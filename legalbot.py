import asyncio 
import logging 
import sqlite3 
import os

from aiogram import Bot, Dispatcher, types 
from aiogram.filters import CommandStart 
from aiogram.fsm.context import FSMContext 
from aiogram.fsm.state import StatesGroup, State 
from aiogram.fsm.storage.memory import MemoryStorage 
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from fastapi import FastAPI, Request, HTTPException, status 
from fastapi.responses import HTMLResponse 
from pydantic import BaseModel 
import uvicorn

API_TOKEN = os.getenv("API_TOKEN") 
ADMIN_CHAT_ID_ENV = os.getenv("ADMIN_CHAT_ID") 
if not ADMIN_CHAT_ID_ENV: 
    raise ValueError("ADMIN_CHAT_ID is not set")
ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_ENV) 
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "secure-token-123")

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
        status TEXT DEFAULT 'new')""") 
conn.commit()

class RequestForm(StatesGroup): 
    name = State() 
    phone = State() 
    message = State()

menu_kb = ReplyKeyboardMarkup( 
    keyboard=[ 
        [KeyboardButton(text="Записаться на консультацию")], 
        [KeyboardButton(text="Часто задаваемые вопросы")], 
        [KeyboardButton(text="Отправить документ")], 
        [KeyboardButton(text="Контакты")] ], 
    resize_keyboard=True )

@dp.message(CommandStart()) 
async def start(message: types.Message): 
    await message.answer("Добро пожаловать в LegalBot!", reply_markup=menu_kb)

@dp.message(lambda m: m.text == "Контакты") 
async def contacts(message: types.Message): 
    await message.answer("г. Астрахань, ул. Татищева 20\n+7 988 600 56 61")

@dp.message(lambda m: m.text == "Записаться на консультацию") 
async def consultation(message: types.Message, state: FSMContext): 
    await state.set_state(RequestForm.name) 
    await state.update_data(user_id=message.from_user.id) 
    await message.answer("Введите ваше имя:")

@dp.message(RequestForm.name) 
async def get_name(message: types.Message, state: FSMContext): 
    await state.update_data(name=message.text) 
    await state.set_state(RequestForm.phone) 
    await message.answer("Введите номер телефона:")

@dp.message(RequestForm.phone) 
async def get_phone(message: types.Message, state: FSMContext): 
    await state.update_data(phone=message.text) 
    await state.set_state(RequestForm.message) 
    await message.answer("Опишите вашу проблему:")

@dp.message(RequestForm.message) 
async def save_request(message: types.Message, state: FSMContext): 
    data = await state.get_data() 
    from datetime import datetime
    now = datetime.now().isoformat() 
    with conn: 
        conn.execute("INSERT INTO requests (user_id, name, phone, message, created_at, status) VALUES (?, ?, ?, ?, ?, ?)", (message.from_user.id, data['name'], data['phone'], message.text, now, 'new')) 
        await bot.send_message(ADMIN_CHAT_ID, f"Новая заявка:\nИмя: {data['name']}\nТел: {data['phone']}\nПроблема: {message.text}") 
        await message.answer("Спасибо! Мы свяжемся с вами.", reply_markup=menu_kb) 
        await state.clear()

app = FastAPI()

class ReplyRequest(BaseModel): 
    user_id: int 
    message: str

class StatusRequest(BaseModel): 
    user_id: int 
    status: str

def authorize(request: Request): 
    token = request.headers.get("Authorization") 
    if token != f"Bearer {ADMIN_TOKEN}": 
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

@app.get("/") 
async def root(): 
    return {"status": "ok"}

@app.get("/api/requests") 
async def get_requests(request: Request): 
    authorize(request) 
    rows = conn.execute("SELECT id, user_id, name, phone, message, created_at, status FROM requests ORDER BY created_at DESC").fetchall() 
    return [
        {
            "id": r[0], 
            "user_id": r[1], 
            "name": r[2], 
            "phone": r[3], 
            "message": r[4], 
            "created_at": r[5], 
            "status": r[6]
        } 
        for r in rows
    ]

@app.post("/api/reply")
async def reply_user(req: ReplyRequest, request: Request):
    authorize(request)
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
    authorize(request) 
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
    <!-- Tabler Core CSS -->
    <link href="https://unpkg.com/@tabler/core@latest/dist/css/tabler.min.css" rel="stylesheet"/>
    <style>
        body { background: #f4f6fa; }
        .table-responsive { margin-top: 28px; }
        .actions .btn { margin-right: 8px; }
        .filter-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }
        .filter-row input, .filter-row select { min-width: 160px; }
    </style>
</head>
<body>
<div class="page">
    <div class="container-xl">
        <div class="page-header d-print-none mt-4 mb-2">
            <h2 class="page-title">Заявки LegalBot</h2>
        </div>
        <div class="filter-row">
            <input type="search" class="form-control" id="searchInput" placeholder="Поиск по имени или сообщению">
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
                        <th data-sort="name">Имя &#x25B2;&#x25BC;</th>
                        <th data-sort="phone">Телефон</th>
                        <th data-sort="created_at">Время &#x25B2;&#x25BC;</th>
                        <th data-sort="message">Сообщение</th>
                        <th data-sort="status">Статус</th>
                        <th>Действия</th>
                    </tr>
                </thead>
                <tbody id="reqTbody"></tbody>
            </table>
        </div>
    </div>
</div>

<!-- Модалка для ответа -->
<div class="modal modal-blur fade" id="replyModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered" role="document">
    <div class="modal-content">
      <div class="modal-header"><h5 class="modal-title">Ответ пользователю</h5></div>
      <div class="modal-body">
        <textarea id="replyMsg" class="form-control" rows="4" placeholder="Введите ответ"></textarea>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-link" onclick="closeReplyModal()">Отмена</button>
        <button type="button" class="btn btn-primary" id="replySendBtn">Отправить</button>
      </div>
    </div>
  </div>
</div>
<!-- Модалка для смены статуса -->
<div class="modal modal-blur fade" id="statusModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered" role="document">
    <div class="modal-content">
      <div class="modal-header"><h5 class="modal-title">Сменить статус</h5></div>
      <div class="modal-body">
        <select id="newStatus" class="form-select">
            <option value="new">Новая</option>
            <option value="in_work">В работе</option>
            <option value="done">Готово</option>
        </select>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-link" onclick="closeStatusModal()">Отмена</button>
        <button type="button" class="btn btn-primary" id="statusSendBtn">Сохранить</button>
      </div>
    </div>
  </div>
</div>

<!-- Bootstrap JS (ОБЯЗАТЕЛЬНО!) -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<!-- Tabler JS -->
<script src="https://unpkg.com/@tabler/core@latest/dist/js/tabler.min.js"></script>
<script>
let token = sessionStorage.getItem("adminToken");
if (!token) {
    token = prompt("Введите токен для доступа:");
    sessionStorage.setItem("adminToken", token);
}

let allData = [];
let sortField = "created_at", sortAsc = false;
let filterStatus = "", searchValue = "";
let replyUserId = null, statusUserId = null;

// --- Bootstrap modal instances ---
let replyModalInstance = null;
let statusModalInstance = null;

function statusBadge(status) {
    if (status === "done")   return '<span class="badge bg-success">Готово</span>';
    if (status === "in_work")return '<span class="badge bg-warning text-dark">В работе</span>';
    return '<span class="badge bg-purple">Новая</span>';
}

function renderTable() {
    let data = [...allData];
    // Фильтры
    if (filterStatus) data = data.filter(r => r.status === filterStatus);
    if (searchValue) {
        const v = searchValue.toLowerCase();
        data = data.filter(r => (r.name && r.name.toLowerCase().includes(v))
                        || (r.message && r.message.toLowerCase().includes(v)));
    }
    // Сортировка
    data.sort((a, b) => {
        let va = a[sortField], vb = b[sortField];
        if (sortField === "created_at") { va = va || ""; vb = vb || ""; }
        if (va === undefined) return 1;
        if (vb === undefined) return -1;
        if (va < vb) return sortAsc ? -1 : 1;
        if (va > vb) return sortAsc ? 1 : -1;
        return 0;
    });
    // Рендер
    const tbody = document.getElementById('reqTbody');
    tbody.innerHTML = "";
    data.forEach(r => {
        let tr = document.createElement('tr');
        tr.innerHTML = `
            <td><b>${r.name || ""}</b></td>
            <td>${r.phone || ""}</td>
            <td><small>${(r.created_at || '').replace('T','<br>')}</small></td>
            <td style="max-width:220px; word-break:break-word;">${r.message || ""}</td>
            <td>${statusBadge(r.status)}</td>
            <td class="actions">
                <button type="button" class="btn btn-sm btn-primary" onclick="openReplyModal(${r.user_id})">Ответить</button>
                <button type="button" class="btn btn-sm btn-outline-secondary" onclick="openStatusModal(${r.user_id},'${r.status}')">Статус</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function load() {
    document.getElementById('loader').style.display = "";
    document.getElementById('tableDiv').style.display = "none";
    const res = await fetch('/api/requests', {
        headers: { Authorization: 'Bearer ' + token }
    });
    allData = await res.json();
    document.getElementById('loader').style.display = "none";
    document.getElementById('tableDiv').style.display = "";
    renderTable();
}
// Фильтрация
document.getElementById("statusFilter").onchange = function(e) {
    filterStatus = e.target.value;
    renderTable();
};
document.getElementById("searchInput").oninput = function(e) {
    searchValue = e.target.value;
    renderTable();
};
// Сортировка
document.querySelectorAll("#reqTable th[data-sort]").forEach(th => {
    th.style.cursor = "pointer";
    th.onclick = () => {
        const field = th.getAttribute("data-sort");
        if (sortField === field) sortAsc = !sortAsc;
        else { sortField = field; sortAsc = true; }
        renderTable();
    };
});

// --- Модалки ответа ---
function openReplyModal(userId) {
    replyUserId = userId;
    document.getElementById("replyMsg").value = "";
    let elem = document.getElementById("replyModal");
    replyModalInstance = bootstrap.Modal.getOrCreateInstance(elem);
    replyModalInstance.show();
    setTimeout(() => document.getElementById("replyMsg").focus(), 200);
}
function closeReplyModal() {
    if(replyModalInstance) replyModalInstance.hide();
}
document.getElementById("replySendBtn").onclick = async function() {
    const msg = document.getElementById("replyMsg").value;
    if (msg && replyUserId) {
        await fetch('/api/reply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
            body: JSON.stringify({ user_id: replyUserId, message: msg })
        });
        closeReplyModal();
        alert("Ответ отправлен!");
        load();
    }
};
// --- Модалки статуса ---
function openStatusModal(userId, currentStatus) {
    statusUserId = userId;
    document.getElementById("newStatus").value = currentStatus || "new";
    let elem = document.getElementById("statusModal");
    statusModalInstance = bootstrap.Modal.getOrCreateInstance(elem);
    statusModalInstance.show();
}
function closeStatusModal() {
    if(statusModalInstance) statusModalInstance.hide();
}
document.getElementById("statusSendBtn").onclick = async function() {
    const status = document.getElementById("newStatus").value;
    if (status && statusUserId) {
        await fetch('/api/status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
            body: JSON.stringify({ user_id: statusUserId, status: status })
        });
        closeStatusModal();
        alert("Статус обновлён!");
        load();
    }
};

// --- Закрытие модалки при клике вне ---
window.onclick = function(event) {
    if (event.target.classList.contains("modal")) {
        closeReplyModal();
        closeStatusModal();
    }
};

load();
</script>
</body>
</html>
"""

@dp.message(lambda m: m.text == "Часто задаваемые вопросы") 
async def show_faq(message: types.Message): 
    await message.answer("Часто задаваемые вопросы пока не добавлены.")

@dp.message(lambda m: m.text == "Отправить документ") 
async def ask_document(message: types.Message): 
    await message.answer("Пожалуйста, отправьте документ (PDF, DOCX и т.д.)")

@dp.message(lambda m: m.document) 
async def handle_document(message: types.Message): 
    await message.answer("Документ получен. Спасибо!")

async def main():
    # Запускаем FastAPI (uvicorn) как фонового сервера
    # и aiogram polling в том же event loop
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, loop="asyncio", log_level="info")
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve())
    bot_task = asyncio.create_task(dp.start_polling(bot))
    await asyncio.gather(api_task, bot_task)

if __name__ == "__main__":
    asyncio.run(main())
