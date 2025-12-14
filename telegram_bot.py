import os
import logging
import random
import string
import base64
import requests 
from io import BytesIO
import time
from flask import Flask, request
import re 
import asyncio
import warnings

# --- ИМПОРТЫ TELEGRAM ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup 
from telegram.ext import (
    Application, 
    MessageHandler, 
    CommandHandler, 
    ContextTypes, 
    filters,
    ApplicationBuilder,
    CallbackQueryHandler
)
from telegram.constants import ParseMode 
from telegram.warnings import PTBUserWarning

# --- КОНФИГУРАЦИЯ ---

FALLBACK_TOKEN = '7738098322:AAEPMhu7wD-l1_Qr-4Ljlm1dr6oPinnH_oU' 
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', FALLBACK_TOKEN)
PORT = int(os.getenv('PORT', '8443')) 
DEFAULT_LANG = 'ru' 

# Скрываем предупреждения, связанные с использованием Application в асинхронном контексте Flask
warnings.filterwarnings("ignore", category=PTBUserWarning)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Инициализация Flask
app = Flask(__name__)

# Инициализация ApplicationBuilder 
application = (
    ApplicationBuilder()
    .token(TOKEN)
    .connect_timeout(30.0)
    .read_timeout(30.0)
    .write_timeout(30.0)
    .build()
)

# --- ДВУЯЗЫЧНЫЕ СООБЩЕНИЯ ---
BILINGUAL_TEXTS = {
    'start': {
        'en': "👋 **Meloten Obfuscator**\n\n**INSTRUCTIONS:**\n1\\. Send your \\.lua or \\.txt file\\.\n2\\. Select the target platform\\.\n3\\. Get the file and key\\.",
        'ru': "👋 **Meloten Obfuscator**\n\n**ИНСТРУКЦИЯ:**\n1\\. Отправь файл \\.lua или \\.txt\\.\n2\\. Выбери целевую платформу\\.\n3\\. Получи файл и ключ\\.",
    },
    'language_select': {
        'en': "🌐 Select your language:",
        'ru': "🌐 Выберите язык:", 
    },
    'invalid_file': {
        'en': "⛔ Only \\.lua or \\.txt files are accepted\\!",
        'ru': "⛔ Только файлы \\.lua и \\.txt\\!",
    },
    'file_accepted': {
        'en': "File `{}` accepted\\.\nSelect the target platform:",
        'ru': "Файл `{}` принят\\.\nВыберите целевую платформу:",
    },
    'file_expired': {
        'en': "⚠️ File is expired or not found\\. Please send it again\\.",
        'ru': "⚠️ Файл устарел или не найден\\. Отправьте снова\\.",
    },
    'encrypting': {
        'en': "⏳ Encrypting file: `{}` for platform `{}`\\.\\.\\.",
        'ru': "⏳ Шифрую файл: `{}` для платформы `{}`\\.\\.\\.",
    },
    'done': {
        'en': "✅ Done\\!\n🔑 Key: ||`{}`||\n⚙️ Mode: `{}`",
        'ru': "✅ Готово\\!\n🔑 Ключ: ||`{}`||\n⚙️ Режим: `{}`",
    },
    'error': {
        'en': "❌ Critical Error: `{}`",
        'ru': "❌ Критическая ошибка: `{}`",
    },
    'lang_set': {
        'en': "Language set to English\\. Use /start to begin\\.",
        'ru': "Язык установлен на Русский\\. Используйте /start для начала\\.",
    }
}

def get_text(key: str, lang: str) -> str:
    """Получает текст на выбранном языке, с возвратом на язык по умолчанию."""
    return BILINGUAL_TEXTS.get(key, {}).get(lang, BILINGUAL_TEXTS.get(key, {}).get(DEFAULT_LANG, key))

def get_user_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Получает язык пользователя из user_data."""
    return context.user_data.get('language', DEFAULT_LANG)


# --- УТИЛИТЫ ОБФУСКАЦИИ ---

KEY_LENGTH = 32
TIME_LIMIT = 0.05 

def generate_key(length: int) -> str:
    characters = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(characters) for i in range(length))

def xor_obfuscate(data: bytes, key: str) -> str:
    key_bytes = key.encode('utf-8')
    key_len = len(key_bytes)
    obfuscated_bytes = bytearray(data)
    for i in range(len(obfuscated_bytes)):
        obfuscated_bytes[i] ^= key_bytes[i % key_len]
    encoded_data = base64.b64encode(obfuscated_bytes)
    return encoded_data.decode('utf-8')

def escape_markdown_v2(text: str) -> str:
    """Экранирует специальные символы для MarkdownV2."""
    specials = r'\_*[]()~`>#+-=|{}.!'
    for char in specials:
        text = text.replace(char, f'\\{char}')
    text = text.replace('\\\\', '\\\\\\\\') 
    return text

# --- ШАБЛОНЫ ЗАГРУЗЧИКОВ ---

LUA_BASE64_IMPL = """
local b='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
local function B64(data)
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

