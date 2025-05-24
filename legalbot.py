import asyncio 
import logging 
import sqlite3 
import threading 
from datetime import datetime 
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

conn = sqlite3.connect("bot.db", check_same_thread=False) c = conn.cursor() c.execute("""CREATE TABLE IF NOT EXISTS requests ( id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, phone TEXT, message TEXT, created_at TEXT, status TEXT DEFAULT 'new')""") conn.commit()

class RequestForm(StatesGroup): name = State() phone = State() message = State()

menu_kb = ReplyKeyboardMarkup( keyboard=[ [KeyboardButton(text="Записаться на консультацию")], [KeyboardButton(text="Часто задаваемые вопросы")], [KeyboardButton(text="Отправить документ")], [KeyboardButton(text="Контакты")] ], resize_keyboard=True )

@dp.message(CommandStart()) async def start(message: types.Message): await message.answer("Добро пожаловать в LegalBot!", reply_markup=menu_kb)

@dp.message(lambda m: m.text == "Контакты") async def contacts(message: types.Message): await message.answer("г. Астрахань, ул. Татищева 20\n+7 988 600 56 61")

@dp.message(lambda m: m.text == "Записаться на консультацию") async def consultation(message: types.Message, state: FSMContext): await state.set_state(RequestForm.name) await state.update_data(user_id=message.from_user.id) await message.answer("Введите ваше имя:")

@dp.message(RequestForm.name) async def get_name(message: types.Message, state: FSMContext): await state.update_data(name=message.text) await state.set_state(RequestForm.phone) await message.answer("Введите номер телефона:")

@dp.message(RequestForm.phone) async def get_phone(message: types.Message, state: FSMContext): await state.update_data(phone=message.text) await state.set_state(RequestForm.message) await message.answer("Опишите вашу проблему:")

@dp.message(RequestForm.message) async def save_request(message: types.Message, state: FSMContext): data = await state.get_data() now = datetime.now().isoformat() with conn: conn.execute("INSERT INTO requests (user_id, name, phone, message, created_at, status) VALUES (?, ?, ?, ?, ?, ?)", (message.from_user.id, data['name'], data['phone'], message.text, now, 'new')) await bot.send_message(ADMIN_CHAT_ID, f"Новая заявка:\nИмя: {data['name']}\nТел: {data['phone']}\nПроблема: {message.text}") await message.answer("Спасибо! Мы свяжемся с вами.", reply_markup=menu_kb) await state.clear()

app = FastAPI()

class ReplyRequest(BaseModel): user_id: int message: str

class StatusRequest(BaseModel): user_id: int status: str

def authorize(request: Request): token = request.headers.get("Authorization") if token != f"Bearer {ADMIN_TOKEN}": raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

@app.get("/") async def root(): return {"status": "ok"}

@app.get("/api/requests") async def get_requests(request: Request): authorize(request) rows = conn.execute("SELECT id, user_id, name, phone, message, created_at, status FROM requests ORDER BY created_at DESC").fetchall() return [{"id": r[0], "user_id": r[1], "name": r[2], "phone": r[3], "message": r[4], "created_at": r[5], "status": r[6]} for r in rows]

@app.post("/api/reply") async def reply_user(req: ReplyRequest, request: Request): authorize(request) await bot.send_message(req.user_id, req.message) with conn: conn.execute("UPDATE requests SET status = 'done' WHERE user_id = ?", (req.user_id,)) return {"status": "sent"}

@app.post("/api/status") async def update_status(req: StatusRequest, request: Request): authorize(request) with conn: conn.execute("UPDATE requests SET status = ? WHERE user_id = ?", (req.status, req.user_id)) return {"status": "updated"}

@app.get("/admin", response_class=HTMLResponse) async def admin_html(request: Request): return """ <html> <head> <style> body { font-family: Arial, sans-serif; padding: 20px; } h2 { color: #333; } li { margin-bottom: 15px; } button { margin: 2px; } </style> </head> <body> <h2>LegalBot Admin</h2> <script> const token = prompt("Введите токен для доступа:"); async function sendReply(userId) { const msg = prompt("Ответ пользователю:"); if (msg) { await fetch('/api/reply', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token }, body: JSON.stringify({ user_id: userId, message: msg }) }); alert("Ответ отправлен!"); location.reload(); } }

async function setStatus(userId) {
    const status = prompt("Новый статус (new/in_work/done):");
    if (status) {
        await fetch('/api/status', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: 'Bearer ' + token
            },
            body: JSON.stringify({ user_id: userId, status: status })
        });
        alert("Статус обновлён!");
        location.reload();
    }
}

async function load() {
    const res = await fetch('/api/requests', {
        headers: { Authorization: 'Bearer ' + token }
    });
    const data = await res.json();
    const html = '<ul>' + data.map(r => `
        <li>
            <b>${r.name}</b> [${r.phone}] — <i>${r.status}</i><br>
            ${r.message}<br>
            <button onclick="sendReply(${r.user_id})">Ответить</button>
            <button onclick="setStatus(${r.user_id})">Изменить статус</button>
        </li>
    `).join('') + '</ul>';
    document.body.innerHTML += html;
}

load();
</script>
</body>
</html>
"""

@dp.message(lambda m: m.text == "Часто задаваемые вопросы") async def show_faq(message: types.Message): await message.answer("Часто задаваемые вопросы пока не добавлены.")

@dp.message(lambda m: m.text == "Отправить документ") async def ask_document(message: types.Message): await message.answer("Пожалуйста, отправьте документ (PDF, DOCX и т.д.)")

@dp.message(lambda m: m.document) async def handle_document(message: types.Message): await message.answer("Документ получен. Спасибо!")

def run_web(): uvicorn.run(app, host="0.0.0.0", port=8000)

if name == "main": threading.Thread(target=run_web, daemon=True).start() asyncio.run(dp.start_polling(bot))

