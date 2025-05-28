import logging
import os
from datetime import datetime, timezone
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.filters.text import Text
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.webhook import start_webhook
import redis.asyncio as redis
from fastapi import FastAPI, Request, Form, HTTPException, status
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
import itsdangerous

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройка бота
API_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN')
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST', 'https://web-production-bb98.up.railway.app')
WEBHOOK_PATH = '/webhook'
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')  # Установите в переменных окружения

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot=bot, storage=storage)
app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Настройка Redis
redis_client = redis.Redis(host='redis', port=6379, db=0)

# Middleware для сессий
app.add_middleware(SessionMiddleware, secret_key=os.getenv('SESSION_SECRET_KEY', 'your-secret-key'))

# База данных
conn = sqlite3.connect('bot.db', check_same_thread=False)
conn.row_factory = sqlite3.Row

# Создание таблиц
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
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER,
            file_id TEXT,
            file_name TEXT,
            sent_at TEXT,
            FOREIGN KEY (request_id) REFERENCES requests (id)
        )
    """)

# Переводы
translations = {
    'ru': {
        'start': '👋 Привет! Я LegalBot, ваш юридический помощник. Выберите язык / Choose language:\n🇷🇺 Русский\n🇬🇧 English',
        'select_lang': 'Выберите язык / Choose language',
        'canceled': '❌ Запрос отменен. Вы вернулись в главное меню.',
        'thanks': '✅ Спасибо! Ваша заявка принята. Мы свяжемся с вами в ближайшее время.',
        'error_missing_data': 'Ошибка: не все данные заполнены. Пожалуйста, начните заново.',
        'faq_not_added': '⚠️ Функция "Часто задаваемые вопросы" пока не добавлена. Скоро будет доступна!',
        'contacts': '📞 Наши контакты:\nТелефон: +123456789\nEmail: support@legalbot.com'
    },
    'en': {
        'start': '👋 Hello! I am LegalBot, your legal assistant. Choose language / Выберите язык:\n🇬🇧 English\n🇷🇺 Русский',
        'select_lang': 'Choose language / Выберите язык',
        'canceled': '❌ Request canceled. You are back to the main menu.',
        'thanks': '✅ Thank you! Your request has been accepted. We will contact you soon.',
        'error_missing_data': 'Error: not all data is filled. Please start over.',
        'faq_not_added': '⚠️ The "Frequently Asked Questions" feature is not yet added. Coming soon!',
        'contacts': '📞 Our contacts:\nPhone: +123456789\nEmail: support@legalbot.com'
    }
}

# Состояния
class RequestForm(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_message = State()
    attach_docs = State()

# Получение языка
async def get_lang(state: FSMContext, user_id: int) -> str:
    data = await state.get_data()
    if 'lang' not in data:
        lang = 'ru'  # Значение по умолчанию
        await state.update_data(lang=lang)
    else:
        lang = data['lang']
    return lang

# Клавиатуры
def get_menu_kb(user_id: int, lang: str) -> ReplyKeyboardMarkup:
    t = translations[lang]
    keyboard = [
        [KeyboardButton(t['faq_not_added']), KeyboardButton("Контакты")],
        [KeyboardButton("Записаться на консультацию"), KeyboardButton("Админ-панель")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# Обработчики бота
@dp.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = 'ru'  # Значение по умолчанию
    await state.update_data(lang=lang)
    t = translations[lang]
    await message.answer(
        t['start'],
        reply_markup=get_menu_kb(user_id, lang)
    )

@dp.message(Text(equals=["🇷🇺 Русский", "🇬🇧 English"], ignore_case=True))
async def set_lang(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = 'ru' if message.text == "🇷🇺 Русский" else 'en'
    await state.update_data(lang=lang)
    t = translations[lang]
    await message.answer(
        t['select_lang'],
        reply_markup=get_menu_kb(user_id, lang)
    )

@dp.message(Text(equals="Записаться на консультацию", ignore_case=True))
async def start_request(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    await state.set_state(RequestForm.waiting_for_name)
    await message.answer(
        "Введите ваше имя / Enter your name",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton("⬅️ Назад")]], resize_keyboard=True)
    )

@dp.message(RequestForm.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    await state.update_data(name=message.text)
    await state.set_state(RequestForm.waiting_for_phone)
    await message.answer(
        "Введите ваш телефон / Enter your phone",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton("⬅️ Назад")]], resize_keyboard=True)
    )

@dp.message(RequestForm.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    await state.update_data(phone=message.text)
    await state.set_state(RequestForm.waiting_for_message)
    await message.answer(
        "Введите сообщение / Enter your message",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton("⬅️ Назад")]], resize_keyboard=True)
    )

@dp.message(RequestForm.waiting_for_message)
async def process_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    await state.update_data(message_text=message.text)
    await state.set_state(RequestForm.attach_docs)
    await message.answer(
        "Прикрепите документы (если есть) и нажмите /done для завершения / Attach documents (if any) and press /done to finish",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton("⬅️ Назад"), KeyboardButton("/done")]], resize_keyboard=True)
    )

@dp.message(RequestForm.attach_docs, content_types=types.ContentType.DOCUMENT)
async def process_document(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    document = {
        'file_id': message.document.file_id,
        'file_name': message.document.file_name
    }
    data = await state.get_data()
    documents = data.get('documents', [])
    documents.append(document)
    await state.update_data(documents=documents)
    await message.answer(
        "Документ добавлен. Прикрепите еще (если нужно) или нажмите /done для завершения / Document added. Attach more (if needed) or press /done to finish",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton("⬅️ Назад"), KeyboardButton("/done")]], resize_keyboard=True)
    )

@dp.message(Command("done"), RequestForm.attach_docs)
async def done_command(message: types.Message, state: FSMContext):
    logger.info(f"Processing /done command for user {message.from_user.id}")
    await finish_request(message, state)

@dp.message(Text(equals="⬅️ Назад", ignore_case=True), RequestForm)
async def cancel_request(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    await state.clear()
    await message.answer(
        t['canceled'],
        reply_markup=get_menu_kb(user_id, lang)
    )

async def finish_request(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    data = await state.get_data()
    
    # Проверка наличия всех необходимых данных
    required_fields = ['name', 'phone', 'message_text']
    if not all(key in data for key in required_fields):
        await message.answer(
            t.get('error_missing_data', "Ошибка: не все данные заполнены. Пожалуйста, начните заново."),
            reply_markup=get_menu_kb(user_id, lang)
        )
        await state.clear()
        return
    
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
                datetime.now(timezone.utc).isoformat(),
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
                (request_id, doc['file_id'], doc['file_name'], datetime.now(timezone.utc).isoformat())
            )
        logger.info(f"Saved {len(documents)} documents for request {request_id}")

    # Notify admin
    if ADMIN_CHAT_ID:
        admin_text = f"""
