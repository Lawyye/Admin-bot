import logging
import os
import asyncio
from datetime import datetime, timezone
import aiosqlite
from contextlib import asynccontextmanager
from urllib.parse import urljoin
from typing import List, Optional

from aiogram import Router
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.client.default import DefaultBotProperties
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as redis
from fastapi.responses import StreamingResponse
from io import BytesIO
import uvicorn

# ===== НАСТРОЙКА ЛОГИРОВАНИЯ =====
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

# Логирование версий библиотек
import aiogram
import fastapi
logger.info(f"aiogram version: {aiogram.__version__}")
logger.info(f"fastapi version: {fastapi.__version__}")

# ===== КОНСТАНТЫ =====
MAX_DOCUMENT_SIZE = 20 * 1024 * 1024  # 20 MB
ALLOWED_DOCUMENT_TYPES = {
    'application/pdf',
    'image/jpeg',
    'image/png',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
}

# ===== ИНИЦИАЛИЗАЦИЯ БОТА =====
API_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')
ALLOWED_ORIGINS = [origin for origin in os.getenv('ALLOWED_ORIGINS', '*').split(',') if origin]

if not API_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в .env")

bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ===== БАЗА ДАННЫХ =====
async def init_db():
    async with aiosqlite.connect('bot.db') as db:
        await db.execute("""
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER,
                file_id TEXT,
                file_name TEXT,
                file_type TEXT,
                file_size INTEGER,
                sent_at TEXT,
                FOREIGN KEY (request_id) REFERENCES requests(id)
            )
        """)
        await db.commit()

# ===== ПЕРЕВОДЫ =====
translations = {
    'ru': {
        'start': '👋 Привет! Я LegalBot. Выберите язык:\n🇷🇺 Русский\n🇬🇧 English',
        'canceled': '❌ Запрос отменен',
        'thanks': '✅ Спасибо! Ваша заявка принята',
        'error_missing_data': '⚠️ Заполните все поля',
        'contacts': '📞 Контакты: +123456789',
        'menu': 'Главное меню',
        'doc_type_error': '⚠️ Неподдерживаемый тип файла',
        'doc_size_error': '⚠️ Файл слишком большой (максимум 20 МБ)',
        'back': '◀️ Назад',
        'faq': '❓ FAQ',
        'admin_panel': '👤 Админ-панель',
        'consultation': '📝 Записаться на консультацию',
        'change_language': '🌐 Сменить язык'
    },
    'en': {
        'start': '👋 Hello! I am LegalBot. Choose language:\n🇬🇧 English\n🇷🇺 Русский',
        'canceled': '❌ Request canceled',
        'thanks': '✅ Thank you! Request accepted',
        'error_missing_data': '⚠️ Please fill all fields',
        'contacts': '📞 Contacts: +88005553535',
        'menu': 'Main menu',
        'doc_type_error': '⚠️ Unsupported file type',
        'doc_size_error': '⚠️ File too large (max 20 MB)',
        'back': '◀️ Back',
        'faq': '❓ FAQ',
        'admin_panel': '👤 Admin Panel',
        'consultation': '📝 Book Consultation',
        'change_language': '🌐 Change Language'
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
            [KeyboardButton(text=t['consultation'])],
            [KeyboardButton(text=t['change_language']), KeyboardButton(text=t['faq'])],
            [KeyboardButton(text=t['contacts']), KeyboardButton(text=t['admin_panel'])],
            [KeyboardButton(text=t['back'])]
        ],
        resize_keyboard=True
    )

# ===== ОБРАБОТЧИКИ СООБЩЕНИЙ =====
@dp.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await state.update_data(lang='ru')
    await message.answer(translations['ru']['start'], reply_markup=get_menu('ru'))

@dp.message(F.text.endswith('Назад') | F.text.endswith('Back'))
async def back_handler(message: types.Message, state: FSMContext):
    lang = await get_lang(state)
    current_state = await state.get_state()
    
    if current_state is None:
        await message.answer(
            translations[lang]['menu'],
            reply_markup=get_menu(lang)
        )
    else:
        await state.clear()
        await message.answer(
            translations[lang]['menu'],
            reply_markup=get_menu(lang)
        )

@dp.message(F.text.endswith('Сменить язык') | F.text.endswith('Change Language'))
async def change_language_handler(message: types.Message, state: FSMContext):
    await message.answer(
        '🌐 Выберите язык / Choose language:\n🇷🇺 Русский\n🇬🇧 English',
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🇷🇺 Русский"), KeyboardButton(text="🇬🇧 English")],
                [KeyboardButton(text="◀️ Назад")]
            ],
            resize_keyboard=True
        )
    )

@dp.message(F.text.startswith('🇷🇺') | F.text.startswith('🇬🇧'))
async def lang_handler(message: types.Message, state: FSMContext):
    lang = 'ru' if message.text.startswith('🇷🇺') else 'en'
    await state.update_data(lang=lang)
    await message.answer(translations[lang]['menu'], reply_markup=get_menu(lang))

