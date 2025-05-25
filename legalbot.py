import asyncio
import logging
import sqlite3
import os
import re
from typing import Any, Awaitable, Callable, Dict

from redis.asyncio.connection import ConnectionError as RedisConnectionError

from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

from fastapi import FastAPI, Request, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
import secrets

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Проверка и получение необходимых переменных окружения
API_TOKEN = os.getenv("API_TOKEN")
if not API_TOKEN:
    raise ValueError("API_TOKEN is not set")

REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    raise ValueError("REDIS_URL environment variable is not set")

# Webhook configuration
WEBHOOK_PATH = f"/webhook/{API_TOKEN}"
APP_URL = os.getenv("APP_URL", "https://web-production-bb98.up.railway.app")
WEBHOOK_URL = APP_URL + WEBHOOK_PATH

ADMIN_CHAT_ID_ENV = os.getenv("ADMIN_CHAT_ID")
if not ADMIN_CHAT_ID_ENV:
    raise ValueError("ADMIN_CHAT_ID is not set")
ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_ENV)

ADMIN_LOGIN1 = os.getenv("ADMIN_LOGIN1")
ADMIN_PASSWORD1 = os.getenv("ADMIN_PASSWORD1")
ADMIN_LOGIN2 = os.getenv("ADMIN_LOGIN2")
ADMIN_PASSWORD2 = os.getenv("ADMIN_PASSWORD2")

ADMINS = {1899643695, 1980103568}  # Можно расширить

# Инициализация Redis
try:
    storage = RedisStorage.from_url(
        REDIS_URL,
        key_builder=DefaultKeyBuilder(prefix="fsm")
    )
    logging.info(f"Initialized Redis storage with URL: {REDIS_URL.split('@')[-1]}")
except Exception as e:
    logging.error(f"Failed to initialize Redis storage: {e}")
    raise

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=storage)

# Инициализация FastAPI
app = FastAPI()

# Для шаблонов и статики
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
security = HTTPBasic()

# Инициализация базы данных
conn = sqlite3.connect("bot.db", check_same_thread=False)
c = conn.cursor()
c.execute("""
    CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        phone TEXT,
        message TEXT,
        created_at TEXT,
        status TEXT DEFAULT 'new'
    )""")
