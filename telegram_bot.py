import os
import logging
import random
import string
import base64
import requests 
from io import BytesIO
import asyncio

# Импорты для Telegram Bot API (Async V20+)
from telegram import Update
from telegram.ext import (
    Application, 
    MessageHandler, 
    CommandHandler, 
    ContextTypes, 
    filters
)
from telegram.constants import ParseMode 
from flask import Flask, request

# --- ЛОГИКА ОБФУСКАЦИИ (Ядро) ---

KEY_LENGTH = 16 

def generate_key(length: int) -> str:
    """Генерирует случайный ключ для XOR-шифрования."""
    characters = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(characters) for i in range(length))

def xor_obfuscate(data: bytes, key: str) -> str:
    """Применяет XOR-шифрование и кодирует результат в Base64."""
    key_bytes = key.encode('utf-8')
    key_len = len(key_bytes)
    
    obfuscated_bytes = bytearray(data)
    for i in range(len(obfuscated_bytes)):
        obfuscated_bytes[i] ^= key_bytes[i % key_len]
        
    encoded_data = base64.b64encode(obfuscated_bytes)
    return encoded_data.decode('utf-8')

def generate_lua_loader(encoded_data: str, key: str) -> str:
    """Генерирует Lua-код-загрузчик."""
    lua_loader = f"""
-- Дешифровщик Lua XOR (Meloten Bot)
local encoded_data = "{encoded_data}"
local key = "{key}"

local function base64_decode(data)
    -- Requires external base64 lib or implementation
    return base64.decode(data) 
end

local decoded_bytes = base64_decode(encoded_data)
local key_bytes = key
local key_len = #key_bytes
local chunk_bytes = {{}}

for i = 1, #decoded_bytes do
    local byte_value = string.byte(decoded_bytes, i)
    local key_value = string.byte(key_bytes, (i - 1) % key_len + 1)
    local obfuscated_byte = bit.bxor(byte_value, key_value)
    table.insert(chunk_bytes, string.char(obfuscated_byte))
end

local chunk = table.concat(chunk_bytes)
loadstring(chunk)()
"""
    return lua_loader

# --- КОНФИГУРАЦИЯ ---

FALLBACK_TOKEN = '7738098322:AAEPMhu7wD-l1_Qr-4Ljlm1dr6oPinnH_oU' 
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', FALLBACK_TOKEN)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Глобальные объекты
application = Application.builder().token(TOKEN).build()
loop = asyncio.new_event_loop() # Создаем свой цикл событий
asyncio.set_event_loop(loop) # Устанавливаем его как текущий

# --- ОБРАБОТЧИКИ БОТА ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    instructions = (
        "👋 Привет! Я — **Meloten**.\n"
        "Отправь мне **.lua** файл, и я его зашифрую."
    )
    await update.message.reply_text(instructions, parse_mode=ParseMode.MARKDOWN)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    if not document or not document.file_name.lower().endswith('.lua'):
        await update.message.reply_text("Нужен файл с расширением **.lua**.", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        file_info = await context.bot.get_file(document.file_id)
        file_data = BytesIO()
        await file_info.download_to_memory(file_data)
        file_data.seek(0)
        original_data = file_data.read()
        
        obf_key = generate_key(KEY_LENGTH)
        encoded_data_base64 = xor_obfuscate(original_data, obf_key)
        final_obfuscated_code = generate_lua_loader(encoded_data_base64, obf_key)
        
        output_filename = "obf_" + document.file_name
        output_file = BytesIO(final_obfuscated_code.encode('utf-8'))
        output_file.name = output_filename
        
        await update.message.reply_document(output_file, 
                                     caption=f"Ключ: `{obf_key}`",
                                     parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"Ошибка: {e}")

# --- НАСТРОЙКА ---

def setup_bot():
    """Добавляет хендлеры и инициализирует приложение."""
    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # Инициализируем PTB внутри нашего цикла событий
    # Application.initialize() и start() - асинхронные
    loop.run_until_complete(application.initialize())
    loop.run_until_complete(application.start())
    logger.info("Bot application initialized.")

def set_webhook_url():
    """Устанавливает Webhook."""
    RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    if RENDER_EXTERNAL_HOSTNAME:
        webhook_url = f'https://{RENDER_EXTERNAL_HOSTNAME}/{TOKEN}'
        telegram_api_url = f'https://api.telegram.org/bot{TOKEN}/setWebhook'
        try:
            response = requests.get(telegram_api_url, params={'url': webhook_url, 'drop_pending_updates': 'True'})
            if response.status_code == 200:
                logger.info(f"Webhook set: {webhook_url}")
            else:
                logger.error(f"Webhook failed: {response.text}")
        except Exception as e:
            logger.error(f"Webhook error: {e}")

# --- FLASK ROUTING ---

@app.route('/', methods=['GET'])
def index():
    return "Bot is running.", 200

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook_handler():
    """Синхронный Flask обработчик, вызывающий асинхронный код бота."""
    if request.method == "POST":
        try:
            # Получаем JSON
            json_update = request.get_json(force=True)
            # Создаем объект Update
            update = Update.de_json(json_update, application.bot)
            
            # ВАЖНО: Запускаем process_update внутри нашего loop
            # Это блокирует поток Flask до завершения обработки, 
            # но для простых ботов это ок.
            loop.run_until_complete(application.process_update(update))
            
        except Exception as e:
            logger.error(f"Update error: {e}")
            return 'error', 200
    return 'ok', 200

# Запуск настройки при старте
setup_bot()
set_webhook_url()
