import logging
import os
from datetime import datetime, timezone
import sqlite3
from contextlib import asynccontextmanager
from urllib.parse import urljoin

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as redis
import uvicorn

# ===== НАСТРОЙКА ЛОГИРОВАНИЯ =====
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

# ===== ИНИЦИАЛИЗАЦИЯ БОТА =====
API_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')

if not API_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в .env")

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ===== БАЗА ДАННЫХ =====
conn = sqlite3.connect('bot.db', check_same_thread=False)
conn.row_factory = sqlite3.Row

with conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            phone TEXT,
            message TEXT,
            created_at TEXT,
            status TEXT DEFAULT 'new'
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER,
            file_id TEXT,
            file_name TEXT,
            sent_at TEXT,
            FOREIGN KEY (request_id) REFERENCES requests(id)
        )""")

# ===== ПЕРЕВОДЫ =====
translations = {
    'ru': {
        'start': '👋 Привет! Я LegalBot. Выберите язык:\n🇷🇺 Русский\n🇬🇧 English',
        'canceled': '❌ Запрос отменен',
        'thanks': '✅ Спасибо! Ваша заявка принята',
        'error_missing_data': '⚠️ Заполните все поля',
        'contacts': '📞 Контакты: +123456789',
        'menu': 'Главное меню'
    },
    'en': {
        'start': '👋 Hello! I am LegalBot. Choose language:\n🇬🇧 English\n🇷🇺 Русский',
        'canceled': '❌ Request canceled',
        'thanks': '✅ Thank you! Request accepted',
        'error_missing_data': '⚠️ Please fill all fields',
        'contacts': '📞 Contacts: +123456789',
        'menu': 'Main menu'
    }
}

# ===== СОСТОЯНИЯ =====
class RequestForm(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_message = State()
    attach_docs = State()

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
async def get_lang(state: FSMContext) -> str:
    data = await state.get_data()
    return data.get('lang', 'ru')

def get_menu(lang: str) -> ReplyKeyboardMarkup:
    t = translations[lang]
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("Записаться на консультацию")],
            [KeyboardButton(t['contacts']), KeyboardButton("Админ-панель")]
        ],
        resize_keyboard=True
    )

# ===== ОБРАБОТЧИКИ СООБЩЕНИЙ =====
@dp.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext):
    await state.update_data(lang='ru')
    await message.answer(
        translations['ru']['start'],
        reply_markup=get_menu('ru')
    )

@dp.message(F.text.in_(["🇷🇺 Русский", "🇬🇧 English"]))
async def lang_handler(message: types.Message, state: FSMContext):
    lang = 'ru' if message.text == "🇷🇺 Русский" else 'en'
    await state.update_data(lang=lang)
    t = translations[lang]
    await message.answer(t['menu'], reply_markup=get_menu(lang))

@dp.message(F.text == "Записаться на консультацию")
async def request_handler(message: types.Message, state: FSMContext):
    await state.set_state(RequestForm.waiting_for_name)
    await message.answer("Введите ваше имя:")

@dp.message(RequestForm.waiting_for_name)
async def name_handler(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(RequestForm.waiting_for_phone)
    await message.answer("Введите ваш телефон:")

@dp.message(RequestForm.waiting_for_phone)
async def phone_handler(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await state.set_state(RequestForm.waiting_for_message)
    await message.answer("Опишите вашу проблему:")

@dp.message(RequestForm.waiting_for_message)
async def message_handler(message: types.Message, state: FSMContext):
    await state.update_data(message_text=message.text)
    await state.set_state(RequestForm.attach_docs)
    await message.answer("Прикрепите документы (если есть) и нажмите /done")

@dp.message(F.document, RequestForm.attach_docs)
async def doc_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    docs = data.get('docs', [])
    docs.append({
        'file_id': message.document.file_id,
        'file_name': message.document.file_name
    })
    await state.update_data(docs=docs)
    await message.answer("Документ добавлен!")

@dp.message(Command("done"), RequestForm.attach_docs)
async def finish_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = await get_lang(state)
    
    # Сохранение в БД
    with conn:
        cursor = conn.execute(
            """INSERT INTO requests 
            (user_id, name, phone, message, created_at) 
            VALUES (?, ?, ?, ?, ?)""",
            (message.from_user.id, 
             data['name'], 
             data['phone'], 
             data['message_text'],
             datetime.now(timezone.utc).isoformat())
        )
        request_id = cursor.lastrowid
        
        for doc in data.get('docs', []):
            conn.execute(
                """INSERT INTO documents 
                (request_id, file_id, file_name, sent_at) 
                VALUES (?, ?, ?, ?)""",
                (request_id, doc['file_id'], doc['file_name'], 
                 datetime.now(timezone.utc).isoformat())
            )
    
    await message.answer(translations[lang]['thanks'])
    await state.clear()

# ===== FASTAPI НАСТРОЙКА =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.delete_webhook()
    WEBHOOK_URL = urljoin(
        os.getenv('WEBHOOK_HOST', 'https://web-production-bb98.up.railway.app'), 
        '/webhook'
    )
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook установлен: {WEBHOOK_URL}")
    yield
    await bot.delete_webhook()

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ===== CORS =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== ВЕБХУК =====
@app.post("/webhook")
async def webhook_handler(request: Request):
    try:
        update = types.Update(**await request.json())
        await dp.feed_update(bot, update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Ошибка: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(e)}
        )

# ===== АДМИН-ПАНЕЛЬ =====
app.add_middleware(SessionMiddleware, secret_key=os.getenv('SESSION_SECRET', 'secret'))

@app.get("/admin/login")
async def admin_login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/admin/login")
async def admin_auth(
    username: str = Form(...),
    password: str = Form(...),
    request: Request = None
):
    valid_users = {
        os.getenv('ADMIN_USER1', 'nurbol'): os.getenv('ADMIN_PASS1', 'marzhan2508'),
        os.getenv('ADMIN_USER2', 'vlad'): os.getenv('ADMIN_PASS2', 'archiboss20052024')
    }
    if username in valid_users and password == valid_users[username]:
        request.session["auth"] = True
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse(
        "admin_login.html", 
        {"request": request, "error": "Неверные данные"},
        status_code=401
    )

@app.get("/admin")
async def admin_panel(request: Request):
    if not request.session.get("auth"):
        return RedirectResponse("/admin/login")
    return templates.TemplateResponse("admin.html", {"request": request})

# ===== ЗАПУСК =====
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
