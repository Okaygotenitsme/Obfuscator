import os
import logging
import random
import string
import base64
import requests # Новый импорт для безопасной установки WEBHOOK
from io import BytesIO

# Импорты для Telegram Bot API (Async V20+)
from telegram import Update, Bot 
from telegram.ext import (
    Application, 
    MessageHandler, 
    CommandHandler, 
    ContextTypes, 
    filters
)
# ИСПРАВЛЕНО: ParseMode теперь импортируется из telegram.constants
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
        # Применяем XOR к каждому байту
        obfuscated_bytes[i] ^= key_bytes[i % key_len]
        
    encoded_data = base64.b64encode(obfuscated_bytes)
    return encoded_data.decode('utf-8')

def generate_lua_loader(encoded_data: str, key: str) -> str:
    """
    Генерирует Lua-код-загрузчик, который расшифровывает и выполняет 
    зашифрованные данные во время выполнения (runtime).
    """
    lua_loader = f"""
-- Дешифровщик Lua XOR (Автоматически сгенерирован ботом Meloten)
-- Requires: base64.decode, bit.bxor (или совместимые функции)
local encoded_data = "{encoded_data}"
local key = "{key}"

local function base64_decode(data)
    -- Предполагается, что base64.decode доступна в среде Lua.
    return base64.decode(data) 
end

local decoded_bytes = base64_decode(encoded_data)
local key_bytes = key
local key_len = #key_bytes
local chunk_bytes = {{}}

for i = 1, #decoded_bytes do
    local byte_value = string.byte(decoded_bytes, i)
    local key_value = string.byte(key_bytes, (i - 1) % key_len + 1)
    
    -- Применяем XOR (bit.bxor)
    local obfuscated_byte = bit.bxor(byte_value, key_value)
    
    -- Сохраняем расшифрованный байт
    table.insert(chunk_bytes, string.char(obfuscated_byte))
end

local chunk = table.concat(chunk_bytes)

-- Выполняем расшифрованный код (использует loadstring)
loadstring(chunk)()
"""
    return lua_loader

# --- КОНФИГУРАЦИЯ И WEBHOOK ---

# ⚠️ ВАШ РЕАЛЬНЫЙ ТОКЕН ДЛЯ НАДЕЖНОСТИ
# Используется как резервный, если переменная окружения не найдена
FALLBACK_TOKEN = 'ВАШ_РЕАЛЬНЫЙ_ТОКЕН_ЗДЕСЬ' 

# 1. Попытка получить токен из переменной окружения (предпочтительный, безопасный метод)
TOKEN = os.environ.get('7738098322:AAEPMhu7wD-l1_Qr-4Ljlm1dr6oPinnH_oU')

# 2. Если переменная окружения не найдена, используем резервный токен
if not TOKEN:
    if FALLBACK_TOKEN == 'ВАШ_РЕАЛЬНЫЙ_ТОКЕН_ЗДЕСЬ':
        # Если и переменная окружения отсутствует, и вы не вставили токен
        raise ValueError("ТОКЕН не найден. Пожалуйста, установите TELEGRAM_BOT_TOKEN в Render или вставьте токен в FALLBACK_TOKEN.")
    
    TOKEN = FALLBACK_TOKEN
    logging.warning("Токен получен из FALLBACK_TOKEN. Рекомендуется использовать переменные окружения.")

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Объект Flask
app = Flask(__name__)

# Глобальный объект Application
application = Application.builder().token(TOKEN).build()

# --- АСИНХРОННЫЕ ФУНКЦИИ-ОБРАБОТЧИКИ ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет приветственное сообщение и инструкцию."""
    instructions = (
        "👋 Привет! Я — **Meloten**, бот для шифрования Lua-кодов.\n\n"
        "Чтобы начать обфускацию, просто *отправь мне файл* со своим скриптом. "
        "Главное условие: **расширение файла должно быть .lua**.\n\n"
        "Я верну тебе зашифрованный код, который загрузит и выполнит оригинал во время выполнения."
    )
    await update.message.reply_text(instructions, parse_mode=ParseMode.MARKDOWN)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает загруженный файл, обфусцирует его и отправляет загрузчик."""
    document = update.message.document
    
    if not document or not document.file_name.lower().endswith('.lua'):
        await update.message.reply_text("Пожалуйста, отправьте файл с расширением **.lua**.", parse_mode=ParseMode.MARKDOWN)
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
                                     caption=f"Ваш код обфусцирован с ключом: `{obf_key}`",
                                     parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"Ошибка при обработке файла: {e}")
        await update.message.reply_text(f"Произошла ошибка при обфускации файла: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логирование ошибок."""
    logger.error("Произошла ошибка в обработчике:", exc_info=context.error)

# --- НАСТРОЙКА И ЗАПУСК WEBHOOK (ИСПРАВЛЕНА) ---

def setup_application():
    """Добавляет обработчики к объекту Application."""
    
    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_error_handler(error_handler)
    
    logger.info("Обработчики Application настроены.")

def set_webhook_url():
    """Устанавливает URL Webhook, используя синхронный запрос, чтобы избежать конфликтов asyncio."""
    RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    
    if RENDER_EXTERNAL_HOSTNAME:
        # Формируем URL Webhook и URL для Telegram API
        webhook_url = f'https://{RENDER_EXTERNAL_HOSTNAME}/{TOKEN}'
        telegram_api_url = f'https://api.telegram.org/bot{TOKEN}/setWebhook'
        
        try:
            # Используем requests для синхронной установки Webhook
            response = requests.get(telegram_api_url, params={'url': webhook_url})
            
            if response.status_code == 200 and response.json().get('ok'):
                logger.info(f"Webhook успешно установлен на: {webhook_url}")
            else:
                logger.error(f"Не удалось установить Webhook. Ответ: {response.text}")
        except Exception as e:
            logger.error(f"Ошибка при попытке установки Webhook: {e}")
    else:
        logger.warning("RENDER_EXTERNAL_HOSTNAME не найден. Пропуск установки Webhook.")


# --- ОБРАБОТЧИКИ FLASK ---

@app.route('/', methods=['GET'])
def hello():
    """Проверка доступности сервиса Render."""
    return "Obfuscator Bot is running.", 200

@app.route(f'/{TOKEN}', methods=['POST'])
async def webhook_handler():
    """Обрабатывает входящие обновления от Telegram и передает их Application."""
    if request.method == "POST":
        # Передаем обновление в очередь Application для асинхронной обработки
        await application.update_queue.put(
            Update.de_json(request.get_json(force=True), application.bot)
        )
    return 'ok'

# Инициализация Application
setup_application()

# Установка Webhook при запуске сервиса Gunicorn/Render
set_webhook_url()
