import os
import re
import logging
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict
from contextlib import asynccontextmanager
from urllib.parse import quote

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

from fastapi import FastAPI, Request, Form, status, Response
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

templates = Jinja2Templates(directory="templates")


import httpx

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Database configuration
DB_PATH = os.getenv("DATABASE_PATH", "/app/bot.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Initialize tables
c.executescript("""
    CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        phone TEXT,
        message TEXT,
        created_at TEXT,
        status TEXT DEFAULT 'new'
    );
    
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER,
        file_id TEXT,
        file_name TEXT,
        file_path TEXT,
        sent_at TEXT
    );
    
    CREATE TABLE IF NOT EXISTS user_languages (
        user_id INTEGER PRIMARY KEY,
        language TEXT DEFAULT 'ru'
    );
""")
conn.commit()

# Bot configuration
API_TOKEN = os.getenv("API_TOKEN")
REDIS_URL = os.getenv("REDIS_URL")
APP_URL = os.getenv("APP_URL", "https://web-production-bb98.up.railway.app")
ADMIN_LOGIN1 = os.getenv("ADMIN_LOGIN1")
ADMIN_PASSWORD1 = os.getenv("ADMIN_PASSWORD1")
ADMIN_LOGIN2 = os.getenv("ADMIN_LOGIN2")
ADMIN_PASSWORD2 = os.getenv("ADMIN_PASSWORD2")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
ADMINS = {int(x) for x in os.getenv("ADMINS", "1899643695,1980103568").split(",")}
SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")

# Initialize Redis storage
storage = RedisStorage.from_url(
    REDIS_URL,
    key_builder=DefaultKeyBuilder(prefix="fsm")
)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=storage)

# Initialize FastAPI
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY"))  # Уберите значение по умолчанию

# Конфигурация вебхука
encoded_token = quote(API_TOKEN, safe='').replace(':', '%25253A')
WEBHOOK_PATH = f"/webhook/{encoded_token}"  # Экранируем :
WEBHOOK_URL = f"{APP_URL}{WEBHOOK_PATH}"

# Translation setup
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
        'attach_file': "Прикрепите документ (до 3 файлов), затем нажмите /done",
        'attach_added': "Документ '{}' добавлен. Можно добавить ещё или нажать /done.",
        'attach_max': "Максимум 3 файла. Для отправки нажмите /done",
        'thanks': "Спасибо! Мы свяжемся с вами.",
        'not_added': "Выберите 'Да' или 'Нет'.",
        'faq_not_added': "FAQ пока не доступен.",
        'contacts': "г. Астрахань, ул. Татищева 20\n+7 988 600 56 61",
        'back': "⬅️ Назад",
        'main_menu_btn': "🏠 В главное меню",
        'menu_caption': "Выберите действие:",
        'reply_sent': "Ответ отправлен!",
        'reply_fail': "Ошибка отправки",
        'status_updated': "Статус обновлён!",
        'status_fail': "Ошибка обновления статуса",
        'forbidden': "Доступ запрещён.",
        'login': "Вход в админ-панель",
        'logout': "Выйти",
        'search': "Поиск по имени, сообщению...",
        'status_new': "Новая",
        'status_inwork': "В работе",
        'status_done': "Завершено",
        'loader': "Загрузка...",
        'choose_language': "Выберите язык / Choose language",
        'lang_ru': "🇷🇺 Русский",
        'lang_en': "🇺🇸 English"
    },
    'en': {
        'welcome': "Welcome to LegalBot!",
        'choose_lang': "Choose language / Выберите язык",
        'main_menu': "🏠 Main Menu",
        'consult_button': "Book Consultation",
        'faq_button': "FAQ",
        'contacts_button': "Contacts",
        'admin_panel_button': "Admin Panel",
        'enter_name': "Enter your name:",
        'enter_phone': "Enter phone number:",
        'invalid_phone': "Please enter valid phone (e.g. +19991234567).",
        'describe_problem': "Describe your problem:",
        'attach_ask': "Attach documents?",
        'attach_yes': "Yes",
        'attach_no': "No",
        'attach_file': "Attach files (max 3), then press /done",
        'attach_added': "Added '{}'. Add more or press /done.",
        'attach_max': "Max 3 files. Press /done to submit.",
        'thanks': "Thank you! We'll contact you.",
        'not_added': "Choose 'Yes' or 'No'.",
        'faq_not_added': "FAQ not available yet.",
        'contacts': "Astrakhan, Tatischeva st. 20\n+7 988 600 56 61",
        'back': "⬅️ Back",
        'main_menu_btn': "🏠 Main Menu",
        'menu_caption': "Choose action:",
        'reply_sent': "Reply sent!",
        'reply_fail': "Send error",
        'status_updated': "Status updated!",
        'status_fail': "Update error",
        'forbidden': "Access denied.",
        'login': "Admin Login",
        'logout': "Logout",
        'search': "Search by name, message...",
        'status_new': "New",
        'status_inwork': "In Progress",
        'status_done': "Completed",
        'loader': "Loading...",
        'choose_language': "Choose language / Выберите язык",
        'lang_ru': "🇷🇺 Russian",
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

# Database functions
def save_user_language(user_id: int, lang: str):
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_languages VALUES (?, ?)",
            (user_id, lang)
        )

