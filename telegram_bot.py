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
import re 

# --- ИМПОРТЫ ---
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

# --- КОНФИГУРАЦИЯ ---

FALLBACK_TOKEN = '7738098322:AAEPMhu7wD-l1_Qr-4Ljlm1dr6oPinnH_oU' 
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', FALLBACK_TOKEN)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
# Инициализация asyncio для работы с Webhook
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

# --- ДВУЯЗЫЧНЫЕ СООБЩЕНИЯ (БЕЗ ВЫБОРА ЯЗЫКА) ---
BILINGUAL_TEXTS = {
    # Краткая инструкция по запросу пользователя
    'start': (
        "👋 **Meloten Obfuscator**\n\n"
        "**INSTRUCTIONS / ИНСТРУКЦИЯ:**\n"
        "1\\. Send your \\.lua or \\.txt file / Отправь файл \\.lua или \\.txt\\.\n"
        "2\\. Select the target platform / Выбери целевую платформу\\.\n"
        "3\\. Get the file and key / Получи файл и ключ\\."
    ),
    'invalid_file': "⛔ Only \\.lua or \\.txt files are accepted / Только файлы \\.lua и \\.txt\\!",
    'file_accepted': "File `{}` accepted / Файл `{}` принят\\.\nSelect the target platform / Выберите целевую платформу:",
    'file_expired': "⚠️ File is expired or not found / Файл устарел или не найден\\. Please send it again / Отправьте снова\\.",
    'encrypting': "⏳ Encrypting file: `{}` for platform `{}` / Шифрую файл: `{}` для платформы `{}`\\.\\.\\.",
    'done': "✅ Done / Готово\\!\n🔑 Key / Ключ: ||`{}`||\n⚙️ Mode / Режим: `{}`",
    'error': "❌ Critical Error / Критическая ошибка: `{}`",
}

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
    """Экранирует специальные символы для MarkdownV2, включая двойное экранирование обратного слеша."""
    specials = r'\_*[]()~`>#+-=|{}.!'
    for char in specials:
        text = text.replace(char, f'\\{char}')
    text = text.replace('\\', '\\\\')
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
    # Отправляем двуязычную, краткую инструкцию
    start_text = BILINGUAL_TEXTS['start']
    await update.message.reply_text(start_text, parse_mode=ParseMode.MARKDOWN_V2)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
        
    # Важно: .document будет None, если это не файл, но filters.Document.ALL это должно отсечь
    doc = update.message.document
    
    # Проверка, что update.message и doc существуют
    if not update.message or not doc:
         # Это не должно происходить, если фильтр работает правильно, но на всякий случай
         return 

    filename = doc.file_name.lower()
    
    if not (filename.endswith('.lua') or filename.endswith('.txt')):
        text = BILINGUAL_TEXTS['invalid_file']
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        return

    context.user_data['file_id'] = doc.file_id
    context.user_data['file_name'] = doc.file_name

    # Создаем InlineKeyboard для выбора платформы
    keyboard = [
        [InlineKeyboardButton("🎮 Roblox (Executors)", callback_data='roblox_exec')],
        [InlineKeyboardButton("🛠 Roblox Studio (bit32)", callback_data='roblox_studio')],
        [InlineKeyboardButton("🌐 Generic Lua (5.1/JIT)", callback_data='generic')],
        [InlineKeyboardButton("🛡 Safe Native Lua (Slow, universal)", callback_data='safe_native')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    escaped_file_name = escape_markdown_v2(doc.file_name)
    text = BILINGUAL_TEXTS['file_accepted'].format(escaped_file_name)

    await update.message.reply_text(
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id
    
    await query.answer() 
        
    mode = query.data
    file_id = context.user_data.get('file_id')
    file_name = context.user_data.get('file_name')
    
    if not file_id:
        text = BILINGUAL_TEXTS['file_expired']
        await query.edit_message_text(escape_markdown_v2(text), parse_mode=ParseMode.MARKDOWN_V2)
        return

    try:
        escaped_file_name = escape_markdown_v2(file_name)
        text = BILINGUAL_TEXTS['encrypting'].format(escaped_file_name, mode)
        
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
        
        caption = BILINGUAL_TEXTS['done'].format(escaped_key, mode)
        
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
        error_text = BILINGUAL_TEXTS['error'].format(error_message)
        
        try:
            await query.edit_message_text(error_text, parse_mode=ParseMode.MARKDOWN_V2)
        except:
             await context.bot.send_message(chat_id, error_text, parse_mode=ParseMode.MARKDOWN_V2)

# --- ИНИЦИАЛИЗАЦИЯ ПРИЛОЖЕНИЯ ---

def init_app():
    # 1. Обработчик команды /start
    application.add_handler(CommandHandler('start', start_command))
    
    # 2. Обработчик документов (ВСЕГДА ЛОВИТ ФАЙЛЫ)
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # 3. Обработчик кнопок обфускации
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
            # Устанавливаем Webhook с drop_pending_updates=True
            requests.get(
                f'https://api.telegram.org/bot{TOKEN}/setWebhook', 
                params={'url': url, 'drop_pending_updates': 'True'},
                timeout=10
            )
            logger.info(f"Webhook set: {url}")
        except Exception as e:
            logger.error(f"Webhook fail: {e}")

# --- РОУТЫ FLASK (для Webhook) ---

@app.route('/', methods=['GET'])
def index():
    # Проверка, что Flask работает
    return "Bot is running.", 200

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    # Обработка входящего Webhook-запроса от Telegram
    if request.method == "POST":
        try:
            update = Update.de_json(request.get_json(force=True), application.bot)
            # Передача обновления в python-telegram-bot
            loop.run_until_complete(application.process_update(update))
        except Exception as e:
            logger.error(f"Update error: {e}")
    return 'ok'

init_app()
set_webhook()
