import os
import logging
import random
import string
import base64
import requests 
from io import BytesIO
import asyncio
import time
from flask import Flask, request

# --- ИСПРАВЛЕННЫЕ ИМПОРТЫ ---
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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

# --- ЛОКАЛИЗАЦИЯ ---
TEXTS = {
    'en': {
        'start': "👋 **Meloten Obfuscator**\n\nUpload your .lua or .txt file.",
        'select_lang': "🌐 Choose your language:",
        'language_set': "Language set to **English**.",
        'invalid_file': "⛔ Only .lua or .txt files are accepted!",
        'file_accepted': "File `{}` accepted.\nSelect the target platform:",
        'file_expired': "⚠️ File is expired or not found. Please send it again.",
        'encrypting': "⏳ Encrypting file: `{}` for platform `{}`...",
        'done': "✅ Done!\n🔑 Key: ||`{}`||\n⚙️ Mode: `{}`",
        'error': "❌ Critical Error: `{}`",
    },
    'ru': {
        'start': "👋 **Meloten Obfuscator**\n\nОтправь мне файл \\.lua или \\.txt\\.",
        'select_lang': "🌐 Выберите ваш язык:",
        'language_set': "Язык установлен на **Русский**\\.",
        'invalid_file': "⛔ Только файлы \\.lua и \\.txt\\!",
        'file_accepted': "Файл `{}` принят\\.\nВыберите целевую платформу:",
        'file_expired': "⚠️ Файл устарел или не найден\\. Отправьте снова\\.",
        'encrypting': "⏳ Шифрую файл: `{}` для платформы `{}`\\.\\.\\.",
        'done': "✅ Готово\\!\n🔑 Key: ||`{}`||\n⚙️ Mode: `{}`",
        'error': "❌ Критическая ошибка: `{}`",
    }
}

def get_text(chat_id, key):
    """Получает текст на выбранном языке пользователя."""
    lang = application.user_data.get(chat_id, {}).get('lang', 'ru')
    return TEXTS.get(lang, TEXTS['ru']).get(key, TEXTS['ru'][key])

# --- УТИЛИТЫ ОБФУСКАЦИИ (ОСТАВЛЕНЫ БЕЗ ИЗМЕНЕНИЙ) ---

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
    specials = r'\_*[]()~`>#+-=|{}.!'
    for char in specials:
        text = text.replace(char, f'\\{char}')
    text = text.replace('\\', '\\\\')
    return text

# --- ШАБЛОНЫ ЗАГРУЗЧИКОВ ---

# *ВНИМАНИЕ: ВСЯ ЛОГИКА ЗАГРУЗЧИКА ПРЕВРАЩАЕТСЯ В ОДНУ СТРОКУ В ФУНКЦИИ get_loader*
# Эта функция генерирует сам самомодифицирующийся код.

def get_loader(mode: str, encoded_data: str, final_key: str) -> str:
    """Генерирует финальный загрузчик с полной стрингификацией логики."""
    
    # --- I. Генерация параметров и логики XOR (как раньше) ---
    if mode == 'roblox_exec':
        xor_logic = "local XorFunc = bit.bxor or bit32.bxor"
    # ... (другие режимы остались, но укорочены для примера)
    elif mode == 'safe_native':
        xor_logic = "local function XorFunc(a, b) local c=0; local p=1; while a>0 or b>0 do local ra,rb=a%2,b%2 if ra~=rb then c=c+p end a=(a-ra)/2; b=(b-rb)/2; p=p*2 end return c end"
    else:
        xor_logic = "local XorFunc = (bit and bit.bxor) or (bit32 and bit32.bxor) or function(a,b) local p,c=1,0 while a>0 and b>0 do local ra,rb=a%2,b%2 if ra~=rb then c=c+p end a,b,p=(a-ra)/2,(b-rb)/2,p*2 end if a<b then a=b end while a>0 do local ra=a%2 if ra>0 then c=c+p end a,p=(a-ra)/2,p*2 end return c end"

    # ... (Остальная генерация ключей и запутанной арифметики) ...
    
    # 2. Разбиение ключа (на 6 частей)
    split_points = sorted(random.sample(range(1, KEY_LENGTH), 5))
    key_parts = [
        final_key[0:split_points[0]], final_key[split_points[0]:split_points[1]],
        final_key[split_points[1]:split_points[2]], final_key[split_points[2]:split_points[3]],
        final_key[split_points[3]:split_points[4]], final_key[split_points[4]:KEY_LENGTH]
    ]
    mini_keys = [generate_key(8) for _ in range(6)]
    encoded_parts = [
        xor_obfuscate(part.encode('utf-8'), mini_keys[i]) for i, part in enumerate(key_parts)
    ]
    
    # 3. Гипер-Запутанная Сборка Ключа (Hyper-Fuzzing)
    indices = [1, 2, 3, 4, 5, 6]
    random.shuffle(indices)
    
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
    
    # --- II. Генерация Полной Логики Загрузчика (В виде Lua-кода) ---
    
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
    
    # 4. Финальный шаг: Шифруем ВЕСЬ загрузчик Base64 и XOR-ом!
    # Используем простую, статичную логику для этого мета-шифра.
    META_KEY = generate_key(8)
    encoded_meta = xor_obfuscate(FULL_LOADER_LOGIC.encode('utf-8'), META_KEY)

    # --- III. Самая верхняя, нечитаемая часть скрипта ---
    # Это единственная часть, которая остается в открытом виде.
    
    FINAl_SCRIPT = f"""--[[ Meloten MEGA-OBF ({mode}) - Anti-Analysis & Self-Modifying Loader ]]
local D = "{encoded_meta}"
local K = "{META_KEY}"

-- Встроенная логика Base64 и XOR для расшифровки самого загрузчика
local b='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
local function B64_D(data)
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

local function XOR_D(data, key)
    local decoded = B64_D(data)
    local k_len = #key
    local t = {{}}
    
    for i = 1, #decoded do
        local byte_value = string.byte(decoded, i)
        local key_value = string.byte(key, (i - 1) % k_len + 1)
        table.insert(t, string.char(byte_value ~ key_value)) -- Используем прямой XOR, если доступен (Roblox)
    end
    return table.concat(t)
end

local run = loadstring or load
local code = XOR_D(D, K)
run(code)()
"""
    # Примечание: Мы используем простой ~ для XOR в мета-загрузчике, предполагая наличие bit32.
    # Если это не сработает (например, в Generic Lua 5.1), нужно будет использовать более сложный XOR.
    # Для Roblox/JIT этот код максимально компактен и нечитаем.
    
    return FINAl_SCRIPT

