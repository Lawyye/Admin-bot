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

# Новый FSM: добавлены attach, document, document_more
class RequestForm(StatesGroup):
    name = State()
    phone = State()
    message = State()
    attach = State()
    document = State()
    document_more = State()

def get_menu_kb(user_id: int):
    keyboard = [
        [KeyboardButton(text="Записаться на консультацию")],
        [KeyboardButton(text="Часто задаваемые вопросы")],
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
async def ask_attach(message: types.Message, state: FSMContext):
    await state.update_data(message=message.text)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Да"), KeyboardButton(text="Нет")]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer("У вас есть документы, которые вы хотите прикрепить? (До 3 файлов)", reply_markup=kb)
    await state.set_state(RequestForm.attach)

@dp.message(RequestForm.attach)
async def handle_attach_choice(message: types.Message, state: FSMContext):
    choice = message.text.strip().lower()
    if choice == "нет":
        # Отправляем заявку без документов
        data = await state.get_data()
        from datetime import datetime
        now = datetime.now().isoformat()
        with conn:
            conn.execute(
                "INSERT INTO requests (user_id, name, phone, message, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
                (message.from_user.id, data['name'], data['phone'], data['message'], now, 'new')
            )
        await bot.send_message(
            ADMIN_CHAT_ID,
            f"Новая заявка:\nИмя: {data['name']}\nТел: {data['phone']}\nПроблема: {data['message']}"
        )
        await message.answer("Спасибо! Мы свяжемся с вами.", reply_markup=get_menu_kb(message.from_user.id))
        await state.clear()
    elif choice == "да":
        await state.update_data(documents=[])
        await message.answer("Пожалуйста, отправьте первый документ (PDF, DOCX и т.д.).")
        await state.set_state(RequestForm.document)
    else:
        await message.answer("Пожалуйста, выберите \"Да\" или \"Нет\".")

@dp.message(RequestForm.document)
async def handle_document_in_request(message: types.Message, state: FSMContext):
    if not message.document:
        await message.answer("Пожалуйста, отправьте файл-документ.")
        return
    data = await state.get_data()
    documents = data.get("documents", [])
    from datetime import datetime
    file_id = message.document.file_id
    file_name = message.document.file_name
    user_id = message.from_user.id
    sent_at = datetime.now().isoformat()
    documents.append({"file_id": file_id, "file_name": file_name, "sent_at": sent_at})
    await state.update_data(documents=documents)
    if len(documents) < 3:
        # спросить, хочет ли пользователь ещё документ
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Да"), KeyboardButton(text="Нет")]],
            resize_keyboard=True, one_time_keyboard=True
        )
        await message.answer(f"Документ добавлен. Хотите прикрепить ещё один документ? ({len(documents)}/3)", reply_markup=kb)
        await state.set_state(RequestForm.document_more)
    else:
        await message.answer("Это был третий документ — лимит достигнут. Заявка отправляется.")
        await finish_request_with_documents(message, state)

@dp.message(RequestForm.document_more)
async def handle_more_docs(message: types.Message, state: FSMContext):
    choice = message.text.strip().lower()
    data = await state.get_data()
    documents = data.get("documents", [])
    if choice == "да":
        if len(documents) < 3:
            await message.answer("Пожалуйста, отправьте следующий документ (PDF, DOCX и т.д.).")
            await state.set_state(RequestForm.document)
        else:
            await message.answer("Вы уже прикрепили 3 документа. Заявка отправляется.")
            await finish_request_with_documents(message, state)
    elif choice == "нет":
        await finish_request_with_documents(message, state)
    else:
        await message.answer("Пожалуйста, выберите \"Да\" или \"Нет\".")

