import os
import asyncio
import aiohttp
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')

if not TOKEN:
    exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher()

API_URL = "https://api.jolpi.ca/ergast/f1"
DB_PATH = "f1_users.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY)")

def add_user(chat_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (chat_id,))

def get_users():
    with sqlite3.connect(DB_PATH) as conn:
        return [row[0] for row in conn.execute("SELECT chat_id FROM users")]

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
        [KeyboardButton(text="📊 Сравнение телеметрии")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def extract_all_sessions(race_data: dict) -> list:
    sessions = []
    keys_map = [
        ('FirstPractice', '🏎 Первая тренировка'),
        ('SecondPractice', '🏎 Вторая тренировка'),
        ('ThirdPractice', '🏎 Третья тренировка'),
        ('SprintQualifying', '⏱ Спринт-квалификация'),
        ('Sprint', '🔥 Спринт'),
        ('Qualifying', '⏱ Квалификация к гонке')
    ]
    
    for key, name in keys_map:
        if key in race_data:
            sessions.append({
                'name': name,
                'date': race_data[key].get('date'),
                'time': race_data[key].get('time', '00:00:00Z')
            })
            
    sessions.append({
        'name': '🏁 Главная гонка',
        'date': race_data.get('date'),
        'time': race_data.get('time', '00:00:00Z')
    })
    
    return sessions

async def check_schedule_and_notify():
    data = await fetch_f1_data("current/next")
    if not data:
        return

    try:
        race = data['MRData']['RaceTable']['Races'][0]
        race_name = race['raceName']
        sessions = extract_all_sessions(race)
        now_utc = datetime.now(ZoneInfo("UTC"))
        
        for sess in sessions:
            if not sess['date'] or not sess['time']:
                continue
                
            dt_utc = datetime.strptime(f"{sess['date']} {sess['time']}", "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC"))
            delta = (dt_utc - now_utc).total_seconds()
            
            if 3300 <= delta <= 3600:
                dt_moscow = dt_utc.astimezone(ZoneInfo("Europe/Moscow")).strftime("%H:%M")
                msg = f"🔔 *Напоминание!*\n\n{sess['name']} в рамках {race_name} начнется ровно через час (в {dt_moscow} по Мск)!"
                
                for chat_id in get_users():
                    try:
                        await bot.send_message(chat_id, msg, parse_mode="Markdown")
                    except Exception:
                        pass
    except Exception:
        pass

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    add_user(message.chat.id)
    welcome_text = (
        "Привет, фанат автоспорта! 🏎💨\n\n"
        "Я буду присылать тебе напоминания за час до старта каждой квалификации и гонки.\n"
        "Используй кнопки внизу для навигации!"
    )
    await message.answer(welcome_text, reply_markup=get_reply_keyboard())

@dp.message(F.text == '📅 Ближайший этап')
async def process_next_race(message: types.Message):
    add_user(message.chat.id)
    tmp_msg = await message.answer("🔄 Загружаю расписание...")
    data = await fetch_f1_data("current/next")
    
    if not data:
        await tmp_msg.edit_text("❌ Ошибка получения данных от API.")
        return

    try:
        race = data['MRData']['RaceTable']['Races'][0]
        race_name = race['raceName']
        circuit = race['Circuit']['circuitName']
        
        sessions = extract_all_sessions(race)
        
        ru_days = {0: 'Понедельник', 1: 'Вторник', 2: 'Среда', 3: 'Четверг', 4: 'Пятница', 5: 'Суббота', 6: 'Воскресенье'}
        schedule_by_date = {}
        
        for sess in sessions:
            if not sess['date'] or not sess['time']:
                continue
                
            dt_utc = datetime.strptime(f"{sess['date']} {sess['time']}", "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC"))
            dt_local = dt_utc.astimezone(ZoneInfo("Europe/Moscow"))
            
            date_key = f"{ru_days[dt_local.weekday()]}, {dt_local.strftime('%d.%m')}"
            time_str = dt_local.strftime("%H:%M")
            
            if date_key not in schedule_by_date:
                schedule_by_date[date_key] = []
            schedule_by_date[date_key].append(f"{time_str} — {sess['name']}")
        
        text = f"📅 *{race_name}*\n📍 Трасса: {circuit}\n\n*Расписание (время московское):*\n\n"
        
        for date_key, events in schedule_by_date.items():
            text += f"*{date_key}:*\n"
            for event in events:
                text += f"{event}\n"
            text += "\n"
            
    except Exception:
        text = "🤷‍♂️ Не удалось распарсить данные о следующей гонке."
        
    await tmp_msg.edit_text(text, parse_mode="Markdown")

@dp.message(F.text == '🏁 Последняя гонка')
async def process_last_race(message: types.Message):
    add_user(message.chat.id)
    tmp_msg = await message.answer("🔄 Загружаю результаты...")
    data = await fetch_f1_data("current/last/results")
    
    if data:
        try:
            race = data['MRData']['RaceTable']['Races'][0]
            text = f"🏁 *Итоги: {race['raceName']}*\n\n"
            for res in race['Results'][:5]:
                text += f"{res['position']}. {res['Driver']['familyName']} ({res['Constructor']['name']}) — {res['points']} очков\n"
            await tmp_msg.edit_text(text, parse_mode="Markdown")
            return
        except KeyError:
            pass
    await tmp_msg.edit_text("🤷‍♂️ Ошибка получения результатов.")

@dp.message(F.text == '🏆 Личный зачет')
async def process_drivers(message: types.Message):
    add_user(message.chat.id)
    tmp_msg = await message.answer("🔄 Загружаю таблицу...")
    data = await fetch_f1_data("current/driverStandings")
    
    if data:
        try:
            standings = data['MRData']['StandingsTable']['StandingsLists'][0]['DriverStandings'][:10]
            text = "🏆 *Личный зачет (Топ-10):*\n\n"
            for driver in standings:
                text += f"{driver['position']}. {driver['Driver']['familyName']} — {driver['points']} очков\n"
            await tmp_msg.edit_text(text, parse_mode="Markdown")
            return
        except KeyError:
            pass
    await tmp_msg.edit_text("🤷‍♂️ Данные пока недоступны.")

@dp.message(F.text == '🏎 Кубок конструкторов')
async def process_teams(message: types.Message):
    add_user(message.chat.id)
    tmp_msg = await message.answer("🔄 Загружаю Кубок...")
    data = await fetch_f1_data("current/constructorStandings")
    
    if data:
        try:
            standings = data['MRData']['StandingsTable']['StandingsLists'][0]['ConstructorStandings']
            text = "🏎 *Кубок конструкторов:*\n\n"
            for team in standings:
                text += f"{team['position']}. {team['Constructor']['name']} — {team['points']} очков\n"
            await tmp_msg.edit_text(text, parse_mode="Markdown")
            return
        except KeyError:
            pass
    await tmp_msg.edit_text("🤷‍♂️ Данные пока недоступны.")

@dp.message(F.text == '📊 Сравнение телеметрии')
async def process_telemetry(message: types.Message):
    add_user(message.chat.id)
    await message.answer("📊 *Модуль телеметрии*\nСкоро здесь будут графики!", parse_mode="Markdown")

async def main():
    init_db()
    
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_schedule_and_notify, 'interval', minutes=5)
    scheduler.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())