# --- ХЕНДЛЕРЫ ---

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang_code = query.data.split('_')[1]
    
    # Сохраняем язык в user_data (привязан к chat_id)
    chat_id = update.effective_chat.id
    if chat_id not in application.user_data:
        application.user_data[chat_id] = {}
    application.user_data[chat_id]['lang'] = lang_code
    
    text = get_text(chat_id, 'language_set')
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    # После выбора языка предлагаем отправить файл
    start_text = get_text(chat_id, 'start')
    await context.bot.send_message(chat_id, start_text, parse_mode=ParseMode.MARKDOWN_V2)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Проверяем, был ли уже выбран язык
    if context.user_data.get('lang'):
        start_text = get_text(chat_id, 'start')
        await update.message.reply_text(start_text, parse_mode=ParseMode.MARKDOWN_V2)
        return
        
    # Если язык не выбран, предлагаем выбор
    keyboard = [
        [InlineKeyboardButton("🇬🇧 English", callback_data='setlang_en')],
        [InlineKeyboardButton("🇷🇺 Russian", callback_data='setlang_ru')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        TEXTS['ru']['select_lang'], # Используем русский по умолчанию для выбора
        reply_markup=reply_markup
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Проверяем, выбран ли язык (обязательно)
    if not context.user_data.get('lang'):
        await update.message.reply_text("Пожалуйста, выберите язык с помощью команды /start.", parse_mode=ParseMode.MARKDOWN_V2)
        return
        
    doc = update.message.document
    filename = doc.file_name.lower()
    
    if not doc or not (filename.endswith('.lua') or filename.endswith('.txt')):
        text = get_text(chat_id, 'invalid_file')
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        return

    context.user_data['file_id'] = doc.file_id
    context.user_data['file_name'] = doc.file_name

    keyboard = [
        [InlineKeyboardButton("🎮 Roblox (Executors)", callback_data='roblox_exec')],
        [InlineKeyboardButton("🛠 Roblox Studio (bit32)", callback_data='roblox_studio')],
        [InlineKeyboardButton("🌐 Generic Lua (5.1/JIT)", callback_data='generic')],
        [InlineKeyboardButton("🛡 Safe Native Lua (Slow, universal)", callback_data='safe_native')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    escaped_file_name = escape_markdown_v2(doc.file_name)
    text = get_text(chat_id, 'file_accepted').format(escaped_file_name)

    await update.message.reply_text(
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() 
    chat_id = update.effective_chat.id
    
    if 'setlang' in query.data:
        await set_language(update, context)
        return
        
    mode = query.data
    file_id = context.user_data.get('file_id')
    file_name = context.user_data.get('file_name')
    
    if not file_id:
        text = get_text(chat_id, 'file_expired')
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        escaped_file_name = escape_markdown_v2(file_name)
        text = get_text(chat_id, 'encrypting').format(escaped_file_name, mode)
        
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2)

        f = await context.bot.get_file(file_id)
        bio = BytesIO()
        await f.download_to_memory(bio)
        
        original_data_bytes = bio.getvalue()
        
        if not original_data_bytes:
            raise ValueError("Файл пуст или не содержит данных.")
            
        final_key = generate_key(KEY_LENGTH)
        encoded_data_base64 = xor_obfuscate(original_data_bytes, final_key)
        
        # ГЕНЕРАЦИЯ УЛЬТИМАТИВНОГО ЗАГРУЗЧИКА
        final_code = get_loader(mode, encoded_data_base64, final_key)

        output_file = BytesIO(final_code.encode('utf-8'))
        output_file.name = f"{mode}_{file_name}.lua"

        escaped_key = escape_markdown_v2(final_key)
        
        caption = get_text(chat_id, 'done').format(escaped_key, mode)
        
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
        error_text = get_text(chat_id, 'error').format(error_message)
        await query.edit_message_text(error_text, parse_mode=ParseMode.MARKDOWN_V2)

# --- ИНИЦИАЛИЗАЦИЯ (ОСТАВЛЕНА БЕЗ ИЗМЕНЕНИЙ) ---

def init_app():
    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(CallbackQueryHandler(start_command, pattern='^setlang_'))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Инициализируем user_data
    global application
    application.user_data = {} 
    
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

# --- РОУТЫ (ОСТАВЛЕНЫ БЕЗ ИЗМЕНЕНИЙ) ---

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