async def finish_request_with_documents(message: types.Message, state: FSMContext):
    data = await state.get_data()
    from datetime import datetime
    now = datetime.now().isoformat()
    user_id = message.from_user.id
    # Сохраняем заявку
    with conn:
        conn.execute(
            "INSERT INTO requests (user_id, name, phone, message, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, data['name'], data['phone'], data['message'], now, 'new')
        )
    # Сохраняем документы и отправляем админу
    documents = data.get("documents", [])
    if documents:
        await bot.send_message(
            ADMIN_CHAT_ID,
            f"Новая заявка с документами:\nИмя: {data['name']}\nТел: {data['phone']}\nПроблема: {data['message']}"
        )
        for doc in documents:
            with conn:
                conn.execute(
                    "INSERT INTO documents (user_id, file_id, file_name, sent_at) VALUES (?, ?, ?, ?)",
                    (user_id, doc["file_id"], doc["file_name"], doc["sent_at"])
                )
            await bot.send_document(
                ADMIN_CHAT_ID,
                doc["file_id"],
                caption=f"Документ от пользователя {message.from_user.full_name} ({user_id})"
            )
    else:
        await bot.send_message(
            ADMIN_CHAT_ID,
            f"Новая заявка:\nИмя: {data['name']}\nТел: {data['phone']}\nПроблема: {data['message']}"
        )
    await message.answer("Спасибо! Мы свяжемся с вами.", reply_markup=get_menu_kb(user_id))
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

# Объединенный эндпоинт для заявок и документов
@app.get("/api/all_records")
async def get_all_records(request: Request):
    token = request.headers.get("X-Admin-Token")
    authorize(request, token)
    reqs = conn.execute("""
        SELECT id, user_id, name, phone, message, created_at, status, NULL as file_id, NULL as file_name
        FROM requests
    """).fetchall()
    docs = conn.execute("""
        SELECT id+1000000 as id, user_id, NULL as name, NULL as phone, NULL as message, sent_at as created_at, NULL as status, file_id, file_name
        FROM documents
    """).fetchall()
    all_records = [dict(zip(
        ["id", "user_id", "name", "phone", "message", "created_at", "status", "file_id", "file_name"], r
    )) for r in list(reqs) + list(docs)]
    all_records.sort(key=lambda r: r["created_at"], reverse=True)
    return all_records