def get_loader(mode: str, encoded_data: str, final_key: str) -> str:
    # Оставшаяся логика get_loader остается без изменений для обеспечения функциональности
    if mode == 'roblox_exec':
        xor_logic = "local XorFunc = bit.bxor or bit32.bxor"
    elif mode == 'roblox_studio':
        xor_logic = "local XorFunc = bit32.bxor"
    elif mode == 'safe_native':
        xor_logic = "local function XorFunc(a, b) local c=0; local p=1; while a>0 or b>0 do local ra,rb=a%2,b%2 if ra~=rb then c=c+p end a=(a-ra)/2; b=(b-rb)/2; p=p*2 end return c end"
    else: 
        xor_logic = "local XorFunc = (bit and bit.bxor) or (bit32 and bit32.bxor) or function(a,b) local p,c=1,0 while a>0 and b>0 do local ra,rb=a%2,b%2 if ra~=rb then c=c+p end a,b,p=(a-ra)/2,(b-rb)/2,p*2 end if a<b then a=b end while a>0 do local ra=a%2 if ra>0 then c=c+p end a,p=(a-ra)/2,p*2 end return c end"

    split_points = sorted(random.sample(range(1, KEY_LENGTH), 5))
    key_parts = [final_key[0:split_points[0]], final_key[split_points[0]:split_points[1]],
                 final_key[split_points[1]:split_points[2]], final_key[split_points[2]:split_points[3]],
                 final_key[split_points[3]:split_points[4]], final_key[split_points[4]:KEY_LENGTH]]
    
    mini_keys = [generate_key(8) for _ in range(6)]
    encoded_parts = [xor_obfuscate(part.encode('utf-8'), mini_keys[i]) for i, part in enumerate(key_parts)]
    
    indices = [1, 2, 3, 4, 5, 6]; random.shuffle(indices)
    key_assembly_parts = [f"P{i}" for i in indices]
    key_assembly_concat = " .. ".join(key_assembly_parts)
    
    nums = [random.randint(100, 999) for _ in range(3)]
    vars = [generate_key(4) for _ in range(9)]
    
    fuzzing_math = f"""
    local {vars[6]} = ({nums[0]} * {nums[1]}) / {nums[2]} 
    local {vars[7]} = {nums[0]} + {nums[1]} - {vars[6]}
    local {vars[8]} = string.byte("{generate_key(1)}", 1) + 1
    if ({vars[7]} > 0) then {vars[8]} = {vars[8]} - 1 end
    """
    
    FULL_LOADER_LOGIC = f"""
        local encoded_main = "{encoded_data}"
        local {vars[0]} = "{encoded_parts[0]}"
        local {vars[1]} = "{encoded_parts[1]}"
        local {vars[2]} = "{encoded_parts[2]}"
        local {vars[3]} = "{encoded_parts[3]}"
        local {vars[4]} = "{encoded_parts[4]}"
        local {vars[5]} = "{encoded_parts[5]}"

        local K1 = "{mini_keys[0]}"
        local K2 = "{mini_keys[1]}"
        local K3 = "{mini_keys[2]}"
        local K4 = "{mini_keys[3]}"
        local K5 = "{mini_keys[4]}"
        local K6 = "{mini_keys[5]}"

        {LUA_BASE64_IMPL}
        {xor_logic}

        local function Decrypt(data, key)
            local decoded = B64(data)
            local k_len = #key
            local t = {{}}
            
            for i = 1, #decoded do
                local byte_value = string.byte(decoded, i)
                local key_value = string.byte(key, (i - 1) % k_len + 1)
                local obfuscated_byte = XorFunc(byte_value, key_value)
                table.insert(t, string.char(obfuscated_byte))
            end
            return table.concat(t)
        end

        local function GetKeyAndCheck()
            local start_time = os.clock()
            {fuzzing_math}
            
            local P1 = Decrypt({vars[0]}, K1)
            local P2 = Decrypt({vars[1]}, K2)
            local P3 = Decrypt({vars[2]}, K3)
            local P4 = Decrypt({vars[3]}, K4)
            local P5 = Decrypt({vars[4]}, K5)
            local P6 = Decrypt({vars[5]}, K6)

            local FinalKey = {key_assembly_concat}

            local elapsed = os.clock() - start_time
            if elapsed > {TIME_LIMIT} then 
                return nil 
            end

            return FinalKey
        end

        local function CheckEnvironment()
            if getfenv(0) ~= _G then return false end
            if pcall(function() local a = debug.getinfo end) and string.len(debug.traceback()) > 100 then return false end
            return true
        end

        if not CheckEnvironment() then return end 

        local success, res = pcall(function()
            local FinalKey = GetKeyAndCheck()
            if not FinalKey then return nil end
            return Decrypt(encoded_main, FinalKey)
        end)

        local run = loadstring or load
        if success and res then
            local func = run(res)
            if func then func() end
        end
    """
    
    META_KEY = generate_key(8)
    encoded_meta = xor_obfuscate(FULL_LOADER_LOGIC.encode('utf-8'), META_KEY)

    FINAl_SCRIPT = f"""--[[ Meloten MEGA-CHAOS-OBF ({mode}) - Ultimate Self-Modifying Loader ]]
local D = "{encoded_meta}"
local K = "{META_KEY}"

local function GetLogic(s, i)
    return string.byte(s, i)
end

local function ChaosDecrypt(data, key)
    local b='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
    
    local function B64_D(d)
        d = string.gsub(d, '[^'..b..'=]', '')
        local f = function(x)
            if (x == '=') then return '' end
            local r, fr = '', (b:find(x)-1)
            for j=6,1,-1 do r = r .. ((fr % 2^j - fr % 2^(j-1)) > 0 and '1' or '0') end
            return r;
        end
        return (d:gsub('.', f):gsub('%d%d%d?%d?%d?%d?%d?%d?', function(x)
            if (#x ~= 8) then return '' end
            local c=0
            for k=1,8 do c=c+(x:sub(k,k)=='1' and 2^(8-k) or 0) end
            return string.char(c)
        end))
    end

    local decoded = B64_D(data)
    local k_len = #key
    local t = {{}}
    
    for i = 1, #decoded do
        local byte_value = GetLogic(decoded, i)
        local key_value = GetLogic(key, (i - 1) % k_len + 1)
        local xor_result = byte_value ~ key_value 
        if not xor_result then
            local function native_xor(a, b)
                local p, c = 1, 0
                while a > 0 or b > 0 do
                    local ra, rb = a % 2, b % 2
                    if ra ~= rb then c = c + p end
                    a, b, p = (a - ra) / 2, (b - rb) / 2, p * 2
                end
                return c
            end
            xor_result = native_xor(byte_value, key_value)
        end
        
        table.insert(t, string.char(xor_result))
    end
    return table.concat(t)
end

local run = loadstring or load
local code = ChaosDecrypt(D, K)
run(code)()
"""
    
    return FINAl_SCRIPT