@dp.message(F.text.endswith('FAQ'))
async def faq_handler(message: types.Message, state: FSMContext):
    lang = await get_lang(state)
    await message.answer(
        "FAQ содержание...",  # Здесь добавьте ваш FAQ текст
        reply_markup=get_menu(lang)
    )

@dp.message(F.text.endswith('Админ-панель') | F.text.endswith('Admin Panel'))
async def admin_panel_handler(message: types.Message, state: FSMContext):
    lang = await get_lang(state)
    admin_url = os.getenv('ADMIN_PANEL_URL', 'https://web-production-bb98.up.railway.app/admin')
    
    await message.answer(
        f"🔐 {translations[lang]['admin_panel']}\n\n{admin_url}",
        reply_markup=get_menu(lang)
    )

@dp.message(Command("cancel"))
async def cancel_handler(message: types.Message, state: FSMContext):
    lang = await get_lang(state)
    await state.clear()
    await message.answer(translations[lang]['canceled'], reply_markup=get_menu(lang))

@dp.message(F.text.endswith('консультацию') | F.text.endswith('Consultation'))
async def request_handler(message: types.Message, state: FSMContext):
    await state.set_state(RequestForm.waiting_for_name)
    await message.answer("Введите ваше имя:", reply_markup=ReplyKeyboardRemove())

@dp.message(RequestForm.waiting_for_name)
async def name_handler(message: types.Message, state: FSMContext):
    if not message.text or len(message.text) < 2:
        lang = await get_lang(state)
        await message.answer(translations[lang]['error_missing_data'])
        return
    await state.update_data(name=message.text)
    await state.set_state(RequestForm.waiting_for_phone)
    await message.answer("Введите ваш телефон:")

@dp.message(RequestForm.waiting_for_phone)
async def phone_handler(message: types.Message, state: FSMContext):
    if not message.text or len(message.text) < 5:
        lang = await get_lang(state)
        await message.answer(translations[lang]['error_missing_data'])
        return
    await state.update_data(phone=message.text)
    await state.set_state(RequestForm.waiting_for_message)
    await message.answer("Опишите вашу проблему:")

@dp.message(RequestForm.waiting_for_message)
async def message_handler(message: types.Message, state: FSMContext):
    if not message.text or len(message.text) < 10:
        lang = await get_lang(state)
        await message.answer(translations[lang]['error_missing_data'])
        return
    await state.update_data(message_text=message.text)
    await state.set_state(RequestForm.attach_docs)
    await message.answer("Прикрепите документы (если есть) и нажмите /done")

@router.message(StateFilter(RequestForm.attach_docs), F.document)
async def doc_handler(message: types.Message, state: FSMContext):
    lang = await get_lang(state)

    logger.info(f"[📎 ДОКУМЕНТ ПОЛУЧЕН] file_id: {message.document.file_id}")
    logger.info(f"Название: {message.document.file_name}")
    logger.info(f"Тип: {message.document.mime_type}")
    logger.info(f"Размер: {message.document.file_size}")

    if message.document.mime_type not in ALLOWED_DOCUMENT_TYPES:
        await message.answer(translations[lang]['doc_type_error'])
        return

    if message.document.file_size > MAX_DOCUMENT_SIZE:
        await message.answer(translations[lang]['doc_size_error'])
        return

    data = await state.get_data()
    docs = data.get('docs', [])
    docs.append({
        'file_id': message.document.file_id,
        'file_name': message.document.file_name,
        'file_type': message.document.mime_type,
        'file_size': message.document.file_size
    })
    await state.update_data(docs=docs)
    await message.answer("Документ добавлен!")

@dp.message(Command("done"), RequestForm.attach_docs)
async def finish_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = await get_lang(state)
    
    if not all(k in data for k in ['name', 'phone', 'message_text']):
        await message.answer(translations[lang]['error_missing_data'])
        return
        
    async with aiosqlite.connect('bot.db') as db:
        cursor = await db.execute(
            """INSERT INTO requests 
            (user_id, name, phone, message, created_at) 
            VALUES (?, ?, ?, ?, ?)""",
            (message.from_user.id, data['name'], data['phone'], data['message_text'], 
             datetime.now(timezone.utc).isoformat())
        )
        request_id = cursor.lastrowid
        
        for doc in data.get('docs', []):
            await db.execute(
                """INSERT INTO documents 
                (request_id, file_id, file_name, file_type, file_size, sent_at) 
                VALUES (?, ?, ?, ?, ?, ?)""",
                (request_id, doc['file_id'], doc['file_name'], doc['file_type'],
                 doc['file_size'], datetime.now(timezone.utc).isoformat())
            )
        await db.commit()
    
    await message.answer(translations[lang]['thanks'], reply_markup=get_menu(lang))
    await state.clear()