🆕 Новая заявка #{request_id}

👤 Имя: {data['name']}
📞 Телефон: {data['phone']}
💬 Сообщение: {data['message_text']}
📅 Дата: {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} (UTC)
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

@dp.message(Text(equals=["Часто задаваемые вопросы", "FAQ"], ignore_case=True))
async def faq(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    await message.answer(
        t['faq_not_added'],
        reply_markup=get_menu_kb(user_id, lang)
    )

@dp.message(Text(equals="Контакты", ignore_case=True))
async def contacts(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_lang(state, user_id)
    t = translations[lang]
    
    contacts_text = t.get('contacts', "📞 Наши контакты:\nТелефон: +123456789\nEmail: support@legalbot.com")
    await message.answer(
        contacts_text,
        reply_markup=get_menu_kb(user_id, lang)
    )

# Админ-панель
@app.get("/admin/login")
async def admin_login(request: Request):
    if request.session.get("admin"):
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse("admin_login.html", {"request": request})

@app.post("/admin/login")
async def admin_login_post(
    username: str = Form(...),
    password: str = Form(...),
    request: Request = None
):
    if username == os.getenv('ADMIN_USERNAME', 'admin') and password == os.getenv('ADMIN_PASSWORD', 'password'):
        request.session["admin"] = True
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": "Неверные учетные данные"})

@app.get("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=302)

@app.get("/admin")
async def admin(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login", status_code=302)
    return templates.TemplateResponse("admin.html", {"request": request})

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

# Webhook
async def on_startup(_):
    await bot.set_webhook(WEBHOOK_URL)

async def on_shutdown(_):
    await bot.delete_webhook()

if __name__ == '__main__':
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True,
        host='0.0.0.0',
        port=8080,
)