# --- ХЕНДЛЕРЫ ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(context)
    start_text = get_text('start', lang)
    await update.message.reply_text(start_text, parse_mode=ParseMode.MARKDOWN_V2)

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(context)
    text = get_text('language_select', lang)
    
    keyboard = [
        [InlineKeyboardButton("English 🇬🇧", callback_data='lang_en')],
        [InlineKeyboardButton("Русский 🇷🇺", callback_data='lang_ru')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(context)
    doc = update.message.document
    
    if not update.message or not doc:
         return 

    filename = doc.file_name.lower()
    
    if not (filename.endswith('.lua') or filename.endswith('.txt')):
        text = get_text('invalid_file', lang)
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        return

    context.user_data['file_id'] = doc.file_id
    context.user_data['file_name'] = doc.file_name

    # Создаем InlineKeyboard для выбора платформы
    platform_keyboard = [
        [InlineKeyboardButton(f"🎮 Roblox (Executors)", callback_data='mode_roblox_exec')],
        [InlineKeyboardButton(f"🛠 Roblox Studio (bit32)", callback_data='mode_roblox_studio')],
        [InlineKeyboardButton(f"🌐 Generic Lua (5.1/JIT)", callback_data='mode_generic')],
        [InlineKeyboardButton(f"🛡 Safe Native Lua (Slow, universal)", callback_data='mode_safe_native')],
    ]
    reply_markup = InlineKeyboardMarkup(platform_keyboard)
    
    escaped_file_name = escape_markdown_v2(doc.file_name)
    text = get_text('file_accepted', lang).format(escaped_file_name)

    await update.message.reply_text(
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id
    
    await query.answer() 
    
    # Обработка выбора языка
    if query.data.startswith('lang_'):
        new_lang = query.data.split('_')[1]
        context.user_data['language'] = new_lang
        text = get_text('lang_set', new_lang)
        await query.edit_message_text(text)
        return
        
    # Обработка выбора режима обфускации
    if query.data.startswith('mode_'):
        mode = query.data.split('mode_')[1]
    else:
        # Неизвестный callback_data
        return

    lang = get_user_lang(context)
    file_id = context.user_data.get('file_id')
    file_name = context.user_data.get('file_name')
    
    if not file_id:
        text = get_text('file_expired', lang)
        await query.edit_message_text(escape_markdown_v2(text), parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        escaped_file_name = escape_markdown_v2(file_name)
        text = get_text('encrypting', lang).format(escaped_file_name, mode)
        
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2)

        f = await context.bot.get_file(file_id)
        bio = BytesIO()
        await f.download_to_memory(bio)
        
        original_data_bytes = bio.getvalue()
        
        if not original_data_bytes:
            raise ValueError("Файл пуст или не содержит данных.")
            
        final_key = generate_key(KEY_LENGTH)
        encoded_data_base64 = xor_obfuscate(original_data_bytes, final_key)
        
        final_code = get_loader(mode, encoded_data_base64, final_key)

        output_file = BytesIO(final_code.encode('utf-8'))
        output_file.name = f"{mode}_{file_name}.lua"

        escaped_key = escape_markdown_v2(final_key)
        
        caption = get_text('done', lang).format(escaped_key, mode)
        
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=output_file,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
        context.user_data.pop('file_id', None)
        context.user_data.pop('file_name', None)


    except Exception as e:
        logger.error(f"Error processing callback: {e}")
        error_message = escape_markdown_v2(str(e))
        error_text = get_text('error', lang).format(error_message)
        
        try:
            await query.edit_message_text(error_text, parse_mode=ParseMode.MARKDOWN_V2)
        except:
             await context.bot.send_message(chat_id, error_text, parse_mode=ParseMode.MARKDOWN_V2)

# --- ЛОГИКА ИНИЦИАЛИЗАЦИИ ДЛЯ GUNICORN ---

def initialize_bot_application():
    """Инициализирует Application асинхронно с помощью asyncio.run и добавляет хендлеры."""
    logger.info("Starting bot initialization...")
    try:
        # 1. Асинхронная инициализация, выполняемая синхронно при старте Gunicorn
        asyncio.run(application.initialize())
        logger.info("Application initialized.")
        
        # 2. Добавление хендлеров
        application.add_handler(CommandHandler('start', start_command))
        application.add_handler(CommandHandler('language', language_command))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        application.add_handler(CallbackQueryHandler(button_callback))
        logger.info("Handlers added.")

        # 3. Установка Webhook
        host = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
        if host:
            # Убеждаемся, что URL Webhook использует HTTPS
            url = f'https://{host}/{TOKEN}'
            response = requests.get(
                f'https://api.telegram.org/bot{TOKEN}/setWebhook', 
                params={'url': url, 'drop_pending_updates': 'True'},
                timeout=10
            )
            if response.status_code == 200 and response.json().get('ok'):
                logger.info(f"Webhook set successfully: {url}")
            else:
                logger.error(f"Webhook fail: {response.text}")
        else:
            logger.warning("RENDER_EXTERNAL_HOSTNAME not set. Webhook not set.")

    except Exception as e:
        logger.error(f"FATAL: Error during initialization or webhook setup: {e}")
        # Re-raise to prevent Gunicorn from starting if initialization failed critically
        raise

# Вызываем функцию инициализации при импорте модуля (то есть при запуске Gunicorn)
initialize_bot_application()

# --- РОУТЫ FLASK (для Webhook) ---

@app.route('/', methods=['GET'])
async def index():
    # Проверка, что Flask работает
    return "Bot is running.", 200

@app.route(f'/{TOKEN}', methods=['POST'])
async def webhook():
    # Обработка входящего Webhook-запроса от Telegram
    if request.method == "POST":
        try:
            data = request.get_json(force=True)
            update = Update.de_json(data, application.bot)
            # Передача обновления в python-telegram-bot
            # application.process_update(update) вызывается асинхронно
            await application.process_update(update) 
        except Exception as e:
            logger.error(f"Update error: {e}")
    return 'ok'