# ===== FASTAPI НАСТРОЙКА =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
        
        webhook_path = '/webhook'
        webhook_url = urljoin(
            os.getenv('WEBHOOK_HOST', 'https://web-production-bb98.up.railway.app'),
            webhook_path
        )
        
        current_webhook = await bot.get_webhook_info()
        logger.info(f"Current webhook info: {current_webhook}")
        
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Old webhook deleted")
        
        webhook_info = await bot.set_webhook(
            url=webhook_url,
            allowed_updates=['message', 'callback_query', 'inline_query'],
            drop_pending_updates=True
        )
        
        logger.info(f"New webhook set: {webhook_url}")
        logger.info(f"Webhook setup result: {webhook_info}")
        
        yield
        
        await bot.delete_webhook()
        logger.info("Webhook deleted on shutdown")
    except Exception as e:
        logger.error(f"Lifespan error: {e}")
        raise

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ===== CORS =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if ALLOWED_ORIGINS else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== MIDDLEWARE =====
app.add_middleware(SessionMiddleware, secret_key=os.getenv('SESSION_SECRET', 'secret'))

# ===== ROUTES =====
@app.get("/")
async def root():
    return RedirectResponse("/admin/login", status_code=302)

@app.get("/admin/login")
async def admin_login(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})

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

    async with aiosqlite.connect("bot.db") as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM requests ORDER BY created_at DESC")
        requests = await cursor.fetchall()
        enriched = []
        for row in requests:
            cur_docs = await db.execute("SELECT * FROM documents WHERE request_id = ?", (row["id"],))
            documents = await cur_docs.fetchall()
            enriched.append({**dict(row), "documents": [dict(d) for d in documents]})

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "requests": enriched,
        "bot_token": os.getenv("BOT_TOKEN")
    })

@app.post("/admin/update")
async def update_request(
    request: Request,
    request_id: int = Form(...),
    status: str = Form(...),
    reply: str = Form("")
):
    if not request.session.get("auth"):
        return RedirectResponse("/admin/login", status_code=302)

    try:
        async with aiosqlite.connect("bot.db") as db:
            db.row_factory = aiosqlite.Row  # ← добавь это!
            await db.execute(
                "UPDATE requests SET status = ? WHERE id = ?",
                (status, request_id)
            )
            await db.commit()

            if reply:
                cursor = await db.execute("SELECT user_id FROM requests WHERE id = ?", (request_id,))
                row = await cursor.fetchone()

                if row and row["user_id"]:
                    try:
                        await bot.send_message(
                            row["user_id"],
                            f"📩 Ответ администратора:\n\n{reply}"
                        )
                    except Exception as send_err:
                        logger.error(f"Ошибка при отправке сообщения: {send_err}")
                else:
                    logger.warning(f"⚠️ Не найден user_id для заявки {request_id}")

        return RedirectResponse("/admin", status_code=303)

    except Exception as e:
        logger.error(f"❌ Ошибка при обновлении заявки: {e}")
        return RedirectResponse("/admin", status_code=500)
        
@app.post("/webhook")
async def webhook_handler(request: Request):
    try:
        update_data = await request.json()
        logger.info(f"Received update data: {update_data}")
        
        try:
            update = types.Update.model_validate(update_data)
        except Exception as e:
            logger.error(f"Error creating Update object: {e}")
            update = types.Update(**update_data)
        
        logger.info(f"Created update object: {type(update)}")
        
        await dp.feed_update(bot, update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "ok": False, 
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            }
        )

@app.get("/webhook")
async def webhook_get():
    return JSONResponse(
        status_code=405,
        content={
            "ok": False,
            "error": "Method Not Allowed",
            "detail": "This webhook endpoint only accepts POST requests from Telegram servers.",
            "documentation": "https://core.telegram.org/bots/api#setwebhook",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        }
    )

@app.get("/health")
async def health_check():
    try:
        bot_info = await bot.get_me()
        webhook_info = await bot.get_webhook_info()
        return {
            "status": "ok",
            "bot": {
                "id": bot_info.id,
                "username": bot_info.username,
                "webhook_url": webhook_info.url,
                "pending_updates": webhook_info.pending_update_count
            },
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            }
        )
@app.get("/download/{file_id}")
async def download_file(file_id: str):
    try:
        file = await bot.get_file(file_id)
        file_path = file.file_path
        file_url = f"https://api.telegram.org/file/bot{API_TOKEN}/{file_path}"

        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=resp.status, detail="Не удалось загрузить файл")
                filename = file_path.split("/")[-1]
                return StreamingResponse(resp.content, media_type="application/octet-stream", headers={
                    "Content-Disposition": f"attachment; filename={filename}"
                })
    except Exception as e:
        logger.error(f"Ошибка при скачивании файла: {e}")
           raise 
        HTTPException(status_code=500, 
        detail=str(e))
        

if __name__ == "__main__":
    asyncio.run(init_db())
    uvicorn.run(
        "legalbot:app",
        host="0.0.0.0",
        port=8080,
        reload=True
    )
