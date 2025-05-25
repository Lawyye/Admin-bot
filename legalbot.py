import asyncio
import logging
import sqlite3
import os
import re

from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

API_TOKEN = os.getenv("API_TOKEN")
ADMIN_CHAT_ID_ENV = os.getenv("ADMIN_CHAT_ID")
if not ADMIN_CHAT_ID_ENV:
    raise ValueError("ADMIN_CHAT_ID is not set")
ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_ENV)
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "secure-token-123")

ADMIN_LOGIN1 = os.getenv("ADMIN_LOGIN1")
ADMIN_PASSWORD1 = os.getenv("ADMIN_PASSWORD1")
ADMIN_LOGIN2 = os.getenv("ADMIN_LOGIN2")
ADMIN_PASSWORD2 = os.getenv("ADMIN_PASSWORD2")

ADMINS = {1899643695, 1980103568}

bot = Bot(token=API_TOKEN)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
storage = RedisStorage.from_url(REDIS_URL, key_builder=DefaultKeyBuilder(prefix="fsm"))
dp = Dispatcher(storage=storage)
logging.basicConfig(level=logging.INFO)

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
    """Сохраняем язык пользователя в базу данных"""
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_languages (user_id, language) VALUES (?, ?)",
            (user_id, lang)
        )

def get_user_language(user_id: int) -> str:
    """Получаем язык пользователя из базы данных"""
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
    """Получаем язык из состояния или из базы данных"""
    data = await state.get_data()
    lang = data.get('lang')
    if not lang and user_id:
        lang = get_user_language(user_id)
    return lang or 'ru'

# ---- ДОБАВЛЕН ЛОГ: состояние после установки ----
@dp.message(CommandStart()) 
async def start(message: types.Message, state: FSMContext): 
    user_id = message.from_user.id
    saved_lang = get_user_language(user_id)
    if not saved_lang:
        await state.set_state(RequestForm.language)
        current_state = await state.get_state()
        logging.info(f"STATE SET AFTER START: {current_state}")  # ЛОГ ДОБАВЛЕН
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

# ---- ДОБАВЛЕН ПОДРОБНЫЙ ЛОГ В ОБРАБОТЧИК ВЫБОРА ЯЗЫКА ----
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
    logging.info("Язык пользователя сохранён.")
    await state.clear()
    logging.info("Состояние FSM очищено.")

    try:
        await bot.send_photo(
            chat_id=message.chat.id,
            photo="AgACAgIAAxkBAAE1YB1oMkDR4lZwFBBjnUnPc4tHstWRRwAC4esxG9dOmUnr1RkgaeZ_hQEAAwIAA3kAAzYE",
            caption=translations[lang]['welcome'],
            reply_markup=get_menu_kb(user_id, lang)
        )
        logging.info("Фото с приветствием отправлено успешно.")
    except Exception as e:
        logging.error(f"Ошибка при отправке фото: {e}")
        await message.answer("Ошибка при отправке приветствия. Пожалуйста, напишите /start ещё раз.")

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
    if message.text in [translations['ru']['back'], translations['en']['back']]:
        await state.clear()
        await start(message, state)
        return
    if message.text in [translations['ru']['main_menu_btn'], translations['en']['main_menu_btn']]:
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
    # Валидация телефона
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
    admin_url = "https://web-production-bb98.up.railway.app/admin"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Перейти в админку", url=admin_url)]
    ])
    await message.answer("Откройте админ-панель:", reply_markup=kb)

@dp.message(lambda m: m.text in [translations['ru']['faq_button'], translations['en']['faq_button']])
async def show_faq(message: types.Message, state: FSMContext):
    lang = await get_lang(state, message.from_user.id)
    await message.answer(translations[lang]['faq_not_added'], reply_markup=get_menu_kb(message.from_user.id, lang))

# --- FastAPI part ---

app = FastAPI()

class ReplyRequest(BaseModel):
    user_id: int
    message: str

class StatusRequest(BaseModel):
    user_id: int
    status: str

def check_admin_credentials(login: str, password: str) -> bool:
    return (login == ADMIN_LOGIN1 and password == ADMIN_PASSWORD1) or \
           (login == ADMIN_LOGIN2 and password == ADMIN_PASSWORD2)

def authorize(request: Request, token: str = None):
    if not token or token != ADMIN_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

@app.post("/api/login")
async def api_login(form: dict):
    login = form.get("login")
    password = form.get("password")
    if check_admin_credentials(login, password):
        return JSONResponse({"status": "ok", "token": ADMIN_TOKEN})
    return JSONResponse({"status": "fail"}, status_code=401)

@app.get("/")
async def root():
    return {"status": "ok"}

@app.get("/api/requests")
async def get_requests(request: Request):
    token = request.headers.get("X-Admin-Token")
    authorize(request, token)
    rows = conn.execute(
        "SELECT id, user_id, name, phone, message, created_at, status FROM requests ORDER BY created_at DESC"
    ).fetchall()
    result = []
    for r in rows:
        docs = conn.execute(
            "SELECT file_id, file_name, sent_at FROM documents WHERE user_id = ?", (r[1],)
        ).fetchall()
        doc_list = [
            {"file_id": d[0], "file_name": d[1], "sent_at": d[2]}
            for d in docs
        ]
        result.append({
            "id": r[0],
            "user_id": r[1],
            "name": r[2],
            "phone": r[3],
            "message": r[4],
            "created_at": r[5],
            "status": r[6],
            "documents": doc_list
        })
    return result

# --- Webhook configuration ---
WEBHOOK_PATH = f"/webhook/{API_TOKEN}"
WEBHOOK_URL = f"https://web-production-bb98.up.railway.app{WEBHOOK_PATH}"

@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)
    print(f"Webhook set: {WEBHOOK_URL}")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()
    await bot.session.close()

from aiogram.types import Update

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}

# ---- ДОБАВЛЕН ЭХО-ХЭНДЛЕР В КОНЕЦ ФАЙЛА ----
@dp.message()
async def echo_all(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    logging.info(f"ECHO: {message.text}, STATE: {current_state}")
    await message.answer(f"ECHO: {message.text}, STATE: {current_state}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
