import json
import logging
import asyncio
import os
import uuid
import re
from pathlib import Path
import gspread
from google.oauth2.service_account import Credentials

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

load_dotenv()

ADMIN_TOKEN = os.getenv("ADMIN_BOT_TOKEN")  # Берем из твоего .env
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")
CLIENT_BOT_USERNAME = os.getenv("CLIENT_BOT_USERNAME", "YourClientBot") # Используется для генерации ссылки на бота
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

_DB = Path(__file__).parent / "data" / "businesses.json"

class AddBusiness(StatesGroup):
    waiting_for_name = State()
    waiting_for_prompt = State()
    waiting_for_sheet = State()

class EditBusiness(StatesGroup):
    waiting_for_id = State()
    waiting_for_new_prompt = State()

def load_businesses() -> list:
    if not _DB.exists():
        return []
    with open(_DB, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def save_businesses(businesses: list):
    _DB.parent.mkdir(parents=True, exist_ok=True)
    with open(_DB, "w", encoding="utf-8") as f:
        json.dump(businesses, f, ensure_ascii=False, indent=4)

if not ADMIN_TOKEN:
    raise ValueError("ADMIN_BOT_TOKEN не найден в .env. Добавь его для запуска!")

bot = Bot(token=ADMIN_TOKEN)
dp = Dispatcher()

# Фильтр для проверки прав админа
def is_admin(user_id: int) -> bool:
    if not ADMIN_TELEGRAM_ID:
        return True
    return str(user_id) == str(ADMIN_TELEGRAM_ID)

@dp.message(CommandStart())
async def start_admin(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("У вас нет прав администратора.")
        
    await message.answer(
        "👋 Привет, Админ!\n\n"
        "Доступные команды:\n"
        "➕ /add — добавить новый бизнес/клиента\n"
        "📋 /list — посмотреть список всех бизнесов\n"
        "✏️ /edit — изменить базу знаний (прайс, правила) у бизнеса"
    )

@dp.message(Command("add"))
async def add_business_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
        
    await state.set_state(AddBusiness.waiting_for_name)
    await message.answer("✍️ Введи название нового бота/бизнеса (например, 'Автосервис Макс'):")

@dp.message(AddBusiness.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AddBusiness.waiting_for_prompt)
    await message.answer(
        "Отлично! Теперь отправь **системный промпт** (инструкцию для ИИ):\n\n" 
        "📝 Пример: 'Ты опытный менеджер автосервиса. Общайся вежливо, предлагай запись на ремонт, отвечай кратко.'"
    )

@dp.message(AddBusiness.waiting_for_prompt)
async def process_prompt(message: Message, state: FSMContext):
    await state.update_data(prompt=message.text)
    
    # Теперь просим ссылку
    await state.set_state(AddBusiness.waiting_for_sheet)
    
    # Читаем почту бота из credentials.json для удобства
    try:
        import json
        creds_path = Path(__file__).parent / "credentials.json"
        with open(creds_path, "r", encoding="utf-8") as f:
            creds_data = json.load(f)
            bot_email = creds_data.get("client_email", "почте_из_файла_credentials")
    except Exception:
        bot_email = "почте твоего сервисного аккаунта"
        
    await message.answer(
        f"📝 Промпт сохранен!\n\n"
        f"Так как бесплатные аккаунты Google запрещают ботам создавать файлы, нам нужно сделать это вручную:\n\n"
        f"1. Создай пустую Google Таблицу на своем диске.\n"
        f"2. Нажми 'Поделиться' и дай доступ (как Редактору) вот этой почте бота:\n"
        f"`{bot_email}`\n\n"
        f"3. Скопируй **ссылку на эту таблицу** и пришли её мне сюда:"
    )

@dp.message(AddBusiness.waiting_for_sheet)
async def process_sheet(message: Message, state: FSMContext):
    sheet_url = message.text
    
    # Извлекаем ID таблицы из ссылки
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", sheet_url)
    if not match:
        await message.answer("❌ Это не похоже на ссылку на Google Таблицу (в ней нет /d/.../). Скопируй ссылку из браузера и попробуй еще раз.")
        return
        
    spreadsheet_id = match.group(1)
    data = await state.get_data()
    name = data["name"]
    prompt = data["prompt"]
    
    business_id = str(uuid.uuid4())[:8] 
    
    msg = await message.answer("⏳ Проверяю доступ к таблице...")
    try:
        credentials_file = Path(__file__).parent / "credentials.json"
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_file(credentials_file, scopes=scopes)
        client = gspread.authorize(creds)
        
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.sheet1
        
        # Форматируем заголовки
        worksheet.update([['Дата записи', 'Имя', 'Телефон', 'Желаемое время', ]], 'A1:D1')
        worksheet.format("A1:D1", {"textFormat": {"bold": True}})
        
        await msg.delete()
    except Exception as e:
        log.error(f"Google Sheets API Error: {e}")
        await message.answer(f"❌ Ошибка доступа. Ты точно нажал 'Поделиться' и выдал права редактора почте бота?\nТекст ошибки: {e}")
        return
    
    new_business = {
        "id": business_id,
        "name": name,
        "prompt": prompt,
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_url": sheet_url
    }
    
    businesses = load_businesses()
    businesses.append(new_business)
    save_businesses(businesses)
    
    await state.clear()
    
    # Формируем диплинк
    link = f"https://t.me/{CLIENT_BOT_USERNAME}?start={business_id}"
    
    await message.answer(
        f"✅ Бизнес **{name}** успешно добавлен!\n\n"
        f"🔗 **Ссылка для клиентов** (скинь её заказчику):\n"
        f"**{link}**"
    )

@dp.message(Command("list"))
async def list_businesses(message: Message):
    if not is_admin(message.from_user.id):
        return
        
    businesses = load_businesses()
    if not businesses:
        await message.answer("Упс! В базе пока нет ни одного бизнеса.")
        return
    
    text = "📋 **Список ваших бизнесов:**\n\n"
    for b in businesses:
        link = f"https://t.me/{CLIENT_BOT_USERNAME}?start={b['id']}"
        text += f"🏢 **{b['name']}**\n🔑 ID: `{b['id']}`\n🔗 Ссылка: {link}\n\n"
    await message.answer(text)

@dp.message(Command("edit"))
async def edit_business_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(EditBusiness.waiting_for_id)
    await message.answer("Введи 🔑 ID бизнеса, которому нужно обновить инструкцию (базу знаний/прайсы):")

@dp.message(EditBusiness.waiting_for_id)
async def process_edit_id(message: Message, state: FSMContext):
    business_id = message.text.strip()
    businesses = load_businesses()
    
    business_exists = False
    for b in businesses:
        if b["id"] == business_id:
            business_exists = True
            break
            
    if not business_exists:
        await message.answer("❌ Бизнес с таким ID не найден. Напиши правильный ID.")
        return
        
    await state.update_data(business_id=business_id)
    await state.set_state(EditBusiness.waiting_for_new_prompt)
    await message.answer(
        "✅ Бизнес найден! Теперь отправь **новую Базу Знаний** целиком одним сообщением.\n\n"
        "Сюда можно вписать огромный текст (до 4000 символов):\n"
        "- Цены на услуги\n"
        "- Адрес и часы работы\n"
        "- FAQ (ответы на частые вопросы)\n"
        "- Инструкцию для ИИ: как общаться и **когда выдавать слово READY_TO_COLLECT**."
    )

@dp.message(EditBusiness.waiting_for_new_prompt)
async def process_edit_prompt(message: Message, state: FSMContext):
    data = await state.get_data()
    business_id = data["business_id"]
    new_prompt = message.text
    
    businesses = load_businesses()
    for b in businesses:
        if b["id"] == business_id:
            b["prompt"] = new_prompt
            break
            
    save_businesses(businesses)
    await state.clear()
    
    await message.answer("🎉 База знаний успешно обновлена! Нейросеть уже работает по новому сценарию.")

async def main():
    log.info("Ожидание обновлений админ-бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
