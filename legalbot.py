import asyncio
import logging
import sqlite3
import os
import re

from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn

API_TOKEN = os.getenv("API_TOKEN")
ADMIN_CHAT_ID_ENV = os.getenv("ADMIN_CHAT_ID")
if not ADMIN_CHAT_ID_ENV:
    raise ValueError("ADMIN_CHAT_ID is not set")
ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_ENV)
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "secure-token-123")

# Логины и пароли админов из .env
ADMIN_LOGIN1 = os.getenv("ADMIN_LOGIN1")
ADMIN_PASSWORD1 = os.getenv("ADMIN_PASSWORD1")
ADMIN_LOGIN2 = os.getenv("ADMIN_LOGIN2")
ADMIN_PASSWORD2 = os.getenv("ADMIN_PASSWORD2")

ADMINS = {1899643695, 1980103568}

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
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
        'lang_ru': "Русский",
        'lang_en': "English"
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
        'lang_ru': "Русский",
        'lang_en': "English"
    }
}

class RequestForm(StatesGroup):
    name = State()
    phone = State()
    message = State()
    attach_doc_choice = State()
    attach_docs = State()
    language = State()

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
            [KeyboardButton(text=translations['ru']['lang_ru']), KeyboardButton(text=translations['en']['lang_en'])]
        ],
        resize_keyboard=True
    )

async def get_lang(state: FSMContext):
    data = await state.get_data()
    return data.get('lang', 'ru')

@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext):
    # язык не выбран - предлагаем выбрать
    data = await state.get_data()
    if not data.get('lang'):
        await state.set_state(RequestForm.language)
        await message.answer(translations['ru']['choose_language'], reply_markup=get_lang_kb())
        return
    lang = data['lang']
    await bot.send_photo(
        chat_id=message.chat.id,
        photo="AgACAgIAAxkBAAE1YB1oMkDR4lZwFBBjnUnPc4tHstWRRwAC4esxG9dOmUnr1RkgaeZ_hQEAAwIAA3kAAzYE",
        caption=translations[lang]['welcome'],
        reply_markup=get_menu_kb(message.from_user.id, lang)
    )

@dp.message(RequestForm.language)
async def choose_lang(message: types.Message, state: FSMContext):
    if message.text == translations['ru']['lang_ru']:
        lang = 'ru'
    elif message.text == translations['en']['lang_en']:
        lang = 'en'
    else:
        await message.answer(
            "Пожалуйста, выберите язык кнопкой / Please choose language with button.",
            reply_markup=get_lang_kb()
        )
        return
    await state.update_data(lang=lang)
    await start(message, state)
    await state.clear()
        
@dp.message(lambda m: m.text in [translations['ru']['main_menu_btn'], translations['en']['main_menu_btn']])
async def to_main_menu(message: types.Message, state: FSMContext):
    lang = await get_lang(state)
    await state.clear()
    await bot.send_photo(
        chat_id=message.chat.id,
        photo="AgACAgIAAxkBAAE1YB1oMkDR4lZwFBBjnUnPc4tHstWRRwAC4esxG9dOmUnr1RkgaeZ_hQEAAwIAA3kAAzYE",
        caption=translations[lang]['welcome'],
        reply_markup=get_menu_kb(message.from_user.id, lang)
    )

@dp.message(lambda m: m.text == translations['ru']['contacts_button'] or m.text == translations['en']['contacts_button'])
async def contacts(message: types.Message, state: FSMContext):
    lang = await get_lang(state)
    await message.answer(translations[lang]['contacts'], reply_markup=get_menu_kb(message.from_user.id, lang))

@dp.message(lambda m: m.text == translations['ru']['consult_button'] or m.text == translations['en']['consult_button'])
async def consultation(message: types.Message, state: FSMContext):
    lang = await get_lang(state)
    await state.set_state(RequestForm.name)
    await state.update_data(user_id=message.from_user.id, lang=lang)
    await message.answer(translations[lang]['enter_name'], reply_markup=get_back_kb(lang))

@dp.message(RequestForm.name)
async def get_name(message: types.Message, state: FSMContext):
    lang = await get_lang(state)
    if message.text == translations[lang]['back']:
        await state.clear()
        await start(message, state)
        return
    if message.text == translations[lang]['main_menu_btn']:
        await state.clear()
        await start(message, state)
        return
    await state.update_data(name=message.text)
    await state.set_state(RequestForm.phone)
    await message.answer(translations[lang]['enter_phone'], reply_markup=get_back_kb(lang))

