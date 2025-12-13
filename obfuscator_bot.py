import os
import telebot # Новая библиотека!
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

# --- ОСНОВНОЙ КОД БОТА И WEBHOOK (С ИСПОЛЬЗОВАНИЕМ TELEBOT) ---

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не установлен в переменных окружения Render.")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# Инициализация бота с новой библиотекой
bot = telebot.TeleBot(TOKEN, threaded=False) 

# --- ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ ---

@bot.message_handler(commands=['start'])
def start_message(message):
    """Отправляет приветственное сообщение и инструкцию."""
    instructions = (
        "👋 Привет! Я — **Meloten**, бот для шифрования Lua-кодов.\n\n"
        "Чтобы начать обфускацию, просто *отправь мне файл* со своим скриптом. "
        "Главное условие: **расширение файла должно быть .lua**.\n\n"
        "Я верну тебе зашифрованный код, который загрузит и выполнит оригинал во время выполнения."
    )
    bot.send_message(message.chat.id, instructions, parse_mode='Markdown')

@bot.message_handler(content_types=['document'])
def handle_file(message):
    """Обрабатывает загруженный файл."""
    if not message.document.file_name.endswith('.lua'):
        bot.send_message(message.chat.id, "Пожалуйста, отправьте файл с расширением **.lua**.", parse_mode='Markdown')
        return

    try:
        # Скачивание файла
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        original_data = downloaded_file
        obf_key = generate_key(KEY_LENGTH)
        
        # 1. Обфускация
        encoded_data_base64 = xor_obfuscate(original_data, obf_key)
        # 2. Генерация загрузчика
        final_obfuscated_code = generate_lua_loader(encoded_data_base64, obf_key)
        
        # Подготовка файла к отправке
        output_filename = "obf_" + message.document.file_name
        output_file = BytesIO(final_obfuscated_code.encode('utf-8'))
        output_file.name = output_filename
        
        # Отправка обфусцированного файла
        caption_text = f"Ваш код обфусцирован с ключом: `{obf_key}`"
        bot.send_document(message.chat.id, output_file, 
                          caption=caption_text, 
                          parse_mode='Markdown',
                          visible_file_name=output_filename)
        
    except Exception as e:
        logger.error(f"Ошибка при обработке файла: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка при обфускации файла.")

# --- ОБРАБОТЧИКИ WEBHOOK (ДЛЯ RENDER) ---

@app.route('/', methods=['GET'])
def hello():
    """Проверка доступности сервиса Render."""
    return "Obfuscator Bot is running.", 200

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    """Обрабатывает входящие обновления от Telegram."""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return 'ok'
    return '!'

def set_webhook_url():
    """Устанавливает URL Webhook, используя адрес Render."""
    RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    if RENDER_EXTERNAL_HOSTNAME:
        webhook_url = f'https://{RENDER_EXTERNAL_HOSTNAME}/{TOKEN}'
        
        # Устанавливаем Webhook (новая библиотека)
        try:
            bot.set_webhook(url=webhook_url)
            logger.info(f"Webhook успешно установлен на: {webhook_url}")
        except Exception as e:
            logger.error(f"Не удалось установить Webhook: {e}")
    else:
        logger.warning("RENDER_EXTERNAL_HOSTNAME не найден. Пропуск установки Webhook.")

# Вызываем функцию установки Webhook при запуске сервиса Gunicorn
set_webhook_url()
