import os
import re
import logging
import sqlite3
from typing import Optional

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

from fastapi import FastAPI, Request, Form, status, Depends, Response
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import httpx

# === CONFIG ===
load_dotenv()
API_TOKEN = os.getenv("API_TOKEN")
REDIS_URL = os.getenv("REDIS_URL")
APP_URL = os.getenv("APP_URL", "https://web-production-bb98.up.railway.app")
ADMIN_LOGIN1 = os.getenv("ADMIN_LOGIN1")
ADMIN_PASSWORD1 = os.getenv("ADMIN_PASSWORD1")
ADMIN_LOGIN2 = os.getenv("ADMIN_LOGIN2")
ADMIN_PASSWORD2 = os.getenv("ADMIN_PASSWORD2")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
ADMINS = {1899643695, 1980103568}
SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")

logging.basicConfig(level=logging.INFO)

# === BOT & FASTAPI INIT ===
storage = RedisStorage.from_url(
    REDIS_URL,
    key_builder=DefaultKeyBuilder(prefix="fsm")
)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=storage)
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# === DB INIT ===
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
        request_id INTEGER,
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

# === LANG ===
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

async def get_lang(state: FSMContext, user_id: int) -> str:
    data = await state.get_data()
    lang = data.get('lang')
    if not lang:
        lang = get_user_language(user_id) or 'ru'
        await state.update_data(lang=lang)
    return lang

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

async def show_main_menu(message: types.Message, state: FSMContext):
    lang = await get_lang(state, message.from_user.id)
    await message.answer(
        translations[lang]['menu_caption'],
        reply_markup=get_menu_kb(message.from_user.id, lang)
    )

# === TELEGRAM BOT HANDLERS ===

@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    saved_lang = get_user_language(user_id)
    if not saved_lang:
        await state.set_state(RequestForm.language)
        await message.answer(
            translations['ru']['choose_language'],
            reply_markup=get_lang_kb()
        )
        return
    lang = saved_lang
    await state.update_data(lang=lang)
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

@dp.message(RequestForm.language, F.text)
async def choose_lang(message: types.Message, state: FSMContext):
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
        return
    user_id = message.from_user.id
    save_user_language(user_id, lang)
    await state.update_data(lang=lang)
    await state.clear()
    try:
        await bot.send_photo(
            chat_id=message.chat.id,
            photo="https://i.imgur.com/HDFlGu5.png",
            caption=translations[lang]['welcome'],
            reply_markup=get_menu_kb(user_id, lang)
        )
    except Exception as e:
        logging.error(f"Error sending welcome message: {e}")
        await message.answer(
            translations[lang]['welcome'],
            reply_markup=get_menu_kb(user_id, lang)
        )

@dp.message(lambda m: m.text in [
    translations['ru']['main_menu_btn'], translations['en']['main_menu_btn'],
    translations['ru']['back'], translations['en']['back']
])
async def return_main_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await show_main_menu(message, state)

@dp.message(lambda m: m.text in [translations['ru']['consult_button'], translations['en']['consult_button']])
async def consult_start(message: types.Message, state: FSMContext):
    lang = await get_lang(state, message.from_user.id)
    await state.set_state(RequestForm.name)
    await message.answer(translations[lang]['enter_name'], reply_markup=get_back_kb(lang))

@dp.message(RequestForm.name)
async def get_name(message: types.Message, state: FSMContext):
    lang = await get_lang(state, message.from_user.id)
    if message.text in [translations['ru']['back'], translations['en']['back'],
                        translations['ru']['main_menu_btn'], translations['en']['main_menu_btn']]:
        await state.clear()
        await show_main_menu(message, state)
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
        await show_main_menu(message, state)
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
        await show_main_menu(message, state)
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
        await show_main_menu(message, state)
    else:
        await message.answer(translations[lang]['not_added'])

@dp.message(RequestForm.attach_docs, lambda m: m.text and m.text.lower() == "/done")
async def done_docs(message: types.Message, state: FSMContext):
    await finish_request(message, state)