def get_user_language(user_id: int) -> Optional[str]:
    row = conn.execute(
        "SELECT language FROM user_languages WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    return row[0] if row else None

async def get_lang(state: FSMContext, user_id: int) -> str:
    data = await state.get_data()
    lang = data.get('lang', get_user_language(user_id) or 'ru')
    await state.update_data(lang=lang)
    return lang

# Keyboard helpers
def get_menu_kb(user_id: int, lang: str = 'ru') -> ReplyKeyboardMarkup:
    t = translations[lang]
    buttons = [
        [KeyboardButton(text=t['consult_button'])],
        [KeyboardButton(text=t['faq_button'])],
        [KeyboardButton(text=t['contacts_button'])]
    ]
    if user_id in ADMINS:
        buttons.append([KeyboardButton(text=t['admin_panel_button'])])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_back_kb(lang: str = 'ru') -> ReplyKeyboardMarkup:
    t = translations[lang]
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t['back'])],
            [KeyboardButton(text=t['main_menu_btn'])]
        ],
        resize_keyboard=True
    )

def get_lang_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=translations['ru']['lang_ru'])],
            [KeyboardButton(text=translations['en']['lang_en'])]
        ],
        resize_keyboard=True
    )

# Bot handlers
@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    lang = get_user_language(user_id) or 'ru'
    
    try:
        await bot.send_photo(
            chat_id=message.chat.id,
            photo="https://i.imgur.com/HDFlGu5.png",
            caption=translations[lang]['welcome'],
            reply_markup=get_menu_kb(user_id, lang)
        )
    except Exception as e:
        logging.error(f"Error sending photo: {e}")
        await message.answer(
            translations[lang]['welcome'],
            reply_markup=get_menu_kb(user_id, lang)
        )

# ... (остальные обработчики сообщений из вашего оригинального кода)

# Admin panel routes
@app.get("/admin/login")
def admin_login_page(request: Request):
    if request.session.get("admin"):
        return RedirectResponse("/admin")
    return templates.TemplateResponse("admin_login.html", {"request": request})

@app.post("/admin/login")
async def admin_login(request: Request):
    form_data = await request.form()
    username = form_data.get("username")
    password = form_data.get("password")
    
    if (username == ADMIN_LOGIN1 and password == ADMIN_PASSWORD1) or \
       (username == ADMIN_LOGIN2 and password == ADMIN_PASSWORD2):
        request.session["admin"] = username
        return RedirectResponse("/admin")
    
    return templates.TemplateResponse("admin_login.html", 
        {"request": request, "error": "Invalid credentials"})

@app.post("/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login")

@app.get("/admin")
def admin_panel(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login")
    return templates.TemplateResponse("admin.html", {"request": request})

# Lifespan management
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    webhook_set = False
    try:
        await bot.delete_webhook()
        await bot.set_webhook(
            url=WEBHOOK_URL,
            drop_pending_updates=True,
            allowed_updates=dp.resolve_used_update_types()
        )
        webhook_set = True
        logging.info(f"✅ Webhook successfully set to: {WEBHOOK_URL}")
        
    except Exception as e:
        logging.critical(f"❌ Failed to set webhook: {e}")
        raise
    
    try:
        yield
        
    finally:
        # Shutdown logic
        try:
            if webhook_set:
                await bot.delete_webhook()
                logging.info("🗑 Webhook deleted")
        except Exception as e:
            logging.error(f"⚠️ Error deleting webhook: {e}")

        try:
            await bot.session.close()
            logging.info("🤖 Bot session closed")
        except Exception as e:
            logging.error(f"⚠️ Error closing bot session: {e}")

        try:
            await storage.close()
            logging.info("🗄 Redis storage closed")
        except Exception as e:
            logging.error(f"⚠️ Error closing storage: {e}")

        try:
            conn.close()
            logging.info("🔒 Database connection closed")
        except Exception as e:
            logging.error(f"⚠️ Error closing database: {e}")

# Webhook handler
@app.post(WEBHOOK_PATH)
async def handle_webhook(update: dict):
    try:
        telegram_update = types.Update(**update)
        await dp.feed_update(bot=bot, update=telegram_update)
        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return {"status": "error", "details": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