c.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        file_id TEXT,
        file_name TEXT,
        sent_at TEXT
    )""")
c.execute("""
    CREATE TABLE IF NOT EXISTS user_languages (
        user_id INTEGER PRIMARY KEY,
        language TEXT DEFAULT 'ru'
    )""")
conn.commit()

# --- Мультиязычность ---
translations = {
    'ru': {
        'welcome': "Добро пожаловать в LegalBot!",
        'choose_lang': "Выберите язык / Choose language",
        'main_menu': "🏠 Главное меню",
        'consult_button': "Записаться на консультацию",
        'faq_button': "Часто задаваемые вопросы",
        'contacts_button': "Контакты",
        'admin_panel_button': "Админ-панель",
        'enter_name': "Введите ваше имя:",
        'enter_phone': "Введите номер телефона:",
        'invalid_phone': "Пожалуйста, введите корректный номер телефона (например, +79991234567).",
        'describe_problem': "Опишите вашу проблему:",
        'attach_ask': "У вас есть документ, который вы хотите прикрепить?",
        'attach_yes': "Да",
        'attach_no': "Нет",
        'attach_file': "Прикрепите, пожалуйста, документ (до 3-х файлов, отправляйте по одному). После отправки всех файлов нажмите /done",
        'attach_added': "Документ '{}' добавлен. Можете добавить ещё или нажать /done.",
        'attach_max': "Можно прикрепить не более 3-х файлов. Если хотите отправить заявку, нажмите /done",
        'thanks': "Спасибо! Мы свяжемся с вами.",
        'not_added': "Пожалуйста, выберите 'Да' или 'Нет'.",
        'faq_not_added': "Часто задаваемые вопросы пока не добавлены.",
        'contacts': "г. Астрахань, ул. Татищева 20\n+7 988 600 56 61",
        'back': "⬅️ Назад",
        'main_menu_btn': "🏠 В главное меню",
        'menu_caption': "Выберите действие:",
        'reply_sent': "Ответ отправлен!",
        'reply_fail': "Не удалось отправить ответ",
        'status_updated': "Статус обновлен!",
        'status_fail': "Ошибка при обновлении статуса",
        'forbidden': "Доступ запрещён.",
        'login': "Вход в админ-панель",
        'logout': "Выйти",
        'search': "Поиск по имени, сообщению и т.д.",
        'status_new': "Новая",
        'status_inwork': "В работе",
        'status_done': "Готово",
        'loader': "Загрузка заявок...",
        'choose_language': "Выберите язык / Choose language",
        'lang_ru': "🇷🇺 Русский",
        'lang_en': "🇺🇸 English"
    },
    'en': {
        'welcome': "Welcome to LegalBot!",
        'choose_lang': "Choose your language / Выберите язык",
        'main_menu': "🏠 Main menu",
        'consult_button': "Book a consultation",
        'faq_button': "Frequently Asked Questions",
        'contacts_button': "Contacts",
        'admin_panel_button': "Admin panel",
        'enter_name': "Please enter your name:",
        'enter_phone': "Please enter your phone number:",
        'invalid_phone': "Please enter a valid phone number (e.g., +19991234567).",
        'describe_problem': "Describe your problem:",
        'attach_ask': "Do you want to attach a document?",
        'attach_yes': "Yes",
        'attach_no': "No",
        'attach_file': "Please attach a document (up to 3 files, send one at a time). After uploading all files, press /done",
        'attach_added': "Document '{}' was added. You can add more or press /done.",
        'attach_max': "You can attach up to 3 files only. To submit the request, press /done",
        'thanks': "Thank you! We will contact you soon.",
        'not_added': "Please choose 'Yes' or 'No'.",
        'faq_not_added': "Frequently asked questions not added yet.",
        'contacts': "Astrakhan, Tatischeva st. 20\n+7 988 600 56 61",
        'back': "⬅️ Back",
        'main_menu_btn': "🏠 Main menu",
        'menu_caption': "Choose an action:",
        'reply_sent': "Reply sent!",
        'reply_fail': "Failed to send reply",
        'status_updated': "Status updated!",
        'status_fail': "Status update error",
        'forbidden': "Access denied.",
        'login': "Admin panel login",
        'logout': "Logout",
        'search': "Search by name, message, etc.",
        'status_new': "New",
        'status_inwork': "In progress",
        'status_done': "Done",
        'loader': "Loading requests...",
        'choose_language': "Choose your language / Выберите язык",
        'lang_ru': "🇷🇺 Русский",
        'lang_en': "🇺🇸 English"
    }
}

class RequestForm(StatesGroup):
    name = State()
    phone = State()
    message = State()
    attach_doc_choice = State()
    attach_docs = State()
    language = State()

def save_user_language(user_id: int, lang: str):
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_languages (user_id, language) VALUES (?, ?)",
            (user_id, lang)
        )

def get_user_language(user_id: int) -> str:
    row = conn.execute(
        "SELECT language FROM user_languages WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row[0] if row else None

def get_menu_kb(user_id: int, lang: str = 'ru'):
    t = translations[lang]
    keyboard = [
        [KeyboardButton(text=t['consult_button'])],
        [KeyboardButton(text=t['faq_button'])],
        [KeyboardButton(text=t['contacts_button'])]
    ]
    if user_id in ADMINS:
        keyboard.append([KeyboardButton(text=t['admin_panel_button'])])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_back_kb(lang='ru'):
    t = translations[lang]
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t['back'])],
            [KeyboardButton(text=t['main_menu_btn'])]
        ],
        resize_keyboard=True
    )

def get_lang_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=translations['ru']['lang_ru'])],
            [KeyboardButton(text=translations['en']['lang_en'])]
        ],
        resize_keyboard=True
    )

async def get_lang(state: FSMContext, user_id: int = None):
    data = await state.get_data()
    lang = data.get('lang')
    if not lang and user_id:
        lang = get_user_language(user_id)
    return lang or 'ru'

@dp.message(CommandStart()) 
async def start(message: types.Message, state: FSMContext):
    logging.info(f"User {message.from_user.id} state before clear: {await state.get_state()}")
    await state.clear()
    logging.info(f"User {message.from_user.id} state after clear: {await state.get_state()}")
    # ... остальной код ...
    user_id = message.from_user.id
    saved_lang = get_user_language(user_id)
    if not saved_lang:
        await state.set_state(RequestForm.language)
        current_state = await state.get_state()
        logging.info(f"STATE SET AFTER START: {current_state}")
        await message.answer(
            translations['ru']['choose_language'], 
            reply_markup=get_lang_kb()
        )
        return
    lang = saved_lang
    await state.update_data(lang=lang)
    await bot.send_photo(
        chat_id=message.chat.id,
        photo="AgACAgIAAxkBAAE1YB1oMkDR4lZwFBBjnUnPc4tHstWRRwAC4esxG9dOmUnr1RkgaeZ_hQEAAwIAA3kAAzYE",
        caption=translations[lang]['welcome'],
        reply_markup=get_menu_kb(user_id, lang)
    )

@dp.message(RequestForm.language, F.text)
async def choose_lang(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    logging.info(f"LANG HANDLER STATE: {current_state}")
    logging.info(f"LANG SELECTED: {message.text}")
    text = message.text.strip()
    
    if text == translations['ru']['lang_ru']:
        lang = 'ru'
    elif text == translations['en']['lang_en']:
        lang = 'en'
    else:
        await message.answer(
            "Пожалуйста, выберите язык кнопкой / Please choose language with button.",
            reply_markup=get_lang_kb()
        )
        logging.info("Некорректный выбор языка, просим выбрать снова.")
        return

    user_id = message.from_user.id
    save_user_language(user_id, lang)
    await state.update_data(lang=lang)
    await state.clear()
    
    try:
        await bot.send_photo(
            chat_id=message.chat.id,
            photo="AgACAgIAAxkBAAE1YB1oMkDR4lZwFBBjnUnPc4tHstWRRwAC4esxG9dOmUnr1RkgaeZ_hQEAAwIAA3kAAzYE",
            caption=translations[lang]['welcome'],
            reply_markup=get_menu_kb(user_id, lang)
        )
        logging.info(f"Successfully sent welcome message in {lang}")
    except Exception as e:
        logging.error(f"Error sending welcome message: {str(e)}")
        try:
            await message.answer(
                translations[lang]['welcome'],
                reply_markup=get_menu_kb(user_id, lang)
            )
            logging.info("Sent welcome message without photo")
        except Exception as e2:
            logging.error(f"Error sending text-only welcome: {str(e2)}")
            await message.answer(
                "Ошибка при отправке приветствия. Пожалуйста, напишите /start ещё раз.",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="/start")]],
                    resize_keyboard=True
                )
            )

@dp.message(lambda m: m.text in [translations['ru']['contacts_button'], translations['en']['contacts_button']])
async def contacts(message: types.Message, state: FSMContext):
    lang = await get_lang(state, message.from_user.id)
    await message.answer(translations[lang]['contacts'], reply_markup=get_menu_kb(message.from_user.id, lang))

@dp.message(lambda m: m.text in [translations['ru']['consult_button'], translations['en']['consult_button']])
async def consultation(message: types.Message, state: FSMContext):
    lang = await get_lang(state, message.from_user.id)
    await state.set_state(RequestForm.name)
    await state.update_data(user_id=message.from_user.id, lang=lang)
    await message.answer(translations[lang]['enter_name'], reply_markup=get_back_kb(lang))

@dp.message(RequestForm.name)
async def get_name(message: types.Message, state: FSMContext):
    lang = await get_lang(state, message.from_user.id)
    if message.text in [translations['ru']['back'], translations['en']['back'],
                        translations['ru']['main_menu_btn'], translations['en']['main_menu_btn']]:
        await state.clear()
        await start(message, state)
        return
    await state.update_data(name=message.text)
    await state.set_state(RequestForm.phone)
    await message.answer(translations[lang]['enter_phone'], reply_markup=get_back_kb(lang))

@dp.message(RequestForm.phone)
async def get_phone(message: types.Message, state: FSMContext):
    lang = await get_lang(state, message.from_user.id)
    if message.text in [translations['ru']['back'], translations['en']['back']]:
        await state.set_state(RequestForm.name)
        await message.answer(translations[lang]['enter_name'], reply_markup=get_back_kb(lang))
        return
    if message.text in [translations['ru']['main_menu_btn'], translations['en']['main_menu_btn']]:
        await state.clear()
        await start(message, state)
        return
    if not re.match(r"^\+?\d{10,15}$", message.text):
        await message.answer(translations[lang]['invalid_phone'], reply_markup=get_back_kb(lang))
        return
    await state.update_data(phone=message.text)
    await state.set_state(RequestForm.message)
    await message.answer(translations[lang]['describe_problem'], reply_markup=get_back_kb(lang))

@dp.message(RequestForm.message)
async def after_problem(message: types.Message, state: FSMContext):
    lang = await get_lang(state, message.from_user.id)
    if message.text in [translations['ru']['back'], translations['en']['back']]:
        await state.set_state(RequestForm.phone)
        await message.answer(translations[lang]['enter_phone'], reply_markup=get_back_kb(lang))
        return
    if message.text in [translations['ru']['main_menu_btn'], translations['en']['main_menu_btn']]:
        await state.clear()
        await start(message, state)
        return
    await state.update_data(message=message.text)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=translations[lang]['attach_yes']), KeyboardButton(text=translations[lang]['attach_no'])],
            [KeyboardButton(text=translations[lang]['main_menu_btn'])]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await state.set_state(RequestForm.attach_doc_choice)
    await message.answer(translations[lang]['attach_ask'], reply_markup=kb)

@dp.message(RequestForm.attach_doc_choice)
async def attach_doc_choice(message: types.Message, state: FSMContext):
    lang = await get_lang(state, message.from_user.id)
    if message.text in [translations['ru']['attach_yes'], translations['en']['attach_yes']]:
        await state.set_state(RequestForm.attach_docs)
        await state.update_data(documents=[])
        await message.answer(
            translations[lang]['attach_file'],
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="/done")],
                    [KeyboardButton(text=translations[lang]['main_menu_btn'])]
                ],
                resize_keyboard=True
            )
        )
    elif message.text in [translations['ru']['attach_no'], translations['en']['attach_no']]:
        await finish_request(message, state)
    elif message.text in [translations['ru']['main_menu_btn'], translations['en']['main_menu_btn']]:
        await state.clear()
        await start(message, state)
    else:
        await message.answer(translations[lang]['not_added'])

@dp.message(RequestForm.attach_docs, lambda m: m.document)
async def handle_docs(message: types.Message, state: FSMContext):
    lang = await get_lang(state, message.from_user.id)
    data = await state.get_data()
    docs = data.get('documents', [])
    if len(docs) >= 3:
        await message.answer(translations[lang]['attach_max'])
        return
    docs.append({"file_id": message.document.file_id, "file_name": message.document.file_name})
    await state.update_data(documents=docs)
    await message.answer(translations[lang]['attach_added'].format(message.document.file_name))

@dp.message(RequestForm.attach_docs, lambda m: m.text and m.text.lower() == "/done")
async def done_docs(message: types.Message, state: FSMContext):
    await finish_request(message, state)

@dp.message(RequestForm.attach_docs)
async def attach_docs_menu(message: types.Message, state: FSMContext):
    lang = await get_lang(state, message.from_user.id)
    if message.text in [translations['ru']['main_menu_btn'], translations['en']['main_menu_btn']]:
        await state.clear()
        await start(message, state)
        return

async def finish_request(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('lang') or get_user_language(message.from_user.id) or 'ru'
    from datetime import datetime
    now = datetime.now().isoformat()
    user_id = message.from_user.id
    with conn:
        conn.execute(
            "INSERT INTO requests (user_id, name, phone, message, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, data['name'], data['phone'], data['message'], now, 'new')
        )
        docs = data.get('documents', [])
        for doc in docs:
            conn.execute(
                "INSERT INTO documents (user_id, file_id, file_name, sent_at) VALUES (?, ?, ?, ?)",
                (user_id, doc['file_id'], doc['file_name'], now)
            )
    await bot.send_message(
        ADMIN_CHAT_ID,
        f"Новая заявка:\nИмя: {data['name']}\nТел: {data['phone']}\nПроблема: {data['message']}" +
        ("\nДокументы: " + ", ".join(d['file_name'] for d in docs) if docs else "")
    )
    await message.answer(translations[lang]['thanks'], reply_markup=get_menu_kb(user_id, lang))
    await state.clear()

@dp.message(lambda m: m.text in [translations['ru']['admin_panel_button'], translations['en']['admin_panel_button']])
async def admin_panel(message: types.Message, state: FSMContext):
    lang = await get_lang(state, message.from_user.id)
    if message.from_user.id not in ADMINS:
        await message.answer(translations[lang]['forbidden'])
        return
    admin_url = APP_URL + "/admin"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Перейти в админку", url=admin_url)]
    ])
    await message.answer("Откройте админ-панель:", reply_markup=kb)

@dp.message(lambda m: m.text in [translations['ru']['faq_button'], translations['en']['faq_button']])
async def show_faq(message: types.Message, state: FSMContext):
    lang = await get_lang(state, message.from_user.id)
    await message.answer(translations[lang]['faq_not_added'], reply_markup=get_menu_kb(message.from_user.id, lang))

# --- FastAPI Admin part ---

class ReplyRequest(BaseModel):
    user_id: int
    message: str

class StatusRequest(BaseModel):
    user_id: int
    status: str

def check_admin_credentials(login: str, password: str) -> bool:
    return (
        (login == ADMIN_LOGIN1 and password == ADMIN_PASSWORD1) or
        (login == ADMIN_LOGIN2 and password == ADMIN_PASSWORD2)
    )

@app.get("/admin")
async def admin_panel_page(request: Request, credentials: HTTPBasicCredentials = Depends(security)):
    if not check_admin_credentials(credentials.username, credentials.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    c.execute("""
        SELECT r.id, r.user_id, r.name, r.phone, r.message, r.created_at, r.status,
               GROUP_CONCAT(d.file_name) as files
        FROM requests r
        LEFT JOIN documents d ON r.user_id = d.user_id AND r.created_at = d.sent_at
        GROUP BY r.id
        ORDER BY r.created_at DESC
    """)
    requests = [
        {
            'id': row[0], 'user_id': row[1], 'name': row[2], 'phone': row[3],
            'message': row[4], 'created_at': row[5], 'status': row[6],
            'files': row[7] or ""
        }
        for row in c.fetchall()
    ]
    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "requests": requests}
    )

@app.post("/admin/reply")
async def admin_reply(reply: ReplyRequest, credentials: HTTPBasicCredentials = Depends(security)):
    if not check_admin_credentials(credentials.username, credentials.password):
        raise HTTPException(status_code=401)
    try:
        await bot.send_message(reply.user_id, reply.message)
        return {"status": "success"}
    except Exception as e:
        logging.error(f"Error sending reply: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/status")
async def update_status(status_req: StatusRequest, credentials: HTTPBasicCredentials = Depends(security)):
    if not check_admin_credentials(credentials.username, credentials.password):
        raise HTTPException(status_code=401)
    try:
        c.execute("UPDATE requests SET status = ? WHERE id = ?", 
                 (status_req.status, status_req.user_id))
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        logging.error(f"Error updating status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Webhook endpoint для Telegram
@app.post(WEBHOOK_PATH)
async def bot_webhook(update: dict):
    try:
        logging.info(f"Received webhook update: {update}")
        if not update:
            logging.error("Empty update received")
            return {"error": "Empty update"}
        telegram_update = types.Update(**update)
        await dp.feed_update(bot=bot, update=telegram_update)
        logging.info("Update processed successfully")
        return {"ok": True}
    except Exception as e:
        logging.error(f"General webhook error: {str(e)}", exc_info=True)
        return {"ok": False, "error": str(e)}

# Логирование событий, запуск вебхука и завершение
@app.on_event("startup")
async def on_startup():
    try:
        redis = storage.redis
        await redis.ping()
        logging.info("Successfully connected to Redis")
        await bot.delete_webhook()
        await bot.set_webhook(WEBHOOK_URL)
        logging.info(f"Webhook set to: {WEBHOOK_URL}")
    except RedisConnectionError as e:
        logging.error(f"Redis connection failed: {e}")
        raise
    except Exception as e:
        logging.error(f"Startup error: {e}")
        raise

@app.on_event("shutdown")
async def on_shutdown():
    try:
        await bot.session.close()
        await storage.close()
        logging.info("Bot session and Redis storage closed")
    except Exception as e:
        logging.error(f"Shutdown error: {e}")
        raise

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
