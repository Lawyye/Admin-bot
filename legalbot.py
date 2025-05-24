import asyncio
import logging
import sqlite3
import os

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

class RequestForm(StatesGroup):
    name = State()
    phone = State()
    message = State()

def get_menu_kb(user_id: int):
    keyboard = [
        [KeyboardButton(text="Записаться на консультацию")],
        [KeyboardButton(text="Часто задаваемые вопросы")],
        [KeyboardButton(text="Отправить документ")],
        [KeyboardButton(text="Контакты")]
    ]
    if user_id in ADMINS:
        keyboard.append([KeyboardButton(text="Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer("Добро пожаловать в LegalBot!", reply_markup=get_menu_kb(message.from_user.id))

@dp.message(lambda m: m.text == "Контакты")
async def contacts(message: types.Message):
    await message.answer("г. Астрахань, ул. Татищева 20\n+7 988 600 56 61", reply_markup=get_menu_kb(message.from_user.id))

@dp.message(lambda m: m.text == "Записаться на консультацию")
async def consultation(message: types.Message, state: FSMContext):
    await state.set_state(RequestForm.name)
    await state.update_data(user_id=message.from_user.id)
    await message.answer("Введите ваше имя:", reply_markup=get_menu_kb(message.from_user.id))

@dp.message(RequestForm.name)
async def get_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(RequestForm.phone)
    await message.answer("Введите номер телефона:", reply_markup=get_menu_kb(message.from_user.id))

@dp.message(RequestForm.phone)
async def get_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await state.set_state(RequestForm.message)
    await message.answer("Опишите вашу проблему:", reply_markup=get_menu_kb(message.from_user.id))

@dp.message(RequestForm.message)
async def save_request(message: types.Message, state: FSMContext):
    data = await state.get_data()
    from datetime import datetime
    now = datetime.now().isoformat()
    with conn:
        conn.execute(
            "INSERT INTO requests (user_id, name, phone, message, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
            (message.from_user.id, data['name'], data['phone'], message.text, now, 'new')
        )
        await bot.send_message(
            ADMIN_CHAT_ID,
            f"Новая заявка:\nИмя: {data['name']}\nТел: {data['phone']}\nПроблема: {message.text}"
        )
        await message.answer("Спасибо! Мы свяжемся с вами.", reply_markup=get_menu_kb(message.from_user.id))
        await state.clear()

@dp.message(lambda m: m.text == "Админ-панель")
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMINS:
        await message.answer("Доступ запрещён.")
        return
    admin_url = "https://web-production-bb98.up.railway.app/admin"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Перейти в админку", url=admin_url)]
    ])
    await message.answer("Откройте админ-панель:", reply_markup=kb)

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
    try:
        file_name.encode('latin-1')
        content_disposition = f'attachment; filename="{file_name}"'
    except UnicodeEncodeError:
        quoted_name = urllib.parse.quote(file_name)
        content_disposition = f"attachment; filename*=UTF-8''{quoted_name}"
    headers = {"Content-Disposition": content_disposition}
    return StreamingResponse(file_resp.raw, headers=headers, media_type=file_resp.headers.get('Content-Type', 'application/octet-stream'))

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
    // Преобразование строки ISO в формат DD.MM.YYYY HH:mm
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
                <td></td>
            </tr>`;
        }
        document.getElementById('loader').style.display = "none";
        document.getElementById('tableDiv').style.display = "";
    } catch(e) {
        alert(e.message || 'Ошибка загрузки заявок');
        checkAuth();
    }
}
</script>
</body>
</html>
"""

@dp.message(lambda m: m.text == "Часто задаваемые вопросы")
async def show_faq(message: types.Message):
    await message.answer("Часто задаваемые вопросы пока не добавлены.", reply_markup=get_menu_kb(message.from_user.id))

@dp.message(lambda m: m.text == "Отправить документ")
async def ask_document(message: types.Message):
    await message.answer("Пожалуйста, отправьте документ (PDF, DOCX и т.д.)", reply_markup=get_menu_kb(message.from_user.id))

@dp.message(lambda m: m.document)
async def handle_document(message: types.Message):
    from datetime import datetime
    file_id = message.document.file_id
    file_name = message.document.file_name
    user_id = message.from_user.id
    sent_at = datetime.now().isoformat()
    with conn:
        conn.execute(
            "INSERT INTO documents (user_id, file_id, file_name, sent_at) VALUES (?, ?, ?, ?)",
            (user_id, file_id, file_name, sent_at)
        )
    await bot.send_document(
        ADMIN_CHAT_ID,
        file_id,
        caption=f"Документ от пользователя {message.from_user.full_name} ({user_id})"
    )
    await message.answer("Документ получен и отправлен администратору. Спасибо!", reply_markup=get_menu_kb(user_id))

async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, loop="asyncio", log_level="info")
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve())
    bot_task = asyncio.create_task(dp.start_polling(bot))
    await asyncio.gather(api_task, bot_task)

if __name__ == "__main__":
    asyncio.run(main())
