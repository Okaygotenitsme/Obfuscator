import os
import logging
import random
import string
import base64
import requests 
from io import BytesIO
import asyncio
from flask import Flask, request

# --- ИСПРАВЛЕНО: InputFile теперь импортируется из 'telegram' ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile 
from telegram.ext import (
    Application, 
    MessageHandler, 
    CommandHandler, 
    CallbackQueryHandler, 
    ContextTypes, 
    filters,
    ApplicationBuilder
)
from telegram.constants import ParseMode 

# --- КОНФИГУРАЦИЯ ---

FALLBACK_TOKEN = '7738098322:AAEPMhu7wD-l1_Qr-4Ljlm1dr6oPinnH_oU' 
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', FALLBACK_TOKEN)

# Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flask и Loop
app = Flask(__name__)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

application = (
    ApplicationBuilder()
    .token(TOKEN)
    .connect_timeout(30.0)
    .read_timeout(30.0)
    .write_timeout(30.0)
    .build()
)

# --- УТИЛИТЫ ОБФУСКАЦИИ ---

KEY_LENGTH = 32

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

def escape_markdown_v2(text: str) -> str:
    """Экранирует специальные символы MarkdownV2 для подписей."""
    specials = r'_*[]()~`>#+-=|{}.!'
    for char in specials:
        text = text.replace(char, f'\\{char}')
    text = text.replace('\\', '\\\\')
    return text

# --- ШАБЛОНЫ ЗАГРУЗЧИКОВ ---

# Чистый Lua Base64 (Для автономности)
LUA_BASE64_IMPL = """
local b='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
local function base64_decode(data)
    data = string.gsub(data, '[^'..b..'=]', '')
    return (data:gsub('.', function(x)
        if (x == '=') then return '' end
        local r,f='',(b:find(x)-1)
        for i=6,1,-1 do r=r..(f%2^i-f%2^(i-1)>0 and '1' or '0') end
        return r;
    end):gsub('%d%d%d?%d?%d?%d?%d?%d?', function(x)
        if (#x ~= 8) then return '' end
        local c=0
        for i=1,8 do c=c+(x:sub(i,i)=='1' and 2^(8-i) or 0) end
        return string.char(c)
    end))
end
"""

def get_loader(mode: str, encoded_data: str, key: str) -> str:
    """Генерирует загрузчик в зависимости от выбранной платформы."""
    
    # Выбор логики XOR в Lua
    if mode == 'roblox_exec':
        # Executors, часто поддерживают стандартный bit или bit32
        xor_logic = "local bxor = bit.bxor or bit32.bxor"
    elif mode == 'roblox_studio':
        # Studio, использует bit32
        xor_logic = "local bxor = bit32.bxor"
    elif mode == 'generic':
        # LuaJIT, 5.1, 5.3 (стандартный 'bit' или 'bit32')
        # Если нет 'bit' или 'bit32', переходит на медленный нативный XOR
        xor_logic = "local bxor = (bit and bit.bxor) or (bit32 and bit32.bxor) or function(a,b) local p,c=1,0 while a>0 and b>0 do local ra,rb=a%2,b%2 if ra~=rb then c=c+p end a,b,p=(a-ra)/2,(b-rb)/2,p*2 end if a<b then a=b end while a>0 do local ra=a%2 if ra>0 then c=c+p end a,p=(a-ra)/2,p*2 end return c end"
    elif mode == 'safe_native':
        # Чистая Lua-логика, гарантированно работающая везде.
        xor_logic = "local function bxor(a, b) local c=0; local p=1; while a>0 or b>0 do local ra,rb=a%2,b%2 if ra~=rb then c=c+p end a=(a-ra)/2; b=(b-rb)/2; p=p*2 end return c end"
    else:
        # Fallback
        return get_loader('generic', encoded_data, key)

    return f"""--[[ Obfuscated by Meloten ({mode}) ]]
local encoded = "{encoded_data}"
local key = "{key}"

{LUA_BASE64_IMPL}

{xor_logic}

local decoded = base64_decode(encoded)
local k_len = #key
local t = {{}}

for i = 1, #decoded do
    local byte_value = string.byte(decoded, i)
    local key_value = string.byte(key, (i - 1) % k_len + 1)
    
    local obfuscated_byte = bxor(byte_value, key_value)
    
    table.insert(t, string.char(obfuscated_byte))
end

local res = table.concat(t)
local run = loadstring or load
run(res)()
"""

