import os
import telegram
from telegram.ext import Updater, MessageHandler, Filters
from flask import Flask, request
import logging
import random
import string
import base64
from io import BytesIO

# --- КОНФИГУРАЦИЯ И ЛОГИКА ОБФУСКАЦИИ (Ядро) ---
KEY_LENGTH = 16 

def xor_obfuscate(data, key):
    """Применяет XOR-шифрование и кодирует результат в Base64."""
    key_bytes = key.encode('utf-8')
    key_len = len(key_bytes)
    
    data_bytes = data if isinstance(data, bytes) else data.encode('utf-8')

    obfuscated_bytes = bytearray(data_bytes)
    for i in range(len(obfuscated_bytes)):
        obfuscated_bytes[i] ^= key_bytes[i % key_len]
        
    encoded_data = base64.b64encode(obfuscated_bytes)
    return encoded_data.decode('utf-8')

def generate_lua_loader(encoded_data, key):
    """
    Генерирует Lua-код-загрузчик, который расшифровывает и выполняет 
    зашифрованные данные во время выполнения (runtime).
    """
    # Предполагается, что Lua-среда имеет доступ к Base64 и bit.bxor.

    lua_loader = f"""
-- Дешифровщик Lua XOR (Автоматически сгенерирован ботом)
-- Требует функций Base64-декодирования и bit-операций (bit.bxor)
local encoded_data = "{encoded_data}"
local key = "{key}"

local function base64_decode(data)
    -- Используем base64.decode (Предполагается, что функция доступна в среде)
    return base64.decode(data) 
end

local decoded_bytes = base64_decode(encoded_data)
local key_bytes = key
local key_len = #key_bytes
local chunk_bytes = {{}}

for i = 1, #decoded_bytes do
    local byte_value = string.byte(decoded_bytes, i)
    local key_value = string.byte(key_bytes, (i - 1) % key_len + 1)
    
    -- Применяем XOR
    local obfuscated_byte = bit.bxor(byte_value, key_value)
    
    -- Сохраняем расшифрованный байт
    table.insert(chunk_bytes, string.char(obfuscated_byte))
end

local chunk = table.concat(chunk_bytes)

-- Выполняем расшифрованный код (использует loadstring)
loadstring(chunk)()
"""
    return lua_loader

def generate_key(length):
    """Генерирует случайный ключ для XOR-шифрования."""
    characters = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(characters) for i in range(length))

# --- ОСНОВНОЙ КОД БОТА И WEBHOOK ---

# Инициализация и получение токена из переменных окружения Render
# ИСПРАВЛЕНИЕ: Мы ищем переменную окружения по имени 'TELEGRAM_BOT_TOKEN'
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен в переменных окружения Render.")

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация Flask и Updater
app = Flask(__name__)
updater = Updater(TOKEN, use_context=True)
dispatcher = updater.dispatcher
bot = updater.bot 

def handle_file(update, context):
    """Обрабатывает загруженный файл."""
    document = update.message.document
    
    if not document:
        update.message.reply_text("Пожалуйста, отправьте файл для обфускации.")
        return

    # Скачивание файла
    file_info = context.bot.get_file(document.file_id)
    file_data = BytesIO()
    file_info.download(out=file_data)
    file_data.seek(0)
    
    try:
        original_data = file_data.read()
        obf_key = generate_key(KEY_LENGTH)
        
        # 1. Обфускация
        encoded_data_base64 = xor_obfuscate(original_data, obf_key)
        # 2. Генерация загрузчика
        final_obfuscated_code = generate_lua_loader(encoded_data_base64, obf_key)
        
        # Подготовка файла к отправке
        output_filename = "obf_" + document.file_name
        output_file = BytesIO(final_obfuscated_code.encode('utf-8'))
        output_file.name = output_filename
        
        # Отправка обфусцированного файла
        update.message.reply_document(output_file, 
                                     caption=f"Ваш код обфусцирован с ключом: `{obf_key}`",
                                     parse_mode=telegram.ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"Ошибка при обработке файла: {e}")
        update.message.reply_text("Произошла ошибка при обфускации файла.")

dispatcher.add_handler(MessageHandler(Filters.document, handle_file))

# --- ОБРАБОТЧИКИ WEBHOOK (ДЛЯ RENDER) ---

@app.route('/', methods=['GET'])
def hello():
    """Проверка доступности сервиса Render."""
    return "Obfuscator Bot is running.", 200

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    """Обрабатывает входящие обновления от Telegram."""
    if request.method == "POST":
        update = telegram.Update.de_json(request.get_json(force=True), bot)
        dispatcher.process_update(update)
    return 'ok'

def set_webhook_url():
    """Устанавливает URL Webhook, используя адрес Render."""
    RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    if RENDER_EXTERNAL_HOSTNAME:
        # Полный URL, куда Telegram должен отправлять обновления
        webhook_url = f'https://{RENDER_EXTERNAL_HOSTNAME}/{TOKEN}'
        
        # Устанавливаем Webhook
        success = bot.set_webhook(url=webhook_url)
        if success:
            logger.info(f"Webhook успешно установлен на: {webhook_url}")
        else:
            logger.error("Не удалось установить Webhook. Проверьте токен или логи.")
    else:
        logger.warning("RENDER_EXTERNAL_HOSTNAME не найден. Пропуск установки Webhook.")

# Вызываем функцию установки Webhook при запуске сервиса Gunicorn
set_webhook_url()