@dp.message(RequestForm.attach_docs)
async def attach_docs_handler(message: types.Message, state: FSMContext):
    lang = await get_lang(state, message.from_user.id)

    if message.text in [translations['ru']['main_menu_btn'], translations['en']['main_menu_btn']]:
        await state.clear()
        await show_main_menu(message, state)
        return

    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or 'document'

        tg_file = await bot.get_file(file_id)
        file_path = tg_file.file_path

        data = await state.get_data()
        docs = data.get('documents', [])
        if len(docs) >= 3:
            await message.answer(translations[lang]['attach_max'])
            return
        docs.append({
            'file_id': file_id,
            'file_name': file_name,
            'file_path': file_path
        })
        await state.update_data(documents=docs)
        await message.answer(
            translations[lang]['attach_added'].format(file_name)
        )


async def finish_request(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('lang') or get_user_language(message.from_user.id) or 'ru'
    from datetime import datetime
    now = datetime.now().isoformat()
    user_id = message.from_user.id
    with conn:
        c.execute(
            "INSERT INTO requests (user_id, name, phone, message, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, data['name'], data['phone'], data['message'], now, 'new')
        )
        req_id = c.lastrowid
        docs = data.get('documents', [])
        for doc in docs:
            c.execute(
                "INSERT INTO documents (request_id, file_id, file_name, sent_at) VALUES (?, ?, ?, ?)",
                (req_id, doc['file_id'], doc['file_name'], now)
            )
    admin_msg = f"Новая заявка:\nИмя: {data['name']}\nТел: {data['phone']}\nПроблема: {data['message']}"
    if docs:
        admin_msg += "\nДокументы: " + ", ".join(d['file_name'] for d in docs)
    await bot.send_message(ADMIN_CHAT_ID, admin_msg)
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

@dp.message(lambda m: m.text in [translations['ru']['contacts_button'], translations['en']['contacts_button']])
async def show_contacts(message: types.Message, state: FSMContext):
    lang = await get_lang(state, message.from_user.id)
    await message.answer(translations[lang]['contacts'], reply_markup=get_menu_kb(message.from_user.id, lang))

# === FASTAPI ADMIN PANEL ===

def is_authenticated(request: Request) -> bool:
    return request.session.get("admin") is not None

def authenticate_user(username: str, password: str) -> bool:
    return (
        (username == ADMIN_LOGIN1 and password == ADMIN_PASSWORD1) or
        (username == ADMIN_LOGIN2 and password == ADMIN_PASSWORD2)
    )

def get_requests_data(search: Optional[str]=None, status_f: Optional[str]=None):
    sql = """
        SELECT r.id, r.user_id, r.name, r.phone, r.message, r.created_at, r.status
        FROM requests r
        ORDER BY r.created_at DESC
    """
    params = []
    if search:
        sql = sql.replace("ORDER BY", "WHERE r.name LIKE ? OR r.message LIKE ? ORDER BY")
        params.extend([f'%{search}%', f'%{search}%'])
    if status_f and status_f != "":
        if "WHERE" in sql:
            sql = sql.replace("ORDER BY", "AND r.status = ? ORDER BY")
        else:
            sql = sql.replace("ORDER BY", "WHERE r.status = ? ORDER BY")
        params.append(status_f)
    c.execute(sql, params)
    reqs = []
    for row in c.fetchall():
        c.execute("SELECT file_id, file_name FROM documents WHERE request_id=?", (row[0],))
        docs = [{"file_id": d[0], "file_name": d[1]} for d in c.fetchall()]
        reqs.append({
            "id": row[0], "user_id": row[1], "name": row[2], "phone": row[3],
            "message": row[4], "created_at": row[5], "status": row[6], "documents": docs
        })
    return reqs

@app.get("/admin/login")
def admin_login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": None})

@app.post("/admin/login")
def admin_login(request: Request, username: str = Form(...), password: str = Form(...)):
    if authenticate_user(username, password):
        request.session["admin"] = username
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": "Неверный логин или пароль"})

@app.post("/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=302)

@app.get("/admin")
def admin_panel(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/admin/login", status_code=302)
    return templates.TemplateResponse("admin.html", {
        "request": request
    })

@app.get("/admin/api/requests")
def api_requests(request: Request, search: Optional[str]=None, status_f: Optional[str]=None):
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=403)
    data = get_requests_data(search, status_f)
    return {"requests": data}

@app.post("/admin/status")
async def change_status(request: Request):
    if not is_authenticated(request):
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    form = await request.form()
    req_id = int(form["id"])
    status_val = form["status"]
    c.execute("UPDATE requests SET status=? WHERE id=?", (status_val, req_id))
    conn.commit()
    return Response(status_code=204)

@app.post("/admin/reply")
async def reply_user(request: Request):
    if not is_authenticated(request):
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    form = await request.form()
    user_id = int(form["user_id"])
    msg = form["message"]
    try:
        await bot.send_message(user_id, msg)
        return Response(status_code=204)
    except Exception as e:
        logging.error(f"Send message error: {e}")
        return Response("Ошибка отправки", status_code=500)

from urllib.parse import quote

@app.get("/admin/download/{file_id}")
async def download_file(file_id: str, request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/admin/login", status_code=302)

    try:
        c.execute(
            "SELECT file_name, file_path FROM documents WHERE file_id = ?",
            (file_id,)
        )
        row = c.fetchone()

        if not row:
            return Response("Файл не найден", status_code=404)

        filename, file_path = row

        if not file_path:
            return Response("file_path отсутствует", status_code=500)

        file_url = (
            f"https://api.telegram.org/file/bot{API_TOKEN}/{file_path}"
        )

        async with httpx.AsyncClient() as client:
            r = await client.get(file_url)

            if r.status_code != 200:
                return Response("Ошибка загрузки файла", status_code=502)

            filename_utf8 = quote(filename)

            headers = {
                "Content-Disposition": (
                    f"attachment; filename*=UTF-8''{filename_utf8}"
                )
            }

            return StreamingResponse(
                r.aiter_bytes(),
                headers=headers
            )

except Exception as e:
    import traceback
    logging.error("Download error:", exc_info=True)
    return Response("Ошибка скачивания", status_code=500)



# === WEBHOOK for Telegram (если нужно) ===
WEBHOOK_PATH = f"/webhook/{API_TOKEN}"
WEBHOOK_URL = APP_URL + WEBHOOK_PATH

@app.post(WEBHOOK_PATH)
async def bot_webhook(update: dict):
    try:
        telegram_update = types.Update(**update)
        await dp.feed_update(bot=bot, update=telegram_update)
        return {"ok": True}
    except Exception as e:
        logging.error(f"Webhook error: {str(e)}", exc_info=True)
        return {"ok": False, "error": str(e)}

@app.on_event("startup")
async def on_startup():
    try:
        # подключение Redis и установка вебхука
        redis = storage.redis
        await redis.ping()
        await bot.delete_webhook()
        await bot.set_webhook(WEBHOOK_URL)

        # === ВРЕМЕННО добавляем колонку file_path в таблицу documents ===
        try:
            conn.execute("ALTER TABLE documents ADD COLUMN file_path TEXT")
            conn.commit()
            print("✅ Добавлена колонка file_path в таблицу documents")
        except Exception as e:
            if "duplicate column name" in str(e):
                print("ℹ️ Колонка file_path уже существует, пропускаем")
            else:
                print("❌ Ошибка при добавлении колонки:", e)

    except Exception as e:
        logging.error(f"Startup error: {e}")
        raise

@app.on_event("shutdown")
async def on_shutdown():
    try:
        await bot.session.close()
        await storage.close()
    except Exception as e:
        logging.error(f"Shutdown error: {e}")
        raise

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