# --- ХЕНДЛЕРЫ ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **Meloten Obfuscator**\n\n"
        "Отправь мне \\.lua файл\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает файл и сохраняет его ID, спрашивает платформу."""
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith('.lua'):
        await update.message.reply_text("⛔ Только файлы \\.lua\\!", parse_mode=ParseMode.MARKDOWN_V2)
        return

    # Сохраняем file_id и file_name в context.user_data 
    context.user_data['file_id'] = doc.file_id
    context.user_data['file_name'] = doc.file_name

    # Создаем клавиатуру
    keyboard = [
        [InlineKeyboardButton("🎮 Roblox (Executors)", callback_data='roblox_exec')],
        [InlineKeyboardButton("🛠 Roblox Studio (bit32)", callback_data='roblox_studio')],
        [InlineKeyboardButton("🌐 Generic Lua (5.1/JIT)", callback_data='generic')],
        [InlineKeyboardButton("🛡 Safe Native Lua (Slow, universal)", callback_data='safe_native')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    escaped_file_name = escape_markdown_v2(doc.file_name)

    await update.message.reply_text(
        f"Файл `{escaped_file_name}` принят\\.\nВыберите целевую платформу:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатие кнопки."""
    query = update.callback_query
    await query.answer() 

    mode = query.data
    file_id = context.user_data.get('file_id')
    file_name = context.user_data.get('file_name')
    
    if not file_id:
        await query.edit_message_text("⚠️ Файл устарел или не найден\\. Отправьте снова\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        escaped_file_name = escape_markdown_v2(file_name)
        await query.edit_message_text(f"⏳ Шифрую файл: `{escaped_file_name}` для **{mode}**\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)

        # Чтение файла
        f = await context.bot.get_file(file_id)
        bio = BytesIO()
        await f.download_to_memory(bio)
        
        original_data_bytes = bio.getvalue()
        
        if not original_data_bytes:
            raise ValueError("Файл пуст или не содержит данных.")
            
        # Шифрование
        obf_key = generate_key(KEY_LENGTH)
        encoded_data_base64 = xor_obfuscate(original_data_bytes, obf_key)
        final_code = get_loader(mode, encoded_data_base64, obf_key)

        # Отправка
        output_file = BytesIO(final_code.encode('utf-8'))
        output_file.name = f"{mode}_{file_name}"

        escaped_key = escape_markdown_v2(obf_key)
        
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=output_file,
            caption=f"✅ Готово\\!\n🔑 Key: ||`{escaped_key}`||\n⚙️ Mode: `{mode}`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
        context.user_data.pop('file_id', None)
        context.user_data.pop('file_name', None)


    except Exception as e:
        logger.error(f"Error processing callback: {e}")
        error_message = escape_markdown_v2(str(e))
        await query.edit_message_text(f"❌ Критическая ошибка: `{error_message}`", parse_mode=ParseMode.MARKDOWN_V2)

# --- ИНИЦИАЛИЗАЦИЯ ---

def init_app():
    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    loop.run_until_complete(application.initialize())
    try:
        loop.run_until_complete(application.start())
    except Exception as e:
        logger.warning(f"App start warning: {e}")
        pass

def set_webhook():
    host = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    if host:
        url = f'https://{host}/{TOKEN}'
        try:
            requests.get(
                f'https://api.telegram.org/bot{TOKEN}/setWebhook', 
                params={'url': url, 'drop_pending_updates': 'True'},
                timeout=10
            )
            logger.info(f"Webhook set: {url}")
        except Exception as e:
            logger.error(f"Webhook fail: {e}")

# --- РОУТЫ ---

@app.route('/', methods=['GET'])
def index():
    return "Bot is running.", 200

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    if request.method == "POST":
        try:
            update = Update.de_json(request.get_json(force=True), application.bot)
            loop.run_until_complete(application.process_update(update))
        except Exception as e:
            logger.error(f"Update error: {e}")
    return 'ok'

init_app()
set_webhook()