@dp.message(RequestForm.phone)
async def get_phone(message: types.Message, state: FSMContext):
    lang = await get_lang(state)
    if message.text == translations[lang]['back']:
        await state.set_state(RequestForm.name)
        await message.answer(translations[lang]['enter_name'], reply_markup=get_back_kb(lang))
        return
    if message.text == translations[lang]['main_menu_btn']:
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
    lang = await get_lang(state)
    if message.text == translations[lang]['back']:
        await state.set_state(RequestForm.phone)
        await message.answer(translations[lang]['enter_phone'], reply_markup=get_back_kb(lang))
        return
    if message.text == translations[lang]['main_menu_btn']:
        await state.clear()
        await start(message, state)
        return
    await state.update_data(message=message.text)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=translations[lang]['attach_yes']), KeyboardButton(text=translations[lang]['attach_no'])], [KeyboardButton(text=translations[lang]['main_menu_btn'])]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await state.set_state(RequestForm.attach_doc_choice)
    await message.answer(translations[lang]['attach_ask'], reply_markup=kb)

@dp.message(RequestForm.attach_doc_choice)
async def attach_doc_choice(message: types.Message, state: FSMContext):
    lang = await get_lang(state)
    if message.text == translations[lang]['attach_yes']:
        await state.set_state(RequestForm.attach_docs)
        await state.update_data(documents=[])
        await message.answer(
            translations[lang]['attach_file'],
            reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="/done")], [KeyboardButton(text=translations[lang]['main_menu_btn'])]], resize_keyboard=True)
        )
    elif message.text == translations[lang]['attach_no']:
        await finish_request(message, state)
    elif message.text == translations[lang]['main_menu_btn']:
        await state.clear()
        await start(message, state)
    else:
        await message.answer(translations[lang]['not_added'])

@dp.message(RequestForm.attach_docs, lambda m: m.document)
async def handle_docs(message: types.Message, state: FSMContext):
    lang = await get_lang(state)
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
    lang = await get_lang(state)
    # поддержка главного меню
    if message.text == translations[lang]['main_menu_btn']:
        await state.clear()
        await start(message, state)
        return

async def finish_request(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('lang', 'ru')
    from datetime import datetime
    now = datetime.now().isoformat()
    user_id = message.from_user.id
    with conn:
        conn.execute(
            "INSERT INTO requests (user_id, name, phone, message, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, data['name'], data['phone'], data['message'], now, 'new')
        )
        # Документы, если есть
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

@dp.message(lambda m: m.text == translations['ru']['admin_panel_button'] or m.text == translations['en']['admin_panel_button'])
async def admin_panel(message: types.Message, state: FSMContext):
    lang = await get_lang(state)
    if message.from_user.id not in ADMINS:
        await message.answer(translations[lang]['forbidden'])
        return
    admin_url = "https://web-production-bb98.up.railway.app/admin"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Перейти в админку", url=admin_url)]
    ])
    await message.answer("Откройте админ-панель:", reply_markup=kb)

@dp.message(lambda m: m.text == translations['ru']['faq_button'] or m.text == translations['en']['faq_button'])
async def show_faq(message: types.Message, state: FSMContext):
    lang = await get_lang(state)
    await message.answer(translations[lang]['faq_not_added'], reply_markup=get_menu_kb(message.from_user.id, lang))

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
    # Получаем документы к каждой заявке
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

@app.get("/api/download/{file_id}")
async def download_document(file_id: str, request: Request):
    token = request.headers.get("X-Admin-Token") or request.query_params.get("token")
    authorize(request, token)
    # Имя файла из базы (если нет — используем file_id)
    row = conn.execute("SELECT file_name FROM documents WHERE file_id = ?", (file_id,)).fetchone()
    file_name = row[0] if row else file_id
    url = f"https://api.telegram.org/bot{API_TOKEN}/getFile?file_id={file_id}"
    import requests
    resp = requests.get(url)
    if not resp.ok or 'result' not in resp.json():
        raise HTTPException(status_code=404, detail="Файл не найден в Telegram")
    file_path = resp.json()['result']['file_path']
    file_url = f"https://api.telegram.org/file/bot{API_TOKEN}/{file_path}"
    file_resp = requests.get(file_url, stream=True)
    import urllib.parse
    import mimetypes
    mime_type, _ = mimetypes.guess_type(file_name)
    if not mime_type:
        mime_type = "application/octet-stream"
    try:
        file_name.encode('latin-1')
        content_disposition = f'attachment; filename="{file_name}"'
    except UnicodeEncodeError:
        quoted_name = urllib.parse.quote(file_name)
        content_disposition = f"attachment; filename*=UTF-8''{quoted_name}"
    headers = {
        "Content-Disposition": content_disposition
    }
    return StreamingResponse(file_resp.raw, headers=headers, media_type=mime_type)

