import os
import asyncio
import aiohttp
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
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
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY)")
        try:
            c.execute("ALTER TABLE users ADD COLUMN notify_time INTEGER DEFAULT 60")
        except sqlite3.OperationalError:
            pass

def add_user(chat_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR IGNORE INTO users (chat_id, notify_time) VALUES (?, 60)", (chat_id,))

def update_notify_time(chat_id, minutes):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE users SET notify_time = ? WHERE chat_id = ?", (minutes, chat_id))

def get_user_settings():
    with sqlite3.connect(DB_PATH) as conn:
        return [{"chat_id": row[0], "notify_time": row[1]} for row in conn.execute("SELECT chat_id, notify_time FROM users")]

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
        [KeyboardButton(text="📊 Сравнение телеметрии"), KeyboardButton(text="🔎 Инфо и Профили")],
        [KeyboardButton(text="⚙️ Настройки")]
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
        
        users = get_user_settings()
        
        for sess in sessions:
            if not sess['date'] or not sess['time']:
                continue
                
            dt_utc = datetime.strptime(f"{sess['date']} {sess['time']}", "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC"))
            delta_minutes = (dt_utc - now_utc).total_seconds() / 60
            
            for user in users:
                offset = user['notify_time']
                if offset == 0:
                    continue
                    
                if offset - 5 < delta_minutes <= offset:
                    dt_moscow = dt_utc.astimezone(ZoneInfo("Europe/Moscow")).strftime("%H:%M")
                    
                    if offset == 1440:
                        time_str = "ровно через 24 часа"
                    elif offset >= 60:
                        time_str = f"через {offset // 60} час(а)"
                    else:
                        time_str = f"через {offset} минут"
                        
                    msg = f"🔔 *Напоминание!*\n\n{sess['name']} в рамках {race_name} начнется {time_str} (в {dt_moscow} по Мск)!"
                    
                    try:
                        await bot.send_message(user['chat_id'], msg, parse_mode="Markdown")
                    except Exception:
                        pass
    except Exception as e:
        print(f"Ошибка в планировщике: {e}")

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    add_user(message.chat.id)
    user_name = message.from_user.first_name or "фанат автоспорта"
    
    welcome_text = (
        f"Привет, {user_name}! 🏎💨\n\n"
        "Я — твой личный бот-помощник по Формуле-1.\n"
        "По умолчанию я буду присылать тебе напоминания за час до старта каждой сессии уик-энда. "
        "Время уведомлений можно изменить в меню настроек.\n\n"
        "Используй кнопки внизу для навигации!"
    )
    await message.answer(welcome_text, reply_markup=get_reply_keyboard())

@dp.message(F.text == '🔎 Инфо и Профили')
async def info_menu(message: types.Message):
    add_user(message.chat.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏎 Профили топ-пилотов", callback_data="info_drivers")],
        [InlineKeyboardButton(text="📍 Инфо о текущей трассе", callback_data="info_circuit")]
    ])
    await message.answer("Что именно вас интересует?", reply_markup=kb)

@dp.callback_query(F.data == 'info_drivers')
async def list_top_drivers(callback: types.CallbackQuery):
    data = await fetch_f1_data("current/driverStandings")
    if not data:
        await callback.message.edit_text("❌ Ошибка получения данных.")
        await callback.answer()
        return

    try:
        standings = data['MRData']['StandingsTable']['StandingsLists'][0]['DriverStandings'][:5]
        buttons = []
        for d in standings:
            driver_id = d['Driver']['driverId']
            name = f"{d['Driver']['givenName']} {d['Driver']['familyName']}"
            buttons.append([InlineKeyboardButton(text=name, callback_data=f"profile_{driver_id}")])
            
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_info")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("Выберите пилота для просмотра профиля:", reply_markup=kb)
    except Exception:
        await callback.message.edit_text("🤷‍♂️ Не удалось загрузить список пилотов.")
    await callback.answer()

