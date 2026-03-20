"""
bot.py — Мультитенантный Telegram бот на aiogram
Один бот — много бизнесов. Каждый бизнес получает свою ссылку.
"""

import json
import logging
import asyncio
import httpx
from pathlib import Path
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from dotenv import load_dotenv
import os
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

load_dotenv()

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
_DB = Path(__file__).parent / "data" / "businesses.json"

def load_businesses() -> dict:
    with open(_DB, "r", encoding="utf-8") as f:
        businesses = json.load(f)
    return {b["id"]: b for b in businesses}

def save_lead(business_id: str, business_name: str, name: str, phone: str):
    leads_db = Path(__file__).parent / "data" / "leads.json"
    leads = []
    if leads_db.exists():
        with open(leads_db, "r", encoding="utf-8") as f:
            try:
                leads = json.load(f)
            except json.JSONDecodeError:
                pass
                
    leads.append({
        "business_id": business_id,
        "business_name": business_name,
        "name": name,
        "phone": phone
    })
    
    with open(leads_db, "w", encoding="utf-8") as f:
        json.dump(leads, f, ensure_ascii=False, indent=4)

async def ask_deepseek(business_prompt: str, history: list, user_message: str) -> str:


    messages = [{"role": "system", "content": business_prompt}] + history + [{"role": "user", "content": user_message}]
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            json={
                "model": "deepseek-chat",
                "messages": messages,
                "temperature": 0.5,
                "max_tokens": 500,
            }
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

sessions: dict = {}

def get_session(user_id: int) -> dict:
    if user_id not in sessions:
        sessions[user_id] = {
            "business_id": None,
            "history": [],
            "collecting": False,
            "data": {}
        }
    return sessions[user_id]

bot = Bot(token=TELEGRAM_TOKEN)
dp  = Dispatcher()

@dp.message(CommandStart())
async def start(message: Message):
    user_id  = message.from_user.id
    session  = get_session(user_id)
    args     = message.text.split()

    if len(args) < 2:
        await message.answer("Привет! Перейди по ссылке от бизнеса чтобы начать.")
        return

    business_id = args[1]
    businesses  = load_businesses()

    if business_id not in businesses:
        await message.answer("Бизнес не найден. Проверь ссылку.")
        return

    session["business_id"] = business_id
    session["history"]     = []
    session["collecting"]  = False
    session["data"]        = {}

    business = businesses[business_id]
    await message.answer(f"Привет! Я консультант — {business['name']}.\nЧем могу помочь?")

@dp.message(F.text)
async def handle_message(message: Message):
    user_id  = message.from_user.id
    text     = message.text
    session  = get_session(user_id)

    if not session["business_id"]:
        await message.answer("Перейди по ссылке от бизнеса чтобы начать.")
        return

    businesses = load_businesses()
    business   = businesses[session["business_id"]]

    if session["collecting"] == "name":
        if text.lower() in ["стоп", "отмена", "нет", "не", "потом"]:
            session["collecting"] = False
            return await message.answer("Понял вас! Оформление отменено. Возвращаемся к разговору 😊 Чем еще могу помочь?")
            
        session["data"]["name"] = text
        session["collecting"]   = "phone"
        await message.answer("Отлично! Теперь напишите ваш номер телефона:")
        return

    if session["collecting"] == "phone":
        if text.lower() in ["стоп", "отмена", "нет", "не", "потом"]:
            session["collecting"] = False
            return await message.answer("Понял вас! Оформление отменено. Возвращаемся к разговору 😊 Чем еще могу помочь?")
            
        session["data"]["phone"] = text
        session["collecting"]    = "time"
        await message.answer("Супер! И последний вопрос: на какое время или дату вы хотели бы записаться?")
        return

    if session["collecting"] == "time":
        if text.lower() in ["стоп", "отмена", "нет", "не", "потом"]:
            session["collecting"] = False
            return await message.answer("Понял вас! Оформление отменено. Возвращаемся к разговору 😊 Чем еще могу помочь?")
            
        session["data"]["time"] = text
        session["collecting"]    = False
        name  = session["data"].get("name", "—")
        phone = session["data"].get("phone", "—")
        time_pref = session["data"].get("time", "—")
        
        log.info(f"Новый клиент: {name} | {phone} | {time_pref} | {business['name']}")
        save_lead(business["id"], business["name"], name, phone)
        
        await bot.send_chat_action(message.chat.id, "typing")
        
        # --- SEND TO GOOGLE SHEETS ---
        spreadsheet_id = business.get("spreadsheet_id")
        if spreadsheet_id:
            try:
                credentials_file = Path(__file__).parent / "credentials.json"
                scopes = [
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive"
                ]
                creds = Credentials.from_service_account_file(credentials_file, scopes=scopes)
                client = gspread.authorize(creds)
                
                sheet = client.open_by_key(spreadsheet_id).sheet1
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Записываем: Дата создания заявки, Имя, Телефон, Время записи
                sheet.append_row([current_time, name, phone, time_pref])
            except Exception as e:
                log.error(f"Не удалось записать в Google Sheets: {e}")
        # -----------------------------
        
        await message.answer(
            "✅ Готово! Ваши данные успешно записаны.\n"
            "Владелец свяжется с вами в ближайшее время для подтверждения."
        )
        return

    await bot.send_chat_action(message.chat.id, "typing")

    full_prompt = business["prompt"] + """

ВАЖНО: Если клиент явно говорит что хочет заказать, записаться или купить —
в конце ответа добавь ровно одну строку: READY_TO_COLLECT
Больше ничего не добавляй после этой строки."""

    try:
        reply = await ask_deepseek(full_prompt, session["history"], text)
    except Exception as e:
        log.error(f"DeepSeek ошибка: {e}")
        await message.answer("Что-то пошло не так, попробуй ещё раз.")
        return

    if "READY_TO_COLLECT" in reply:
        reply = reply.replace("READY_TO_COLLECT", "").strip()
        session["collecting"] = "name"
        await message.answer(reply)
        await message.answer("Напишите ваше имя:")
    else:
        await message.answer(reply)

    session["history"].append({"role": "user",      "content": text})
    session["history"].append({"role": "assistant",  "content": reply})
    
    # Ограничиваем историю (оставляем последние 10 сообщений, чтобы не выйти за лимиты токенов)
    if len(session["history"]) > 10:
        session["history"] = session["history"][-10:]

async def main():
    log.info("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())