@app.get("/api/download/{file_id}")
async def download_document(file_id: str, request: Request):
    import requests
    token = request.headers.get("X-Admin-Token") or request.query_params.get("token")
    authorize(request, token)
    row = conn.execute(
        "SELECT file_name FROM documents WHERE file_id = ?", (file_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Файл не найден в базе")
    file_name = row[0]
    url = f"https://api.telegram.org/bot{API_TOKEN}/getFile?file_id={file_id}"
    resp = requests.get(url)
    data = resp.json()
    if not resp.ok or 'result' not in data:
        detail = data.get("description", "Файл не найден в Telegram")
        raise HTTPException(status_code=404, detail=detail)
    file_path = data['result']['file_path']
    file_url = f"https://api.telegram.org/file/bot{API_TOKEN}/{file_path}"
    file_resp = requests.get(file_url, stream=True)
    if not file_resp.ok:
        raise HTTPException(status_code=404, detail="Ошибка скачивания файла с Telegram серверов")
    from mimetypes import guess_type
    content_type = guess_type(file_name)[0] or "application/octet-stream"
    headers = {
        "Content-Disposition": f'attachment; filename="{file_name}"'
    }
    return StreamingResponse(file_resp.raw, headers=headers, media_type=content_type)

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

# КРАСИВАЯ АДМИН-ПАНЕЛЬ
@app.get("/admin", response_class=HTMLResponse)
async def admin_html(request: Request):
    return """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>LegalBot Admin</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <!-- Tabler CSS и иконки -->
    <link href="https://unpkg.com/@tabler/core@latest/dist/css/tabler.min.css" rel="stylesheet"/>
    <link href="https://unpkg.com/@tabler/icons@latest/iconfont/tabler-icons.min.css" rel="stylesheet"/>
    <style>
        body { background: #f8fafc; }
        .login-card {
            max-width: 380px;
            margin: 100px auto;
            background: #fff;
            border-radius: 22px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.14);
            padding: 32px 32px 24px 32px;
            transition: box-shadow .2s;
        }
        .login-card h3 { margin-bottom: 22px; }
        .login-card input { margin-bottom: 14px; }
        .logout-btn { float: right; margin-top: -8px; }
        .page-title {
            font-size: 2.2rem;
            font-weight: 700;
            letter-spacing: -1px;
            margin-bottom: 0.7em;
        }
        .filter-row {
            margin-bottom: 18px;
            gap: 18px;
        }
        .table-responsive { margin-top: 28px; border-radius: 18px; overflow: auto;}
        .table { background: #fff; border-radius: 18px; }
        .table th, .table td { vertical-align: middle !important;}
        .table th { background: #f2f4f7; font-weight: 600;}
        .table tbody tr:hover { background: #eaf0fa; transition: background .2s;}
        .badge-status { font-size: .88em; padding: .3em 1em; border-radius: 12px;}
        .status-new { background: #e3f6ff; color: #1779c4; }
        .status-in_work { background: #ffeec7; color: #a67b00; }
        .status-done { background: #caf6e3; color: #279152; }
        .nowrap { white-space: nowrap; }
        @media (max-width: 768px) {
            .container-xl { padding: 0 2px; }
            .page-title { font-size: 1.3rem;}
            .login-card { margin: 38px auto; }
        }
    </style>
</head>
<body>
<div id="loginDiv" class="login-card" style="display:none;">
    <h3 class="text-center">Вход в админ-панель</h3>
    <input id="loginInput" class="form-control" placeholder="Логин" autofocus>
    <input id="passwordInput" type="password" class="form-control" placeholder="Пароль">
    <button id="loginBtn" class="btn btn-primary w-100 mt-2" style="font-size:1.1em;">
        <i class="ti ti-login-2"></i> Войти
    </button>
    <div id="loginError" style="color:#e53e3e;margin-top:14px;display:none;">Неверный логин или пароль</div>
</div>
<div id="adminDiv" style="display:none;">
    <div class="container-xl">
        <div class="page-header d-print-none mt-4 mb-2 d-flex align-items-center justify-content-between">
            <span class="page-title"><i class="ti ti-shield-lock"></i> Заявки и документы LegalBot</span>
            <button id="logoutBtn" class="btn btn-outline-danger logout-btn">
                <i class="ti ti-logout"></i> Выйти
            </button>
        </div>
        <div class="filter-row d-flex align-items-center flex-wrap">
            <input type="search" class="form-control" style="max-width:260px;" id="searchInput" placeholder="Поиск по имени, сообщению или файлу">
            <select class="form-select" style="max-width:180px;" id="statusFilter">
                <option value="">Все статусы</option>
                <option value="new">Новая</option>
                <option value="in_work">В работе</option>
                <option value="done">Готово</option>
            </select>
        </div>
        <div id="loader" class="text-center py-5">
            <div class="spinner-border text-primary" style="width:2.5rem;height:2.5rem;"></div>
            <div style="margin-top:18px;color:#888;">Загрузка...</div>
        </div>
        <div class="table-responsive" id="allTableDiv" style="display:none;">
            <table class="table table-vcenter table-striped">
                <thead>
                    <tr>
                        <th>Пользователь</th>
                        <th>Имя</th>
                        <th>Телефон</th>
                        <th>Сообщение / Документ</th>
                        <th>Дата</th>
                        <th>Статус</th>
                        <th>Скачать</th>
                    </tr>
                </thead>
                <tbody id="allTbody"></tbody>
            </table>
        </div>
    </div>
</div>
<script>
let adminToken = null;

function show(el) { el.style.display = ''; }
function hide(el) { el.style.display = 'none'; }

async function checkAuth() {
    adminToken = null;
    show(document.getElementById('loginDiv'));
    hide(document.getElementById('adminDiv'));
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
        hide(document.getElementById('loginDiv'));
        show(document.getElementById('adminDiv'));
        document.getElementById('loginError').style.display = 'none';
        loadAll();
    } else {
        document.getElementById('loginError').style.display = '';
    }
};

document.getElementById('logoutBtn').onclick = function() {
    adminToken = null;
    hide(document.getElementById('adminDiv'));
    show(document.getElementById('loginDiv'));
};

window.onload = checkAuth;

// Функция для защищённых API-запросов
async function apiFetch(url, options = {}) {
    options.headers = options.headers || {};
    if(adminToken) options.headers['X-Admin-Token'] = adminToken;
    return fetch(url, options);
}

function escapeHtml(text) {
    if (!text) return "";
    return text.replace(/[<>&"']/g, function(c) {
        return {'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c];
    });
}

// --- ФУНКЦИЯ ФОРМАТИРОВАНИЯ ДАТЫ ---
function formatDate(dt) {
    if (!dt) return "";
    let d = new Date(dt);
    if (isNaN(d)) {
        let m = dt.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)/);
        if (m) return m[1].split('-').reverse().join('.') + ' ' + m[2];
        return dt.replace("T", " ").slice(0, 16);
    }
    return d.toLocaleDateString('ru-RU', { year: 'numeric', month: '2-digit', day: '2-digit' })
        + ' ' +
        d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', hour12: false });
}

// --- ЦВЕТНЫЕ БЕЙДЖИ ДЛЯ СТАТУСОВ ---
function statusBadge(status) {
    if (!status) return '';
    let text = status === 'new' ? 'Новая' : status === 'in_work' ? 'В работе' : status === 'done' ? 'Готово' : status;
    let cls = 'badge-status ';
    if (status === 'new') cls += 'status-new';
    else if (status === 'in_work') cls += 'status-in_work';
    else if (status === 'done') cls += 'status-done';
    else cls += 'bg-secondary';
    return `<span class="${cls}">${text}</span>`;
}

// --- ОСНОВНАЯ ЗАГРУЗКА ТАБЛИЦЫ ---
async function loadAll() {
    document.getElementById('loader').style.display = "";
    document.getElementById('allTableDiv').style.display = "none";
    try {
        const res = await apiFetch('/api/all_records');
        if(res.status !== 200) throw new Error('Ошибка запроса, авторизация истекла');
        let rows = await res.json();
        let tBody = document.getElementById('allTbody');
        tBody.innerHTML = '';
        for(const r of rows) {
            let isDoc = r.file_id !== null && r.file_id !== undefined;
            let safeUser = escapeHtml(String(r.user_id||""));
            let safeName = escapeHtml(r.name||"");
            let safePhone = escapeHtml(r.phone||"");
            let safeMsg = escapeHtml(r.message||"");
            let safeFile = escapeHtml(r.file_name||"");
            let safeDate = formatDate(r.created_at||"");
            let safeStatus = escapeHtml(r.status||"");
            tBody.innerHTML += `<tr>
              <td>${safeUser}</td>
              <td>${safeName}</td>
              <td>${safePhone}</td>
              <td>
                ${isDoc
                  ? `<i class="ti ti-file-text"></i> <b>Документ:</b> ${safeFile}`
                  : `<i class="ti ti-message"></i> ${safeMsg}`
                }
              </td>
              <td class="nowrap">${safeDate}</td>
              <td>${statusBadge(r.status)}</td>
              <td>
                ${isDoc
                  ? `<a class="btn btn-sm btn-primary" title="Скачать" href="/api/download/${r.file_id}?token=${encodeURIComponent(adminToken)}" target="_blank">
                        <i class="ti ti-download"></i>
                    </a>`
                  : ''
                }
              </td>
            </tr>`;
        }
        document.getElementById('loader').style.display = "none";
        document.getElementById('allTableDiv').style.display = "";
    } catch(e) {
        alert(e.message || 'Ошибка загрузки данных');
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

# Удалены старые обработчики "Отправить документ" и document вне FSM

async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, loop="asyncio", log_level="info")
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve())
    bot_task = asyncio.create_task(dp.start_polling(bot))
    await asyncio.gather(api_task, bot_task)

if __name__ == "__main__":
    asyncio.run(main())
