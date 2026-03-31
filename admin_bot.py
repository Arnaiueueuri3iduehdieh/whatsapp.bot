import json
import logging
import asyncio
import os
import uuid
import string
from pathlib import Path
import httpx
import gspread
from google.oauth2.credentials import Credentials
import database as db

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

load_dotenv()

ADMIN_TOKEN        = os.getenv("ADMIN_BOT_TOKEN")
ADMIN_TELEGRAM_ID  = os.getenv("ADMIN_TELEGRAM_ID")
CLIENT_BOT_USERNAME = os.getenv("CLIENT_BOT_USERNAME", "YourClientBot").strip()
ADMIN_EMAIL        = os.getenv("ADMIN_EMAIL", "").strip()
GROQ_API_KEY       = os.getenv("GROQ_API_KEY")  # ← Groq Cloud

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()
GROQ_MODEL   = "llama-3.3-70b-versatile"  # Высокопроизводительная и актуальная модель Groq Cloud

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


class AddBusiness(StatesGroup):
    waiting_for_desc = State()
    waiting_for_owner_email = State()

class UpdateKnowledge(StatesGroup):
    waiting_for_business = State()
    waiting_for_info     = State()
    waiting_for_save_choice = State()


bot = Bot(token=ADMIN_TOKEN)
dp  = Dispatcher()


def is_admin(user_id: int) -> bool:
    if not ADMIN_TELEGRAM_ID:
        log.warning("ADMIN_TELEGRAM_ID is not set in .env! Access denied by default.")
        return False
    return str(user_id) == str(ADMIN_TELEGRAM_ID)


async def ask_groq(system_prompt: str, user_message: str) -> str:
    """Отправляет запрос к Groq Cloud и возвращает ответ модели."""
    log.info(f"Connecting to Groq API: {GROQ_API_URL}")
    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
                "temperature": 0.3,
                "max_tokens": 1000,
            },
        )
    if resp.status_code != 200:
        log.error(f"Groq API Error: {resp.text}")
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


@dp.message(CommandStart())
async def start_admin(message: Message, state: FSMContext):
    await state.clear()
    if not is_admin(message.from_user.id):
        return await message.answer("У вас нет прав администратора.")

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить бизнес"), KeyboardButton(text="📋 Мои бизнесы")],
            [KeyboardButton(text="📚 База знаний / Прайсы")]
        ],
        resize_keyboard=True,
    )

    await message.answer(
        "👋 Привет, Админ!\n\n"
        "Доступные команды:\n"
        "➕ /add — ИИ автоматически создаст промпт и Google-таблицу для нового бизнеса!\n"
        "📋 /list — посмотреть список бизнесов\n\n"
        "👇 Либо используйте кнопки внизу экрана!",
        reply_markup=kb,
    )


@dp.message(Command("add"))
@dp.message(F.text == "➕ Добавить бизнес")
async def add_business_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AddBusiness.waiting_for_desc)
    await message.answer(
        "Опишите бизнес вашего заказчика и скажите, какие данные нужно собирать у клиента.\n\n"
        "Пример:\n"
        "'Студия маникюра Пилочка. Нужно собирать имя, телефон и удобное время, а также предлагать наращивание ногтей.'",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)
    )