@dp.callback_query(F.data.startswith('profile_'))
async def show_driver_profile(callback: types.CallbackQuery):
    driver_id = callback.data.split('_')[1]
    
    data_bio = await fetch_f1_data(f"drivers/{driver_id}")
    data_stats = await fetch_f1_data(f"drivers/{driver_id}/driverStandings")
    
    if not data_bio or not data_stats:
        await callback.message.edit_text("❌ Ошибка получения данных о пилоте.")
        await callback.answer()
        return

    try:
        driver = data_bio['MRData']['DriverTable']['Drivers'][0]
        name = f"{driver['givenName']} {driver['familyName']}"
        code = driver.get('code', '')
        number = driver.get('permanentNumber', '')
        dob = driver['dateOfBirth']
        nationality = driver['nationality']
        url = driver['url']
        
        try:
            lists = data_stats['MRData']['StandingsTable']['StandingsLists']
            titles = 0
            total_points = 0.0
            for l in lists:
                pos = l['DriverStandings'][0]['position']
                total_points += float(l['DriverStandings'][0]['points'])
                if pos == "1":
                    titles += 1
            stats_text = f"🏆 Титулов чемпиона мира: {titles}\n💯 Очков за карьеру: {int(total_points)}"
        except Exception:
            stats_text = "📊 Статистика за карьеру временно недоступна."

        text = (
            f"🏎 *Профиль пилота: {name} ({code})*\n"
            f"🔢 Постоянный номер: {number}\n"
            f"🌍 Национальность: {nationality}\n"
            f"📅 Дата рождения: {dob}\n\n"
            f"{stats_text}\n\n"
            f"🔗 [Страница в Википедии]({url})"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К списку пилотов", callback_data="info_drivers")]
        ])
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        await callback.message.edit_text("🤷‍♂️ Не удалось распарсить профиль.")
    await callback.answer()

@dp.callback_query(F.data == 'info_circuit')
async def show_circuit_info(callback: types.CallbackQuery):
    data = await fetch_f1_data("current/next")
    if not data:
        await callback.message.edit_text("❌ Ошибка получения данных.")
        await callback.answer()
        return

    try:
        race = data['MRData']['RaceTable']['Races'][0]
        circuit = race['Circuit']
        name = circuit['circuitName']
        locality = circuit['Location']['locality']
        country = circuit['Location']['country']
        lat = circuit['Location']['lat']
        lng = circuit['Location']['long']
        url = circuit['url']
        
        text = (
            f"📍 *Информация о текущей трассе*\n\n"
            f"🏁 Название: {name}\n"
            f"🏙 Город/Регион: {locality}\n"
            f"🌍 Страна: {country}\n"
            f"🌐 Координаты: {lat}, {lng}\n\n"
            f"🔗 [Подробнее в Википедии]({url})"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_info")]
        ])
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        await callback.message.edit_text("🤷‍♂️ Не удалось распарсить данные о трассе.")
    await callback.answer()

@dp.callback_query(F.data == 'back_to_info')
async def back_to_info_menu(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏎 Профили топ-пилотов", callback_data="info_drivers")],
        [InlineKeyboardButton(text="📍 Инфо о текущей трассе", callback_data="info_circuit")]
    ])
    await callback.message.edit_text("What exactly interests you?", reply_markup=kb)
    await callback.answer()

@dp.message(F.text == '⚙️ Настройки')
async def settings_menu(message: types.Message):
    add_user(message.chat.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="За 30 минут", callback_data="notify_30"),
         InlineKeyboardButton(text="За 1 час", callback_data="notify_60")],
        [InlineKeyboardButton(text="За 2 часа", callback_data="notify_120"),
         InlineKeyboardButton(text="За 24 часа", callback_data="notify_1440")],
        [InlineKeyboardButton(text="🔕 Отключить уведомления", callback_data="notify_0")]
    ])
    await message.answer("Выберите, за какое время до старта присылать напоминания:", reply_markup=kb)

@dp.callback_query(F.data.startswith('notify_'))
async def process_notify_setting(callback: types.CallbackQuery):
    minutes = int(callback.data.split('_')[1])
    update_notify_time(callback.message.chat.id, minutes)
    
    if minutes == 0:
        text = "🔕 Уведомления полностью отключены."
    elif minutes == 1440:
        text = "✅ Напоминания установлены: за 24 часа до старта."
    elif minutes >= 60:
        text = f"✅ Напоминания установлены: за {minutes // 60} час(а) до старта."
    else:
        text = f"✅ Напоминания установлены: за {minutes} минут до старта."
        
    await callback.message.edit_text(text)
    await callback.answer()

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
            if not sess['date'] or not sess['time']: continue
            dt_utc = datetime.strptime(f"{sess['date']} {sess['time']}", "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC"))
            dt_local = dt_utc.astimezone(ZoneInfo("Europe/Moscow"))
            date_key = f"{ru_days[dt_local.weekday()]}, {dt_local.strftime('%d.%m')}"
            
            if date_key not in schedule_by_date:
                schedule_by_date[date_key] = []
            schedule_by_date[date_key].append(f"{dt_local.strftime('%H:%M')} — {sess['name']}")
        
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