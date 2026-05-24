import os
import asyncio
import aiohttp
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from timezonefinder import TimezoneFinder

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')

if not TOKEN:
    exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher()
tf = TimezoneFinder()
scheduler = AsyncIOScheduler()

API_URL = "https://api.jolpi.ca/ergast/f1"
DB_PATH = "f1_users.db"
LAST_NOTIFIED_RACE = ""

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                tz TEXT DEFAULT 'Europe/Moscow'
            )
        """)
        conn.commit()

def upsert_user(chat_id: int, tz: str = "Europe/Moscow"):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO users(chat_id, tz) VALUES(?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET tz = excluded.tz
        """, (chat_id, tz))
        conn.commit()

def get_user_tz(chat_id: int) -> str:
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT tz FROM users WHERE chat_id=?", (chat_id,))
        row = c.fetchone()
        return row[0] if row else "Europe/Moscow"

def get_all_users():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT chat_id FROM users")
        return [row[0] for row in c.fetchall()]

async def fetch_f1_data(endpoint: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/{endpoint}.json", timeout=10) as response:
            if response.status == 200:
                return await response.json()
            return None

def get_reply_keyboard():
    keyboard = [
        [KeyboardButton(text="📅 Ближайший этап"), KeyboardButton(text="🏁 Последняя гонка")],
        [KeyboardButton(text="🏆 Личный зачет"), KeyboardButton(text="🏎 Кубок конструкторов")],
        [KeyboardButton(text="📊 Сравнение телеметрии"), KeyboardButton(text="⚙️ Настройки времени")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_tz_keyboard():
    keyboard = [
        [KeyboardButton(text="📍 Определить по геопозиции", request_location=True)],
        [KeyboardButton(text="⬅️ В главное меню")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def format_f1_time(date_str: str, time_str: str, user_tz: str) -> str:
    if not time_str:
        return date_str
    try:
        dt_str = f"{date_str} {time_str}"
        dt_utc = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC"))
        dt_local = dt_utc.astimezone(ZoneInfo(user_tz))
        return dt_local.strftime("%d.%m в %H:%M")
    except ValueError:
        return f"{date_str} {time_str}"

async def check_race_reminders():
    global LAST_NOTIFIED_RACE
    data = await fetch_f1_data("current/next")
    
    if not data:
        return

    try:
        race = data['MRData']['RaceTable']['Races'][0]
        race_id = race.get('round')
        
        if LAST_NOTIFIED_RACE == race_id:
            return

        date_str = race['date']
        time_str = race.get('time', '')
        if not time_str:
            return

        dt_str = f"{date_str} {time_str}"
        dt_utc = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC"))
        now_utc = datetime.now(ZoneInfo("UTC"))
        
        time_diff = dt_utc - now_utc
        
        if timedelta(minutes=0) < time_diff <= timedelta(minutes=65):
            LAST_NOTIFIED_RACE = race_id
            users = get_all_users()
            
            for chat_id in users:
                try:
                    await bot.send_message(
                        chat_id, 
                        f"🚨 *Внимание!*\nГонка *{race['raceName']}* стартует менее чем через час!",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
    except (KeyError, IndexError):
        pass

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    upsert_user(message.chat.id)
    welcome_text = (
        "Привет, фанат автоспорта! 🏎💨\n\n"
        "Я — бот-помощник по Формуле-1. Я подключен к живой базе данных и знаю всё о текущем сезоне.\n"
        "Используй кнопки внизу экрана для навигации!"
    )
    await message.answer(welcome_text, reply_markup=get_reply_keyboard())

@dp.message(F.text == '⚙️ Настройки времени')
async def settings_menu(message: types.Message):
    user_tz = get_user_tz(message.chat.id)
    text = (
        f"Твой текущий часовой пояс: `{user_tz}`\n\n"
        "Ты можешь установить его двумя способами:\n"
        "1. Нажать кнопку *Определить по геопозиции* внизу\n"
        "2. Ввести вручную командой: `/settz Europe/London`"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=get_tz_keyboard())

@dp.message(F.text == '⬅️ В главное меню')
async def back_to_main(message: types.Message):
    await message.answer("Главное меню:", reply_markup=get_reply_keyboard())

@dp.message(F.location)
async def handle_location(message: types.Message):
    lat = message.location.latitude
    lon = message.location.longitude
    
    tz_name = tf.timezone_at(lng=lon, lat=lat)
    
    if tz_name:
        upsert_user(message.chat.id, tz_name)
        await message.answer(
            f"✅ Часовой пояс успешно обновлен на `{tz_name}`!", 
            parse_mode="Markdown",
            reply_markup=get_reply_keyboard()
        )
    else:
        await message.answer("❌ Не удалось определить часовой пояс по этим координатам.")

@dp.message(Command("settz"))
async def set_tz_manual(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Формат команды: `/settz Europe/Moscow`", parse_mode="Markdown")
        return
        
    tz_name = parts[1]
    try:
        ZoneInfo(tz_name)
        upsert_user(message.chat.id, tz_name)
        await message.answer(f"✅ Часовой пояс установлен на `{tz_name}`!", parse_mode="Markdown")
    except Exception:
        await message.answer("❌ Неверный формат часового пояса. Пример: `Europe/London`", parse_mode="Markdown")

@dp.message(F.text == '📅 Ближайший этап')
async def process_next_race(message: types.Message):
    tmp_msg = await message.answer("🔄 Загружаю актуальное расписание...")
    data = await fetch_f1_data("current/next")
    
    if not data:
        await tmp_msg.edit_text("❌ Ошибка получения данных от API.")
        return

    try:
        race = data['MRData']['RaceTable']['Races'][0]
        race_name = race['raceName']
        circuit = race['Circuit']['circuitName']
        user_tz = get_user_tz(message.chat.id)
        
        schedule_text = ""
        sessions = [
            ('FirstPractice', '🏎 Практика 1'),
            ('SecondPractice', '🏎 Практика 2'),
            ('ThirdPractice', '🏎 Практика 3'),
            ('Qualifying', '⏱ Квалификация'),
            ('Sprint', '🔥 Спринт')
        ]
        
        for key, name in sessions:
            if key in race:
                dt = format_f1_time(race[key]['date'], race[key].get('time', ''), user_tz)
                schedule_text += f"{name}: {dt}\n"
                
        race_dt = format_f1_time(race['date'], race.get('time', ''), user_tz)
        
        text = (
            f"📅 *Ближайший уик-энд: {race_name}*\n"
            f"📍 Трасса: {circuit}\n\n"
            f"*Расписание сессий:*\n"
            f"{schedule_text}"
            f"🏁 *Гонка: {race_dt}*\n\n"
            f"_(Время: {user_tz})_"
        )
    except (KeyError, IndexError):
        text = "🤷‍♂️ Не удалось распарсить данные о следующей гонке. Возможно, сезон окончен."
        
    await tmp_msg.edit_text(text, parse_mode="Markdown")

@dp.message(F.text == '🏁 Последняя гонка')
async def process_last_race(message: types.Message):
    tmp_msg = await message.answer("🔄 Загружаю результаты...")
    data = await fetch_f1_data("current/last/results")
    
    if not data:
        await tmp_msg.edit_text("❌ Ошибка получения данных.")
        return

    try:
        race = data['MRData']['RaceTable']['Races'][0]
        race_name = race['raceName']
        results = race['Results'][:5]
        
        text = f"🏁 *Итоги: {race_name}*\n\n"
        for res in results:
            pos = res['position']
            driver = res['Driver']['familyName']
            team = res['Constructor']['name']
            points = res['points']
            text += f"{pos}. {driver} ({team}) — {points} очков\n"
    except (KeyError, IndexError):
        text = "🤷‍♂️ Не удалось загрузить результаты."
        
    await tmp_msg.edit_text(text, parse_mode="Markdown")

@dp.message(F.text == '🏆 Личный зачет')
async def process_drivers(message: types.Message):
    tmp_msg = await message.answer("🔄 Загружаю таблицу...")
    data = await fetch_f1_data("current/driverStandings")
    
    if not data:
        await tmp_msg.edit_text("❌ Ошибка получения данных.")
        return

    try:
        standings = data['MRData']['StandingsTable']['StandingsLists'][0]['DriverStandings'][:10]
        
        text = "🏆 *Личный зачет (Топ-10):*\n\n"
        for driver in standings:
            pos = driver['position']
            name = driver['Driver']['familyName']
            points = driver['points']
            text += f"{pos}. {name} — {points} очков\n"
    except (KeyError, IndexError):
        text = "🤷‍♂️ Данные чемпионата пока недоступны."
        
    await tmp_msg.edit_text(text, parse_mode="Markdown")

@dp.message(F.text == '🏎 Кубок конструкторов')
async def process_teams(message: types.Message):
    tmp_msg = await message.answer("🔄 Загружаю Кубок...")
    data = await fetch_f1_data("current/constructorStandings")
    
    if not data:
        await tmp_msg.edit_text("❌ Ошибка получения данных.")
        return

    try:
        standings = data['MRData']['StandingsTable']['StandingsLists'][0]['ConstructorStandings']
        
        text = "🏎 *Кубок конструкторов:*\n\n"
        for team in standings:
            pos = team['position']
            name = team['Constructor']['name']
            points = team['points']
            text += f"{pos}. {name} — {points} очков\n"
    except (KeyError, IndexError):
        text = "🤷‍♂️ Данные пока недоступны."
        
    await tmp_msg.edit_text(text, parse_mode="Markdown")

@dp.message(F.text == '📊 Сравнение телеметрии')
async def process_telemetry(message: types.Message):
    text = (
        "📊 *Модуль телеметрии*\n"
        "Эта фича находится в разработке. Скоро здесь будут крутые графики прохождения секторов!"
    )
    await message.answer(text, parse_mode="Markdown")

async def main():
    init_db()
    scheduler.add_job(check_race_reminders, 'interval', minutes=5)
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())