@app.post("/api/reply")
async def reply_user(req: ReplyRequest, request: Request):
    token = request.headers.get("X-Admin-Token")
    authorize(request, token)
    try:
        await bot.send_message(req.user_id, req.message)
        with conn:
            conn.execute("UPDATE requests SET status = 'done' WHERE user_id = ?", (req.user_id,))
        return {"status": "sent"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        logging.error(f"Ошибка отправки сообщения: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/status")
async def update_status(req: StatusRequest, request: Request):
    token = request.headers.get("X-Admin-Token")
    authorize(request, token)
    with conn:
        conn.execute("UPDATE requests SET status = ? WHERE user_id = ?", (req.status, req.user_id))
        return {"status": "updated"}

@app.get("/admin", response_class=HTMLResponse)
async def admin_html(request: Request):
    # Для краткости: здесь админка как была, так и осталась — можно также интегрировать мультиязычность и подписи в JS
    # (см. предыдущие ответы, если нужно полностью перевести интерфейс админки)
    return """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>LegalBot Admin</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://unpkg.com/@tabler/core@latest/dist/css/tabler.min.css" rel="stylesheet"/>
    <style>
        body { background: #f4f6fa; }
        .table-responsive { margin-top: 28px; }
        .actions .btn { margin-right: 8px; }
        .filter-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }
        .filter-row input, .filter-row select { min-width: 160px; }
        .btn-download {
            display: inline-block;
            padding: 0.25rem 0.8rem;
            font-size: 1rem;
            font-weight: 500;
            color: #fff !important;
            background-color: #206bc4;
            border: none;
            border-radius: 0.4rem;
            text-align: center;
            text-decoration: none !important;
            cursor: pointer;
            transition: background 0.2s;
            margin-bottom: 2px;
        }
        .btn-download:hover { background-color: #1a5ba6; }
        th, td { border-right: 1px solid #dde2e9; }
        th:last-child, td:last-child { border-right: none; }
        @media (max-width: 600px) {
            .btn-download {
                font-size: 0.98rem;
                padding: 0.3rem 0.7rem;
            }
        }
    </style>
</head>
<body>
<div id="loginDiv" style="max-width:350px;margin:80px auto;display:none;">
    <h3>Вход в админ-панель</h3>
    <input id="loginInput" class="form-control mb-2" placeholder="Логин">
    <input id="passwordInput" type="password" class="form-control mb-2" placeholder="Пароль">
    <button id="loginBtn" class="btn btn-primary w-100">Войти</button>
    <div id="loginError" style="color:red;margin-top:10px;display:none;">Неверный логин или пароль</div>
</div>
<div id="adminDiv" style="display:none;">
    <div class="container-xl">
        <div class="page-header d-print-none mt-4 mb-2">
            <h2 class="page-title">Заявки и документы LegalBot</h2>
            <button id="logoutBtn" class="btn btn-outline-danger float-end">Выйти</button>
        </div>
        <div class="filter-row">
            <input type="search" class="form-control" id="searchInput" placeholder="Поиск по имени, сообщению и т.д.">
            <select class="form-select" id="statusFilter">
                <option value="">Все статусы</option>
                <option value="new">Новая</option>
                <option value="in_work">В работе</option>
                <option value="done">Готово</option>
            </select>
        </div>
        <div id="loader" class="text-center py-5">Загрузка заявок...</div>
        <div class="table-responsive" id="tableDiv" style="display:none;">
            <table class="table table-vcenter table-striped" id="reqTable">
                <thead>
                    <tr>
                        <th>ПОЛЬЗОВАТЕЛЬ</th>
                        <th>ИМЯ</th>
                        <th>ТЕЛЕФОН</th>
                        <th>СООБЩЕНИЕ</th>
                        <th>ВРЕМЯ</th>
                        <th>СТАТУС</th>
                        <th>ДОКУМЕНТЫ</th>
                        <th>ДЕЙСТВИЯ</th>
                    </tr>
                </thead>
                <tbody id="reqTbody"></tbody>
            </table>
        </div>
    </div>
</div>
<script>
let adminToken = null;

function formatDatetime(dt) {
    if (!dt) return "";
    const d = new Date(dt);
    const pad = n => n < 10 ? "0"+n : n;
    return pad(d.getDate()) + "." + pad(d.getMonth()+1) + "." + d.getFullYear() +
        " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
}

async function checkAuth() {
    adminToken = null;
    document.getElementById('loginDiv').style.display = '';
    document.getElementById('adminDiv').style.display = 'none';
}
document.getElementById('loginBtn').onclick = async function() {
    const login = document.getElementById('loginInput').value;
    const password = document.getElementById('passwordInput').value;
    let res = await fetch('/api/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({login, password})
    });
    if (res.status === 200) {
        let data = await res.json();
        adminToken = data.token;
        document.getElementById('loginDiv').style.display = 'none';
        document.getElementById('adminDiv').style.display = '';
        document.getElementById('loginError').style.display = 'none';
        load();
    } else {
        document.getElementById('loginError').style.display = '';
    }
};

document.getElementById('logoutBtn').onclick = function() {
    adminToken = null;
    document.getElementById('adminDiv').style.display = 'none';
    document.getElementById('loginDiv').style.display = '';
};

window.onload = checkAuth;

async function apiFetch(url, options = {}) {
    options.headers = options.headers || {};
    if(adminToken) options.headers['X-Admin-Token'] = adminToken;
    return fetch(url, options);
}

async function load() {
    document.getElementById('loader').style.display = "";
    document.getElementById('tableDiv').style.display = "none";
    try {
        const res = await apiFetch('/api/requests');
        if(res.status !== 200) {
            throw new Error('Ошибка запроса, авторизация истекла');
        }
        let allData = await res.json();
        let tBody = document.getElementById('reqTbody');
        tBody.innerHTML = '';
        for(const r of allData) {
            let docsHtml = '';
            if (r.documents && r.documents.length > 0) {
                docsHtml = r.documents.map(doc => 
                    `<a class="btn-download" href="/api/download/${doc.file_id}?token=${encodeURIComponent(adminToken)}" target="_blank">${doc.file_name}</a>`
                ).join("<br>");
            }
            tBody.innerHTML += `<tr>
                <td>${r.user_id}</td>
                <td>${r.name ?? ""}</td>
                <td>${r.phone ?? ""}</td>
                <td>${r.message ?? ""}</td>
                <td>${formatDatetime(r.created_at)}</td>
                <td>${r.status}</td>
                <td>${docsHtml}</td>
                <td>
                  <button class="btn btn-sm btn-success" onclick="replyUser(${r.user_id}, '${(r.name ?? '').replace(/'/g,'&#39;')}')">Ответить</button>
                  <select class="form-select form-select-sm d-inline-block w-auto" onchange="changeStatus(${r.user_id}, this.value)">
                    <option value="new" ${r.status === 'new' ? 'selected' : ''}>new</option>
                    <option value="in_work" ${r.status === 'in_work' ? 'selected' : ''}>in_work</option>
                    <option value="done" ${r.status === 'done' ? 'selected' : ''}>done</option>
                  </select>
                </td>
            </tr>`;
        }
        document.getElementById('loader').style.display = "none";
        document.getElementById('tableDiv').style.display = "";
    } catch(e) {
        alert(e.message || 'Ошибка загрузки заявок');
        checkAuth();
    }
}

function replyUser(userId, userName) {
    const msg = prompt(`Введите ответ для пользователя ${userName} (id=${userId}):`);
    if (msg) {
        apiFetch('/api/reply', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({user_id: userId, message: msg})
        }).then(res => {
            if (res.status === 200) {
                alert('Ответ отправлен!');
                load();
            } else {
                alert('Не удалось отправить ответ');
            }
        });
    }
}

function changeStatus(userId, status) {
    apiFetch('/api/status', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_id: userId, status: status})
    }).then(res => {
        if (res.status === 200) {
            alert('Статус обновлен!');
            load();
        } else {
            alert('Ошибка при обновлении статуса');
        }
    });
}
</script>
</body>
</html>
"""

async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, loop="asyncio", log_level="info")
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve())
    bot_task = asyncio.create_task(dp.start_polling(bot))
    await asyncio.gather(api_task, bot_task)

if __name__ == "__main__":
    asyncio.run(main())
