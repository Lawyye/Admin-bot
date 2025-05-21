# telegram_bot_final_combined.py
# Telegram-бот + FastAPI + Web UI + API с авторизацией + Заявки + Админка

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
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import uvicorn

API_TOKEN = os.getenv("API_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "secure-token-123")

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

logging.basicConfig(level=logging.INFO)

conn = sqlite3.connect("bot.db", check_same_thread=False)
c = conn.cursor()
c.execute("CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, message TEXT, created_at TEXT, status TEXT DEFAULT 'new')")
conn.commit()

class RequestForm(StatesGroup):
    name = State()
    phone = State()
    message = State()

menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Записаться на консультацию")],
        [KeyboardButton(text="Контакты")]
    ],
    resize_keyboard=True
)

@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer("Добро пожаловать в LegalBot!", reply_markup=menu_kb)

@dp.message(lambda m: m.text == "Контакты")
async def contacts(message: types.Message):
    await message.answer("г. Астрахань, ул. Татищева 20\n+7 988 600 56 61")

@dp.message(lambda m: m.text == "Записаться на консультацию")
async def consultation(message: types.Message, state: FSMContext):
    await state.set_state(RequestForm.name)
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
    now = datetime.now().isoformat()
    c.execute("INSERT INTO requests (name, phone, message, created_at, status) VALUES (?, ?, ?, ?, ?)",
              (data['name'], data['phone'], message.text, now, 'new'))
    conn.commit()
    await bot.send_message(ADMIN_CHAT_ID, f"Новая заявка:\nИмя: {data['name']}\nТел: {data['phone']}\nПроблема: {message.text}")
    await message.answer("Спасибо! Мы свяжемся с вами.", reply_markup=menu_kb)
    await state.clear()

# --- FastAPI ---
app = FastAPI()

class ReplyRequest(BaseModel):
    user_id: int
    message: str

def authorize(request: Request):
    token = request.headers.get("Authorization")
    if token != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

@app.get("/api/requests")
async def get_requests(_: Request = Depends(authorize)):
    rows = c.execute("SELECT id, name, phone, message, created_at, status FROM requests ORDER BY created_at DESC").fetchall()
    return [{"id": r[0], "name": r[1], "phone": r[2], "message": r[3], "created_at": r[4], "status": r[5]} for r in rows]

@app.post("/api/reply")
async def reply_user(req: ReplyRequest, _: Request = Depends(authorize)):
    await bot.send_message(req.user_id, req.message)
    c.execute("UPDATE requests SET status = 'done' WHERE id = ?", (req.user_id,))
    conn.commit()
    return {"status": "sent"}

@app.get("/admin", response_class=HTMLResponse)
async def admin_html():
    return """
    <html><body>
    <h2>LegalBot Admin</h2>
    <script>
    async function load() {
        const token = prompt("Token:");
        const res = await fetch('/api/requests', {headers: {Authorization: 'Bearer ' + token}});
        const data = await res.json();
        document.body.innerHTML += '<ul>' + data.map(r => `<li><b>${r.name}</b>: ${r.message}</li>`).join('') + '</ul>';
    }
    load();
    </script>
    </body></html>
    """

def run_web():
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    asyncio.run(dp.start_polling(bot))