@dp.message(AddBusiness.waiting_for_desc)
async def process_desc(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await start_admin(message, state)

    desc = message.text
    msg  = await message.answer("⏳ Анализирую запрос, прошу ИИ (Groq) сгенерировать правила общения...")

    sys_prompt = """Ты - эксперт по бизнесу. Тебе дадут описание бизнеса заказчика.
Твоя задача сгенерировать идеальный промпт для телеграм бота-переговорщика и список полей, которые бот должен узнать у клиента.
Отправь ответ СТРОГО в формате JSON без markdown:
{
  "name": "Название бизнеса (до 30 символов)",
  "prompt": "Ты приветливый менеджер... (тут инструкция для бота, как отвечать, какие тоны использовать)",
  "fields": ["Имя клиента", "Телефон", "Удобная дата", "Какое-то еще поле"]
}"""

    # 1. Запрос к Groq Cloud
    try:
        ai_setup_raw = await ask_groq(sys_prompt, desc)

        if "```json" in ai_setup_raw:
            ai_setup_raw = ai_setup_raw.split("```json")[-1].split("```")[0].strip()
        if "```" in ai_setup_raw:
            ai_setup_raw = ai_setup_raw.replace("```", "").strip()

        ai_setup = json.loads(ai_setup_raw)
        
        # Сохраняем временные данные
        await state.update_data(
            name=ai_setup.get("name", "Новый бизнес"),
            prompt=ai_setup.get("prompt", "Вы помощник."),
            fields=ai_setup.get("fields", ["Имя", "Телефон"])
        )
        
        await state.set_state(AddBusiness.waiting_for_owner_email)
        await msg.edit_text(
            f"✅ ИИ подготовил настройки для бизнеса: **{ai_setup.get('name')}**\n\n"
            "📥 **Теперь введите Gmail владельца бизнеса.**\n"
            "На эту почту будет выслан доступ к Google Таблице с заявками."
        )

    except Exception as e:
        log.error(f"Groq Config Error: {e}")
        await msg.edit_text(
            f"❌ Ошибка ИИ. Попробуйте еще раз.\nОшибка: {str(e)[:100]}"
        )
        await state.clear()
        return

@dp.message(AddBusiness.waiting_for_owner_email)
async def process_owner_email(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await start_admin(message, state)

    owner_email = message.text.strip().lower()
    if "@" not in owner_email or "." not in owner_email:
        return await message.answer("Пожалуйста, введите корректный Email (например, example@gmail.com)")

    data = await state.get_data()
    name = data['name']
    prompt = data['prompt']
    fields = data['fields']
    
    msg = await message.answer("⏳ Создаю Google Таблицу и настраиваю доступы...")
    business_id = str(uuid.uuid4())[:8]

    # 2. Создаём Google Sheet автоматически
    try:
        token_file = Path(__file__).parent / "token.json"
        if not token_file.exists():
            raise FileNotFoundError("token.json not found.")
        
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds    = Credentials.from_authorized_user_file(token_file, scopes=scopes)
        g_client = gspread.authorize(creds)

        if GOOGLE_DRIVE_FOLDER_ID:
            spreadsheet = g_client.create(f"Заявки: {name} ({business_id})", folder_id=GOOGLE_DRIVE_FOLDER_ID)
        else:
            spreadsheet = g_client.create(f"Заявки: {name} ({business_id})")

        # Даем доступ админу (тебе)
        if ADMIN_EMAIL:
            try:
                spreadsheet.share(ADMIN_EMAIL, perm_type="user", role="writer")
            except: pass

        # Даем доступ ВЛАДЕЛЬЦУ
        try:
            spreadsheet.share(owner_email, perm_type="user", role="writer")
            share_success = True
        except Exception as share_err:
            log.warning(f"Не удалось расшарить на {owner_email}: {share_err}")
            share_success = False

        worksheet = spreadsheet.sheet1
        headers   = ["Дата создания записи"] + fields
        last_col  = string.ascii_uppercase[min(len(headers) - 1, 25)]
        worksheet.update([headers], f"A1:{last_col}1")
        worksheet.format(f"A1:{last_col}1", {"textFormat": {"bold": True}})

        spreadsheet_id = spreadsheet.id
        sheet_url      = spreadsheet.url

    except Exception as e:
        log.error(f"Google Sheets API Error: {e}")
        await msg.edit_text(f"❌ Ошибка Google Таблиц: {str(e)[:100]}")
        await state.clear()
        return

    # 3. Сохраняем в SQLite
    db.save_business(
        id=business_id,
        name=name,
        prompt=prompt,
        fields=fields,
        spreadsheet_id=spreadsheet_id,
        spreadsheet_url=sheet_url,
        owner_email=owner_email
    )

    await state.clear()
    link = f"https://t.me/{CLIENT_BOT_USERNAME}?start={business_id}"

    share_text = f"✅ Доступ выдан на: {owner_email}" if share_success else f"⚠️ Не удалось выдать доступ на {owner_email} (проверьте email)"

    await msg.edit_text(
        f"🌟 **Бизнес успешно настроен!**\n\n"
        f"🏢 **Название:** {name}\n"
        f"📧 **Владелец:** {owner_email}\n"
        f"🔗 **Ссылка для клиентов:**\n**{link}**\n\n"
        f"📊 **Таблица с заявками:**\n**{sheet_url}**\n\n"
        f"{share_text}"
    )


@dp.message(Command("list"))
@dp.message(F.text == "📋 Мои бизнесы")
async def list_businesses(message: Message):
    if not is_admin(message.from_user.id):
        return
    businesses = db.get_all_businesses()
    if not businesses:
        return await message.answer("Бизнесов пока нет!")

    text = "📋 **Ваши бизнесы:**\n\n"
    for b in businesses:
        link  = f"https://t.me/{CLIENT_BOT_USERNAME}?start={b['id']}"
        text += f"🏢 **{b.get('name', 'Без имени')}**\n🔗 {link}\n📑 Таблица: {b.get('spreadsheet_url', '-')}\n\n"
    await message.answer(text)


@dp.message(F.text == "📚 База знаний / Прайсы")
async def update_knowledge_list(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    businesses = db.get_all_businesses()
    if not businesses:
        return await message.answer("Бизнесов пока нет!")

    # Кнопки с именами бизнесов
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=f"🏢 {b['name']} (ID: {b['id']})")] for b in businesses] + [[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )
    await state.set_state(UpdateKnowledge.waiting_for_business)
    await message.answer("Выберите бизнес по названию, чтобы обновить или дополнить его Базу знаний:", reply_markup=kb)


@dp.message(UpdateKnowledge.waiting_for_business)
async def process_business_selection(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await start_admin(message)

    try:
        # Извлекаем ID из строки "ИМЯ (ID: XXX)"
        b_id = message.text.split("(ID: ")[1].split(")")[0]
        await state.update_data(business_id=b_id)
        
        business = db.get_business(b_id)
        current_k = business.get("knowledge", "") or "Пусто (бот ничего не знает про этот бизнес)"
        
        await state.set_state(UpdateKnowledge.waiting_for_info)
        await message.answer(
            f"🎯 **Выбран бизнес: {business['name']}**\n\n"
            f"📜 **Текущая база знаний:**\n_{current_k}_\n\n"
            f"📥 **Теперь просто пришлите текст (цены, услуги, FAQ).**\n"
            f"Я спрошу вас: дописать это к уже имеющимся данным или заменить всё полностью.",
            reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)
        )
    except:
        await message.answer("Пожалуйста, выберите бизнес из кнопок ниже.")


@dp.message(UpdateKnowledge.waiting_for_info)
async def process_new_knowledge_input(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        return await start_admin(message)

    await state.update_data(new_text=message.text)
    await state.set_state(UpdateKnowledge.waiting_for_save_choice)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить (дописать к старым)")],
            [KeyboardButton(text="📝 Заменить (стереть старые и записать эти)")],
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True
    )
    await message.answer("Как сохранить эти данные?", reply_markup=kb)


@dp.message(UpdateKnowledge.waiting_for_save_choice, F.text.in_(["➕ Добавить (дописать к старым)", "📝 Заменить (стереть старые и записать эти)"]))
async def save_knowledge_choice(message: Message, state: FSMContext):
    data = await state.get_data()
    b_id = data.get("business_id")
    new_input = data.get("new_text")
    
    if not b_id or not new_input:
        await state.clear()
        return await start_admin(message)
    
    business = db.get_business(b_id)
    old_k = business.get("knowledge", "") or ""
    
    if "Добавить" in message.text:
        final_knowledge = (old_k + "\n\n" + new_input).strip()
    else:
        final_knowledge = new_input.strip()

    # Сохраняем в БД
    conn = db.sqlite3.connect(db.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE businesses SET knowledge = ? WHERE id = ?", (final_knowledge, b_id))
    conn.commit()
    conn.close()

    await state.clear()
    await message.answer(
        f"✅ **Успешно! Обновлено.**\n\n"
        f"📊 **Итоговая база знаний для {business['name']}:**\n_{final_knowledge}_"
    )
    await start_admin(message)


async def main():
    db.init_db()
    log.info("Admin Bot запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())