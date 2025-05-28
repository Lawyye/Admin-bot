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
from aiogram.filters import CommandStart, Command
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

from fastapi import FastAPI, Request, Form, status, Response
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import httpx

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

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

# Initialize Redis storage and bot
storage = RedisStorage.from_url(
    REDIS_URL,
    key_builder=DefaultKeyBuilder(prefix="fsm")
)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=storage)

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
        [KeyboardButton(text=t['contacts_button'])],
        [KeyboardButton(text=t['choose_language'])]
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

def get_attach_kb(lang: str = 'ru') -> ReplyKeyboardMarkup:
    t = translations[lang]
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t['attach_yes'])],
            [KeyboardButton(text=t['attach_no'])]
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
        logger.error(f"Error sending photo: {e}")
        await message.answer(
            translations[lang]['welcome'],
            reply_markup=get_menu_kb(user_id, lang)
        )

@dp.message(F.text.in_(["Записаться на консультацию", "Book Consultation"]))
async def start_consultation(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    await state.set_state(RequestForm.name)
    await message.answer(
        t['enter_name'],
        reply_markup=get_back_kb(lang)
    )

@dp.message(RequestForm.name)
async def process_name(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    if message.text in [t['back'], t['main_menu_btn']]:
        await state.clear()
        await message.answer(
            t['menu_caption'],
            reply_markup=get_menu_kb(user_id, lang)
        )
        return
    
    await state.update_data(name=message.text)
    await state.set_state(RequestForm.phone)
    await message.answer(
        t['enter_phone'],
        reply_markup=get_back_kb(lang)
    )

@dp.message(RequestForm.phone)
async def process_phone(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    if message.text in [t['back'], t['main_menu_btn']]:
        await state.clear()
        await message.answer(
            t['menu_caption'],
            reply_markup=get_menu_kb(user_id, lang)
        )
        return
    
    # Phone validation
    phone_pattern = r'^\+?[1-9]\d{1,14}$'
    if not re.match(phone_pattern, message.text.replace(' ', '').replace('-', '')):
        await message.answer(
            t['invalid_phone'],
            reply_markup=get_back_kb(lang)
        )
        return
    
    await state.update_data(phone=message.text)
    await state.set_state(RequestForm.message)
    await message.answer(
        t['describe_problem'],
        reply_markup=get_back_kb(lang)
    )

@dp.message(RequestForm.message)
async def process_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    if message.text in [t['back'], t['main_menu_btn']]:
        await state.clear()
        await message.answer(
            t['menu_caption'],
            reply_markup=get_menu_kb(user_id, lang)
        )
        return
    
    await state.update_data(message_text=message.text)
    await state.set_state(RequestForm.attach_doc_choice)
    await message.answer(
        t['attach_ask'],
        reply_markup=get_attach_kb(lang)
    )

@dp.message(RequestForm.attach_doc_choice)
async def process_attach_choice(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    if message.text in [t['back'], t['main_menu_btn']]:
        await state.clear()
        await message.answer(
            t['menu_caption'],
            reply_markup=get_menu_kb(user_id, lang)
        )
        return
    
    if message.text == t['attach_yes']:
        await state.set_state(RequestForm.attach_docs)
        await state.update_data(documents=[])
        await message.answer(
            t['attach_file'],
            reply_markup=get_back_kb(lang)
        )
    elif message.text == t['attach_no']:
        await finish_request(message, state)
    else:
        await message.answer(
            t['not_added'],
            reply_markup=get_attach_kb(lang)
        )

@dp.message(RequestForm.attach_docs)
async def process_attach_docs(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    if message.text in [t['back'], t['main_menu_btn']]:
        await state.clear()
        await message.answer(
            t['menu_caption'],
            reply_markup=get_menu_kb(user_id, lang)
        )
        return
    
    if message.document:
        data = await state.get_data()
        documents = data.get('documents', [])
        
        if len(documents) >= 3:
            await message.answer(
                t['attach_max'],
                reply_markup=get_back_kb(lang)
            )
            return
        
        documents.append({
            'file_id': message.document.file_id,
            'file_name': message.document.file_name
        })
        await state.update_data(documents=documents)
        
        await message.answer(
            t['attach_added'].format(message.document.file_name),
            reply_markup=get_back_kb(lang)
        )

@dp.message(Command("done"), StateFilter(RequestForm.attach_docs))
async def done_command(message: types.Message, state: FSMContext):
    await finish_request(message, state)

async def finish_request(message: types.Message, state: FSMContext):


@dp.message(F.text.in_(["Часто задаваемые вопросы", "FAQ"]))
async def faq(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    await message.answer(
        t['faq_not_added'],
        reply_markup=get_menu_kb(user_id, lang)
    )

@dp.message(F.text.in_(["Контакты", "Contacts"]))
async def contacts(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    async def finish_request(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]

    data = await state.get_data()

    # Save to database
    with conn:
        logger.info(f"Saving request for user {user_id}: {data}")
        cursor = conn.execute(
            """INSERT INTO requests (user_id, name, phone, message, created_at, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                data['name'],
                data['phone'],
                data['message_text'],
                datetime.now().isoformat(),
                'new'
            )
        )
        request_id = cursor.lastrowid
        logger.info(f"Request saved with ID: {request_id}")

        # Save documents if any
        documents = data.get('documents', [])
        for doc in documents:
            conn.execute(
                """INSERT INTO documents (request_id, file_id, file_name, sent_at)
                   VALUES (?, ?, ?, ?)""",
                (request_id, doc['file_id'], doc['file_name'], datetime.now().isoformat())
            )
        logger.info(f"Saved {len(documents)} documents for request {request_id}")

    # Notify admin
    if ADMIN_CHAT_ID:
        admin_text = f"""
🆕 Новая заявка #{request_id}

👤 Имя: {data['name']}
📞 Телефон: {data['phone']}
💬 Сообщение: {data['message_text']}
📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}
"""
        try:
            await bot.send_message(ADMIN_CHAT_ID, admin_text)

            # Send documents to admin
            for doc in documents:
                await bot.send_document(
                    ADMIN_CHAT_ID,
                    doc['file_id'],
                    caption=f"Документ к заявке #{request_id}: {doc['file_name']}"
                )
        except Exception as e:
            logger.error(f"Error sending to admin: {e}")

    await state.clear()
    await message.answer(
        t['thanks'],
        reply_markup=get_menu_kb(user_id, lang)
    )

@dp.message(F.text.in_(["Админ-панель", "Admin Panel"]))
async def admin_panel(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if user_id not in ADMINS:
        lang = await get_lang(state, user_id)
        t = translations[lang]
        await message.answer(
            t['forbidden'],
            reply_markup=get_menu_kb(user_id, lang)
        )
        return
    
    await message.answer(
        f"🏛️ Админ-панель: {APP_URL}/admin",
        reply_markup=get_menu_kb(user_id, 'ru')
    )

@dp.message(F.text.in_([translations['ru']['lang_ru'], translations['en']['lang_en']]))
async def set_language(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = 'ru' if message.text == translations['ru']['lang_ru'] else 'en'
    save_user_language(user_id, lang)
    await state.update_data(lang=lang)
    await message.answer(
        translations[lang]['menu_caption'],
        reply_markup=get_menu_kb(user_id, lang)
    )

# Initialize FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    logger.info("🚀 Starting LegalBot...")
    try:
        # Проверка подключения к Redis
        await storage.redis.ping()
        logger.info("✅ Redis connection successful")
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
        raise
    
    try:
        # Delete existing webhook
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("🗑 Old webhook deleted")
        
        # Set new webhook
        await bot.set_webhook(
            url=WEBHOOK_URL,
            drop_pending_updates=True,
            allowed_updates=dp.resolve_used_update_types()
        )
        logger.info(f"✅ Webhook successfully set to: {WEBHOOK_URL}")
        
        # Test webhook
        webhook_info = await bot.get_webhook_info()
        logger.info(f"📡 Webhook info: {webhook_info}")
        
    except Exception as e:
        logger.critical(f"❌ Failed to set webhook: {e}")
        raise
    
    try:
        yield
        
    finally:
        # Shutdown logic
        logger.info("🛑 Shutting down LegalBot...")
        
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("🗑 Webhook deleted")
        except Exception as e:
            logger.error(f"⚠️ Error deleting webhook: {e}")

        try:
            await bot.session.close()
            logger.info("🤖 Bot session closed")
        except Exception as e:
            logger.error(f"⚠️ Error closing bot session: {e}")

        try:
            await storage.close()
            logger.info("🗄 Redis storage closed")
        except Exception as e:
            logger.error(f"⚠️ Error closing storage: {e}")

        try:
            conn.close()
            logger.info("🔒 Database connection closed")
        except Exception as e:
            logger.error(f"⚠️ Error closing database: {e}")

app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Configure templates and static files
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Webhook configuration
WEBHOOK_PATH = "/webhook"  # Упрощаем путь для теста
WEBHOOK_URL = f"{APP_URL}{WEBHOOK_PATH}"
logger.info(f"Webhook handler registered for path: {WEBHOOK_PATH}")  # Логирование регистрации маршрута

# Admin API routes
@app.get("/admin/api/requests")
async def get_requests(request: Request):
    if not request.session.get("admin"):
        return JSONResponse({"error": "Unauthorized"}, status_code=403)

    logger.info("Fetching requests from database")
    rows = conn.execute("""
        SELECT r.*, GROUP_CONCAT(d.file_name) as documents
        FROM requests r
        LEFT JOIN documents d ON r.id = d.request_id
        GROUP BY r.id
        ORDER BY r.created_at DESC
    """).fetchall()
    logger.info(f"Found {len(rows)} rows in database")

    requests = []
    for row in rows:
        requests.append({
            'id': row['id'],
            'user_id': row['user_id'],
            'name': row['name'],
            'phone': row['phone'],
            'message': row['message'],
            'created_at': row['created_at'],
            'status': row['status'],
            'documents': row['documents'].split(',') if row['documents'] else []
        })

    logger.info(f"Returning {len(requests)} requests")
    return {"requests": requests}

@app.post("/admin/api/reply")
async def send_reply(request: Request):
    if not request.session.get("admin"):
        return JSONResponse({"error": "Unauthorized"}, status_code=403)
    
    form_data = await request.form()
    user_id = int(form_data.get("user_id"))
    message = form_data.get("message")
    
    try:
        await bot.send_message(user_id, f"📧 Ответ от юриста:\n\n{message}")
        return {"success": True}
    except Exception as e:
        logger.error(f"Error sending reply: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/admin/api/status")
async def update_status(request: Request):
    if not request.session.get("admin"):
        return JSONResponse({"error": "Unauthorized"}, status_code=403)
    
    form_data = await request.form()
    request_id = int(form_data.get("request_id"))
    status = form_data.get("status")
    
    try:
        with conn:
            conn.execute(
                "UPDATE requests SET status = ? WHERE id = ?",
                (status, request_id)
            )
        return {"success": True}
    except Exception as e:
        logger.error(f"Error updating status: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# Admin panel routes
@app.get("/admin/login")
async def admin_login_page(request: Request):
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
        return RedirectResponse("/admin", status_code=302)
    else:
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "Неверные логин или пароль"}
        )

@app.post("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=302)

@app.get("/admin")
async def admin_panel_page(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login")
    return templates.TemplateResponse("admin.html", {"request": request})

# Health check
@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

# Webhook handler
@app.post(WEBHOOK_PATH)
async def handle_webhook(update: dict):
    logger.info(f"Webhook triggered with update: {update}")
    try:
        telegram_update = types.Update(**update)
        await dp.feed_update(bot=bot, update=telegram_update)
        logger.info("Update processed successfully")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}")
        return JSONResponse({"status": "error", "details": str(e)}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("legalbot:app", host="0.0.0.0", port=port, reload=False)
