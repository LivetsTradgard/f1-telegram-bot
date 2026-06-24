import os
import time
import random
import asyncio
import aiohttp
import sqlite3
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')

if not TOKEN:
    exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher()

API_URL = "https://api.jolpi.ca/ergast/f1"
DB_PATH = "f1_users.db"

DRIVERS_DB = {
    "special": [
        {"id": "schumacher", "name": "Михаэль Шумахер", "emoji": "🇩🇪"},
        {"id": "senna", "name": "Айртон Сенна", "emoji": "🇧🇷"},
        {"id": "vettel", "name": "Себастьян Феттель", "emoji": "🇩🇪"},
        {"id": "prost", "name": "Ален Прост", "emoji": "🇫🇷"},
        {"id": "raikkonen", "name": "Кими Райкконен", "emoji": "🇫🇮"}
    ],
    "legendary": [
        {"id": "antonelli", "name": "Кими Антонелли", "emoji": "🇮🇹"},
        {"id": "hamilton", "name": "Льюис Хэмилтон", "emoji": "🇬🇧"},
        {"id": "verstappen", "name": "Макс Ферстаппен", "emoji": "🇳🇱"}
    ],
    "mythic": [
        {"id": "leclerc", "name": "Шарль Леклер", "emoji": "🇲🇨"},
        {"id": "alonso", "name": "Фернандо Алонсо", "emoji": "🇪🇸"}
    ],
    "epic": [
        {"id": "russell", "name": "Джордж Расселл", "emoji": "🇬🇧"},
        {"id": "norris", "name": "Ландо Норрис", "emoji": "🇬🇧"},
        {"id": "piastri", "name": "Оскар Пиастри", "emoji": "🇦🇺"},
        {"id": "hadjar", "name": "Исак Хаджар", "emoji": "🇫🇷"}
    ],
    "rare": [
        {"id": "gasly", "name": "Пьер Гасли", "emoji": "🇫🇷"},
        {"id": "colapinto", "name": "Франко Колапинто", "emoji": "🇦🇷"},
        {"id": "bearman", "name": "Оливер Берман", "emoji": "🇬🇧"},
        {"id": "sainz", "name": "Карлос Сайнс", "emoji": "🇪🇸"},
        {"id": "hulkenberg", "name": "Нико Хюлькенберг", "emoji": "🇩🇪"},
        {"id": "bortoleto", "name": "Габриэль Бортолето", "emoji": "🇧🇷"},
        {"id": "perez", "name": "Серхио Перес", "emoji": "🇲🇽"}
    ],
    "common": [
        {"id": "lawson", "name": "Лиам Лоусон", "emoji": "🇳🇿"},
        {"id": "lindblad", "name": "Арвид Линдблад", "emoji": "🇬🇧"},
        {"id": "ocon", "name": "Эстебан Окон", "emoji": "🇫🇷"},
        {"id": "albon", "name": "Александр Албон", "emoji": "🇹🇭"},
        {"id": "stroll", "name": "Лэнс Стролл", "emoji": "🇨🇦"},
        {"id": "bottas", "name": "Валттери Боттас", "emoji": "🇫🇮"}
    ]
}

RARITY_INFO = {
    "special": {"name": "✨ ОСОБАЯ", "chance": 0.01},
    "legendary": {"name": "🟡 ЛЕГЕНДА", "chance": 0.1},
    "mythic": {"name": "🟣 МИФИК", "chance": 1.0},
    "epic": {"name": "🔵 ЭПИК", "chance": 4.0},
    "rare": {"name": "🟢 РЕДКАЯ", "chance": 25.0},
    "common": {"name": "⚪️ ОБЫЧНАЯ", "chance": 69.89}
}

class Archive(StatesGroup):
    waiting_for_year = State()

class Predict(StatesGroup):
    waiting_p1 = State()
    waiting_p2 = State()
    waiting_p3 = State()

def get_rank_info(xp):
    ranks = [
        (50, "🎟 Зритель на трибуне"),
        (150, "🎫 Гость паддок-клуба"),
        (300, "🏁 Маршал трассы"),
        (500, "🔧 Гоночный механик"),
        (750, "🏎 Пилот картинга"),
        (1000, "🏆 Чемпион картинга"),
        (1300, "🥉 Пилот Формулы-4"),
        (1700, "🥉 Чемпион Формулы-4"),
        (2200, "🥈 Пилот Формулы-3"),
        (2800, "🥈 Чемпион Формулы-3"),
        (3500, "🥇 Пилот Формулы-2"),
        (4300, "🥇 Чемпион Формулы-2"),
        (5200, "⏱ Тест-пилот Формулы-1"),
        (6200, "🏎 Боевой пилот Ф1"),
        (7300, "⭐️ Лидер команды Ф1"),
        (8500, "🍾 Завсегдатай подиума"),
        (10000, "🏆 Победитель Гран-при"),
        (12000, "🎖 Претендент на титул"),
        (15000, "👑 Чемпион Мира Ф1")
    ]
    
    for threshold, name in ranks:
        if xp < threshold:
            return (name, threshold)
            
    return ("🐐 Легенда Автоспорта", None)

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY)")
        
        for col, col_type, default in [("notify_time", "INTEGER", "60"), 
                                       ("name", "TEXT", "'Гонщик'"), 
                                       ("xp", "INTEGER", "0"),
                                       ("last_pull_time", "INTEGER", "0"),
                                       ("special_pity", "REAL", "0.0"),
                                       ("legendary_pity", "REAL", "0.0"),
                                       ("reminded", "INTEGER", "0")]:
            try:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type} DEFAULT {default}")
            except sqlite3.OperationalError:
                pass
            
        c.execute("""CREATE TABLE IF NOT EXISTS predictions (
            chat_id INTEGER,
            race_id TEXT,
            p1 TEXT,
            p2 TEXT,
            p3 TEXT,
            scored INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, race_id)
        )""")
        
        try:
            c.execute("ALTER TABLE predictions ADD COLUMN accuracy INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
            
        c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        
        c.execute("""CREATE TABLE IF NOT EXISTS inventory (
            chat_id INTEGER,
            driver_id TEXT,
            rarity TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, driver_id)
        )""")

def add_user(chat_id, name=None):
    user_name = name or "Гонщик"
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR IGNORE INTO users (chat_id, notify_time, name, xp, last_pull_time) VALUES (?, 60, ?, 0, 0)", (chat_id, user_name))
        conn.execute("UPDATE users SET name = ? WHERE chat_id = ?", (user_name, chat_id))

def update_notify_time(chat_id, minutes):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE users SET notify_time = ? WHERE chat_id = ?", (minutes, chat_id))

def get_user_settings():
    with sqlite3.connect(DB_PATH) as conn:
        return [{"chat_id": row[0], "notify_time": row[1]} for row in conn.execute("SELECT chat_id, notify_time FROM users")]

async def fetch_f1_data(endpoint: str, params: dict = None) -> dict:
    cache_key = endpoint.replace('/', '_')
    if params:
        cache_key += "_" + "_".join([f"{k}_{v}" for k, v in params.items()])
    cache_file = f"cache_{cache_key}.json"

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        headers = {"User-Agent": "F1TelegramBot/1.0"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(f"{API_URL}/{endpoint}.json", params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    with open(cache_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False)
                    return data
    except Exception as e:
        print(f"API Error ({endpoint}): {e}")

    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Cache Read Error ({endpoint}): {e}")

    return None

async def check_and_send_news():
    url = "https://www.f1news.ru/export/news.xml"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    xml_data = await resp.text()
                    root = ET.fromstring(xml_data)
                    item = root.find('.//item')
                    
                    if item is None: return
                    
                    title = item.find('title').text
                    link = item.find('link').text
                    
                    with sqlite3.connect(DB_PATH) as conn:
                        c = conn.cursor()
                        last_link = c.execute("SELECT value FROM settings WHERE key = 'last_news'").fetchone()
                        
                        if not last_link or last_link[0] != link:
                            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_news', ?)", (link,))
                            
                            users = get_user_settings()
                            msg = f"📰 *Главная новость паддока:*\n\n{title}\n\n🔗 [Читать подробнее]({link})"
                            for user in users:
                                try:
                                    await bot.send_message(user['chat_id'], msg, parse_mode="Markdown")
                                except: pass
    except Exception as e:
        print(f"News fetch error: {e}")

def get_weather_emoji(code):
    if code in [0, 1]: return "☀️"
    if code in [2, 3]: return "☁️"
    if code in [45, 48]: return "🌫"
    if code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]: return "🌧"
    if code in [95, 96, 99]: return "⛈"
    return "🌡"

async def fetch_weather(lat: float, lon: float, target_date_str: str = None) -> dict:
    url = "https://api.open-meteo.com/v1/forecast"
    try:
        if not target_date_str:
            params = {"latitude": lat, "longitude": lon, "current_weather": "true"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("current_weather")
        else:
            params = {
                "latitude": lat, "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                "timezone": "auto",
                "start_date": target_date_str,
                "end_date": target_date_str
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "daily" in data and len(data["daily"]["time"]) > 0:
                            return {
                                "t_max": data["daily"]["temperature_2m_max"][0],
                                "t_min": data["daily"]["temperature_2m_min"][0],
                                "rain": data["daily"]["precipitation_sum"][0],
                                "code": data["daily"]["weathercode"][0]
                            }
    except Exception as e:
        print(f"Weather fetch error: {e}")
    return None

def get_reply_keyboard():
    keyboard = [
        [KeyboardButton(text="📅 Ближайший этап"), KeyboardButton(text="🏁 Последняя гонка")],
        [KeyboardButton(text="🏆 Личный зачет"), KeyboardButton(text="🏎 Кубок конструкторов")],
        [KeyboardButton(text="🔎 Инфо и Профили"), KeyboardButton(text="📜 Архив сезонов")],
        [KeyboardButton(text="🔮 Прогнозы на подиум"), KeyboardButton(text="📊 Рейтинг игроков")],
        [KeyboardButton(text="🎴 Гараж"), KeyboardButton(text="👤 Мой профиль")],
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
    if not data: return

    try:
        race = data['MRData']['RaceTable']['Races'][0]
        race_name = race['raceName']
        sessions = extract_all_sessions(race)
        now_utc = datetime.now(ZoneInfo("UTC"))
        users = get_user_settings()
        
        for sess in sessions:
            if not sess['date'] or not sess['time']: continue
                
            dt_utc = datetime.strptime(f"{sess['date']} {sess['time']}", "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC"))
            delta_minutes = (dt_utc - now_utc).total_seconds() / 60
            
            if sess['name'] == '🏁 Главная гонка' and 1435 < delta_minutes <= 1440:
                for user in users:
                    msg = (f"⏳ До старта {race_name} остались ровно сутки!\n\n"
                           f"Самое время сделать прогноз на подиум. Нажми кнопку «🔮 Прогнозы на подиум» в меню, "
                           f"чтобы проверить свою интуицию!")
                    try:
                        await bot.send_message(user['chat_id'], msg)
                    except: pass
        
            for user in users:
                offset = user['notify_time']
                if offset == 0: continue
                    
                if offset - 5 < delta_minutes <= offset:
                    dt_moscow = dt_utc.astimezone(ZoneInfo("Europe/Moscow")).strftime("%H:%M")
                    if offset == 1440: time_str = "ровно через 24 часа"
                    elif offset >= 60: time_str = f"через {offset // 60} час(а)"
                    else: time_str = f"через {offset} минут"
                        
                    msg = f"🔔 *Напоминание!*\n\n{sess['name']} в рамках {race_name} начнется {time_str} (в {dt_moscow} по Мск)!"
                    try:
                        await bot.send_message(user['chat_id'], msg, parse_mode="Markdown")
                    except: pass
    except Exception: pass

async def check_race_results():
    data = await fetch_f1_data("current/last/results")
    if not data: return
    
    try:
        race = data['MRData']['RaceTable']['Races'][0]
        season = race['season']
        round_ = race['round']
        race_id = f"{season}_{round_}"
        race_name = race['raceName']
        
        results = race['Results']
        if len(results) < 3: return
        
        actual_podium = [r['Driver']['driverId'] for r in results[:3]]
        driver_names = {r['Driver']['driverId']: f"{r['Driver']['familyName']}" for r in results}
        
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            preds = c.execute("SELECT chat_id, p1, p2, p3 FROM predictions WHERE race_id = ? AND scored = 0", (race_id,)).fetchall()
            
            for chat_id, p1, p2, p3 in preds:
                pred_podium = [p1, p2, p3]
                score = 0.0
                
                for i in range(3):
                    if pred_podium[i] == actual_podium[i]: score += 33.34
                    elif pred_podium[i] in actual_podium: score += 16.67
                        
                percent = round(score)
                if percent >= 99: percent = 100
                
                earned_xp = 10 + int(percent * 2)
                
                p1_name = driver_names.get(p1, p1)
                p2_name = driver_names.get(p2, p2)
                p3_name = driver_names.get(p3, p3)
                
                msg = (f"🏁 Итоги Гран-при: {race_name}!\n\n"
                       f"🏆 *Реальный подиум:*\n"
                       f"1. {driver_names[actual_podium[0]]}\n"
                       f"2. {driver_names[actual_podium[1]]}\n"
                       f"3. {driver_names[actual_podium[2]]}\n\n"
                       f"🔮 *Твой прогноз:*\n"
                       f"1. {p1_name}\n2. {p2_name}\n3. {p3_name}\n\n"
                       f"🎯 *Точность твоего прогноза: {percent}%*\n"
                       f"✨ *Получено опыта:* +{earned_xp} XP")
                
                try: await bot.send_message(chat_id, msg, parse_mode="Markdown")
                except: pass
                
                conn.execute("UPDATE predictions SET scored = 1, accuracy = ? WHERE chat_id = ? AND race_id = ?", (percent, chat_id, race_id))
                conn.execute("UPDATE users SET xp = xp + ? WHERE chat_id = ?", (earned_xp, chat_id))
    except Exception as e: print(f"Results scoring error: {e}")

async def check_gacha_reminders():
    now = int(time.time())
    cooldown = 6 * 3600
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        users_to_remind = c.execute("""
            SELECT chat_id FROM users 
            WHERE last_pull_time > 0 
              AND (? - last_pull_time) >= ? 
              AND reminded = 0
        """, (now, cooldown)).fetchall()
        
        for (chat_id,) in users_to_remind:
            try:
                await bot.send_message(chat_id, "🎴 *Твой гараж снова открыт!*\nПрошло 6 часов, самое время подписать нового пилота!", parse_mode="Markdown")
                c.execute("UPDATE users SET reminded = 1 WHERE chat_id = ?", (chat_id,))
            except:
                pass

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    add_user(message.chat.id, message.from_user.first_name)
    user_name = message.from_user.first_name or "фанат автоспорта"
    welcome_text = (f"Привет, {user_name}! 🏎💨\n\nЯ — твой личный бот-помощник по Формуле-1.\n"
                    f"Используй кнопки внизу для навигации!")
    await message.answer(welcome_text, reply_markup=get_reply_keyboard())

@dp.message(Command('news'))
async def force_news(message: types.Message):
    if message.from_user.id != 733477024: return
    await check_and_send_news()

def get_gacha_text_and_kb(chat_id: int):
    total_drivers = sum(len(cat) for cat in DRIVERS_DB.values())
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        count = c.execute("SELECT SUM(count) FROM inventory WHERE chat_id = ?", (chat_id,)).fetchone()[0] or 0
        unique = c.execute("SELECT COUNT(*) FROM inventory WHERE chat_id = ?", (chat_id,)).fetchone()[0] or 0
        cards = c.execute("SELECT driver_id, rarity, count FROM inventory WHERE chat_id = ? ORDER BY count DESC", (chat_id,)).fetchall()
        
    text = (f"🎴 *Твой гараж*\n\n"
            f"Прогресс коллекции: {unique} из {total_drivers} пилотов\n"
            f"Всего карточек: {count}\n\n")
            
    if not cards:
        text += "_Твоя коллекция пока пуста. Нажми «Открыть», чтобы получить первого пилота!_\n"
    else:
        text += "*Текущая коллекция:*\n"
        collection = {"special": [], "legendary": [], "mythic": [], "epic": [], "rare": [], "common": []}
        all_drivers = {d['id']: d for category in DRIVERS_DB.values() for d in category}
        
        for d_id, rarity, cnt in cards:
            if d_id in all_drivers:
                collection[rarity].append((all_drivers[d_id], cnt))
                
        for rarity in ["special", "legendary", "mythic", "epic", "rare", "common"]:
            if collection[rarity]:
                text += f"{RARITY_INFO[rarity]['name']}:\n"
                for driver, cnt in collection[rarity]:
                    cnt_str = f" x{cnt}" if cnt > 1 else ""
                    text += f"  {driver['emoji']} {driver['name']}{cnt_str}\n"
                text += "\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Открыть", callback_data="pull_card")]
    ])
    
    return text, kb

@dp.message(F.text == '🎴 Гараж')
async def gacha_menu(message: types.Message):
    add_user(message.chat.id, message.from_user.first_name)
    text, kb = get_gacha_text_and_kb(message.chat.id)
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == 'pull_card')
async def pull_new_card(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    now = int(time.time())
    cooldown = 6 * 3600
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        user_data = c.execute("SELECT last_pull_time, special_pity, legendary_pity FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
        last_pull, sp_pity, leg_pity = user_data
        
        if now - last_pull < cooldown:
            rem = cooldown - (now - last_pull)
            h = rem // 3600
            m = (rem % 3600) // 60
            await callback.answer(f"⏳ Следующее открытие будет доступно через {h} ч. {m} мин.", show_alert=True)
            return
            
        sp_chance = 0.01 + sp_pity
        leg_chance = 0.1 + leg_pity
        
        roll = random.uniform(0, 100)
        
        if roll <= sp_chance:
            rarity = "special"
            new_sp_pity = 0.0 
            new_leg_pity = leg_pity + 0.05 
        elif roll <= sp_chance + leg_chance:
            rarity = "legendary"
            new_sp_pity = sp_pity + 0.01
            new_leg_pity = 0.0 
        elif roll <= sp_chance + leg_chance + 1.0:
            rarity = "mythic"
            new_sp_pity, new_leg_pity = sp_pity + 0.01, leg_pity + 0.05
        elif roll <= sp_chance + leg_chance + 1.0 + 4.0:
            rarity = "epic"
            new_sp_pity, new_leg_pity = sp_pity + 0.01, leg_pity + 0.05
        elif roll <= sp_chance + leg_chance + 1.0 + 4.0 + 25.0:
            rarity = "rare"
            new_sp_pity, new_leg_pity = sp_pity + 0.01, leg_pity + 0.05
        else:
            rarity = "common"
            new_sp_pity, new_leg_pity = sp_pity + 0.01, leg_pity + 0.05
        
        driver = random.choice(DRIVERS_DB[rarity])
        c.execute("SELECT count FROM inventory WHERE chat_id = ? AND driver_id = ?", (chat_id, driver['id']))
        existing_card = c.fetchone()
        
        xp_rewards = {"common": 15, "rare": 30, "epic": 60, "mythic": 100, "legendary": 200, "special": 500}
        reward = xp_rewards[rarity]
        
        is_duplicate = False
        if existing_card:
            is_duplicate = True
            c.execute("UPDATE users SET xp = xp + ? WHERE chat_id = ?", (reward, chat_id))
        
        c.execute("""
            INSERT INTO inventory (chat_id, driver_id, rarity, count) 
            VALUES (?, ?, ?, 1) 
            ON CONFLICT(chat_id, driver_id) DO UPDATE SET count = count + 1
        """, (chat_id, driver['id'], rarity))
        
        c.execute("UPDATE users SET last_pull_time = ?, special_pity = ?, legendary_pity = ?, reminded = 0 WHERE chat_id = ?", 
                  (now, new_sp_pity, new_leg_pity, chat_id))

    rarity_name = RARITY_INFO[rarity]['name']
    msg = f"Выпал {rarity_name} {driver['name']} " + ("*(Дубликат! ✨ +{} XP)*".format(reward) if is_duplicate else "🎉")
    msg += "\nСледующее открытие будет доступно через 6 часов."
           
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад в Гараж", callback_data="back_to_gacha")]])
    await callback.message.edit_text(msg, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data == 'back_to_gacha')
async def back_to_gacha(callback: types.CallbackQuery):
    text, kb = get_gacha_text_and_kb(callback.message.chat.id)
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    await callback.answer()

def generate_drivers_kb(drivers_list: list, exclude: list = None) -> InlineKeyboardMarkup:
    if exclude is None: exclude = []
    buttons, row = [], []
    for d in drivers_list:
        if d['id'] in exclude: continue
        row.append(InlineKeyboardButton(text=d['name'], callback_data=f"pred_{d['id']}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="pred_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(F.text == '🔮 Прогнозы на подиум')
async def start_prediction(message: types.Message, state: FSMContext):
    add_user(message.chat.id, message.from_user.first_name)
    tmp_msg = await message.answer("🔄 Загружаю данные следующей гонки...")
    
    next_race_data = await fetch_f1_data("current/next")
    if not next_race_data: return await tmp_msg.edit_text("❌ Ошибка соединения с API.")
        
    try:
        race = next_race_data['MRData']['RaceTable']['Races'][0]
        race_id = f"{race['season']}_{race['round']}"
        race_name = race['raceName']
        
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            existing = c.execute("SELECT p1, p2, p3 FROM predictions WHERE chat_id = ? AND race_id = ?", (message.chat.id, race_id)).fetchone()
            
        if existing: return await tmp_msg.edit_text(f"✅ Ты уже сделал прогноз на {race_name}!\nЖди завершения гонки для подсчета очков.")
            
        drivers_data = await fetch_f1_data("current/driverStandings", params={"limit": 100})
        raw_drivers = drivers_data['MRData']['StandingsTable']['StandingsLists'][0]['DriverStandings']
        drivers_list = [{'id': d['Driver']['driverId'], 'name': d['Driver']['familyName']} for d in raw_drivers]
        
        await state.update_data(race_id=race_id, race_name=race_name, drivers=drivers_list, selected=[])
        await state.set_state(Predict.waiting_p1)
        
        kb = generate_drivers_kb(drivers_list)
        await tmp_msg.edit_text(f"🔮 *Прогноз на {race_name}*\n\n🥇 Выбери гонщика, который займет **ПЕРВОЕ** место:", parse_mode="Markdown", reply_markup=kb)
    except Exception: await tmp_msg.edit_text("❌ Ошибка формирования прогноза.")

@dp.callback_query(F.data == 'pred_cancel')
async def cancel_prediction(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Создание прогноза отменено.")
    await callback.answer()

@dp.callback_query(F.data.startswith('pred_'))
async def process_prediction_step(callback: types.CallbackQuery, state: FSMContext):
    driver_id = callback.data[5:]
    current_state = await state.get_state()
    data = await state.get_data()
    
    if not current_state: return await callback.answer("Сессия устарела. Начни заново.", show_alert=True)
        
    selected = data.get('selected', [])
    selected.append(driver_id)
    drivers_list = data.get('drivers', [])
    race_name = data.get('race_name')
    
    await state.update_data(selected=selected)
    
    if current_state == Predict.waiting_p1:
        await state.set_state(Predict.waiting_p2)
        kb = generate_drivers_kb(drivers_list, exclude=selected)
        await callback.message.edit_text(f"🔮 *Прогноз на {race_name}*\n\n🥈 Выбери гонщика на **ВТОРОЕ** место:", parse_mode="Markdown", reply_markup=kb)
        
    elif current_state == Predict.waiting_p2:
        await state.set_state(Predict.waiting_p3)
        kb = generate_drivers_kb(drivers_list, exclude=selected)
        await callback.message.edit_text(f"🔮 *Прогноз на {race_name}*\n\n🥉 Выбери гонщика на **ТРЕТЬЕ** место:", parse_mode="Markdown", reply_markup=kb)
        
    elif current_state == Predict.waiting_p3:
        race_id = data.get('race_id')
        p1, p2, p3 = selected[0], selected[1], selected[2]
        
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("INSERT OR REPLACE INTO predictions (chat_id, race_id, p1, p2, p3, scored, accuracy) VALUES (?, ?, ?, ?, ?, 0, 0)", 
                         (callback.message.chat.id, race_id, p1, p2, p3))
            
        await state.clear()
        
        names = {d['id']: d['name'] for d in drivers_list}
        text = (f"✅ **Прогноз успешно сохранен!**\n\n"
                f"1. {names.get(p1, p1)}\n2. {names.get(p2, p2)}\n3. {names.get(p3, p3)}\n\n"
                f"Бот пришлет результаты и начислит % точности и XP сразу после гонки!")
        await callback.message.edit_text(text, parse_mode="Markdown")
        
    await callback.answer()

def get_detailed_profile_text(chat_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        user_data = c.execute("SELECT name, xp, special_pity, legendary_pity FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
        if not user_data: return "Пользователь не найден."
        user_name, xp, sp_pity, leg_pity = user_data
        
        stats = c.execute("SELECT AVG(accuracy), COUNT(race_id) FROM predictions WHERE chat_id = ? AND scored = 1", (chat_id,)).fetchone()
        
        # Считаем только активных игроков (была крутка ИЛИ есть в таблице прогнозов)
        active_condition = "(last_pull_time > 0 OR chat_id IN (SELECT chat_id FROM predictions))"
        rank_query = c.execute(f"SELECT COUNT(*) FROM users WHERE xp > ? AND {active_condition}", (xp,)).fetchone()[0]
        place = rank_query + 1 
        total_players = c.execute(f"SELECT COUNT(*) FROM users WHERE {active_condition}").fetchone()[0]
        
        cards = c.execute("SELECT driver_id, rarity, count FROM inventory WHERE chat_id = ?", (chat_id,)).fetchall()
        total_drivers = sum(len(cat) for cat in DRIVERS_DB.values())
        unique = len(cards)
        
    rank_name, next_xp = get_rank_info(xp)
    
    text = f"👤 *Профиль: {user_name}*\n\n⚜️ *Звание:* {rank_name}\n✨ *Опыт:* {xp} XP\n"
    if next_xp: text += f"📈 *До след. ранга:* {next_xp - xp} XP\n\n"
    else: text += f"🌟 *Достигнут максимальный ранг!*\n\n"
    
    text += f"🎴 *Собрано пилотов:* {unique} из {total_drivers}\n"
    text += f"🍀 *Текущий шанс на Особую:* {0.01 + sp_pity:.2f}%\n"
    text += f"🟡 *Текущий шанс на Легенду:* {0.1 + leg_pity:.2f}%\n\n"
    
    if unique > 0:
        text += "*Топ-5 карточек в гараже:*\n"
        rarity_weight = {"special": 5, "legendary": 4, "mythic": 3, "epic": 2, "rare": 1, "common": 0}
        all_drivers = {d['id']: d for category in DRIVERS_DB.values() for d in category}
        sorted_cards = sorted(cards, key=lambda x: (rarity_weight.get(x[1], 0), x[2]), reverse=True)
        
        for d_id, rarity, cnt in sorted_cards[:5]:
            d = all_drivers.get(d_id)
            if d: text += f"• {RARITY_INFO[rarity]['name'].split(' ')[0]} {d['emoji']} {d['name']} (x{cnt})\n"
        text += "\n"
        
    if stats[1] > 0 and stats[0] is not None:
        text += (f"🎯 *Точность прогнозов:* {int(stats[0])}%\n"
                 f"🏁 *Сделано прогнозов:* {stats[1]}\n"
                 f"🏆 *Место в рейтинге:* {place} из {max(1, total_players)}\n")
    return text

def get_leaderboard_text_and_kb():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        data = c.execute("""
            SELECT u.chat_id, u.name, u.xp, COALESCE(AVG(p.accuracy), 0),
                   (SELECT COUNT(DISTINCT driver_id) FROM inventory WHERE chat_id = u.chat_id) as cards_count
            FROM users u
            LEFT JOIN predictions p ON u.chat_id = p.chat_id AND p.scored = 1
            WHERE u.last_pull_time > 0 OR u.chat_id IN (SELECT chat_id FROM predictions)
            GROUP BY u.chat_id
            ORDER BY u.xp DESC, AVG(p.accuracy) DESC
            LIMIT 10
        """).fetchall()
        
    if not data: 
        return "📊 *Рейтинг пока пуст.*", None
        
    text = "📊 *Глобальный рейтинг (Топ-10):*\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    
    for i, (uid, name, xp, avg_acc, cards_count) in enumerate(data):
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
        rank_name, _ = get_rank_info(xp)
        cards_count = cards_count if cards_count else 0
        
        text += f"{medal} *{name}* — {xp} XP\n_{rank_name}_ | 🎴 Пилотов: {cards_count}\n\n"
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"{medal} Профиль: {name}", callback_data=f"show_prof_{uid}")])
        
    text += "_Нажми на игрока ниже, чтобы посмотреть его профиль!_"
    return text, kb

@dp.message(F.text == '📊 Рейтинг игроков')
async def process_leaderboard(message: types.Message):
    add_user(message.chat.id, message.from_user.first_name)
    text, kb = get_leaderboard_text_and_kb()
    if kb:
        await message.answer(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await message.answer(text, parse_mode="Markdown")

@dp.callback_query(F.data.startswith('show_prof_'))
async def show_other_profile(callback: types.CallbackQuery):
    target_id = int(callback.data.split('_')[2])
    text = get_detailed_profile_text(target_id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к рейтингу", callback_data="back_to_leaderboard")]
    ])
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == 'back_to_leaderboard')
async def back_to_leaderboard_callback(callback: types.CallbackQuery):
    text, kb = get_leaderboard_text_and_kb()
    if kb:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()

@dp.message(F.text == '👤 Мой профиль')
async def process_my_profile(message: types.Message):
    add_user(message.chat.id, message.from_user.first_name)
    text = get_detailed_profile_text(message.chat.id)
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == '🔎 Инфо и Профили')
async def info_menu(message: types.Message):
    add_user(message.chat.id, message.from_user.first_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏎 Профили всех пилотов", callback_data="info_drivers")],
        [InlineKeyboardButton(text="📍 Инфо о текущей трассе", callback_data="info_circuit")]
    ])
    await message.answer("Что именно вас интересует?", reply_markup=kb)

@dp.callback_query(F.data == 'info_drivers')
async def list_all_drivers(callback: types.CallbackQuery):
    data = await fetch_f1_data("current/driverStandings", params={"limit": 100})
    if not data: return await callback.answer("Ошибка БД")
    try:
        standings = data['MRData']['StandingsTable']['StandingsLists'][0]['DriverStandings']
        buttons, row = [], []
        for d in standings:
            row.append(InlineKeyboardButton(text=f"{d['Driver']['givenName']} {d['Driver']['familyName']}", callback_data=f"profile_{d['Driver']['driverId']}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_info")])
        await callback.message.edit_text("Выберите пилота:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except Exception: pass
    await callback.answer()

@dp.callback_query(F.data.startswith('profile_'))
async def show_driver_profile(callback: types.CallbackQuery):
    driver_id = callback.data[8:]
    data = await fetch_f1_data("current/driverStandings", params={"limit": 100})
    if not data: return await callback.answer()
    try:
        standings = data['MRData']['StandingsTable']['StandingsLists'][0]['DriverStandings']
        driver_info = next((d for d in standings if d.get('Driver', {}).get('driverId') == driver_id), None)
        if not driver_info: return await callback.answer("Пилот не найден")
        driver = driver_info['Driver']
        text = (f"🏎 *Профиль: {driver.get('givenName', '')} {driver.get('familyName', '')} ({driver.get('code', '')})*\n"
                f"🏎 Команда: {driver_info.get('Constructors', [{'name': ''}])[0].get('name')}\n"
                f"🔢 Номер: {driver.get('permanentNumber', '')}\n"
                f"🌍 Нация: {driver.get('nationality', '')}\n\n"
                f"🏆 Позиция: {driver_info.get('position', '')} ({driver_info.get('points', '')} очков)\n🔗 [Википедия]({driver.get('url', '')})")
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ К списку", callback_data="info_drivers")]])
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)
    except: pass
    await callback.answer()

@dp.callback_query(F.data == 'info_circuit')
async def show_circuit_info(callback: types.CallbackQuery):
    data = await fetch_f1_data("current/next")
    if not data: return await callback.answer()
    try:
        circuit = data['MRData']['RaceTable']['Races'][0].get('Circuit', {})
        loc = circuit.get('Location', {})
        lat, lon = loc.get('lat'), loc.get('long')
        
        text = (f"📍 *{circuit.get('circuitName', '')}*\n🏙 Город: {loc.get('locality', '')}\n"
                f"🌍 Страна: {loc.get('country', '')}\n"
                f"📌 Координаты: `{lat}, {lon}`\n")
        
        if lat and lon:
            weather = await fetch_weather(float(lat), float(lon))
            if weather:
                emoji = get_weather_emoji(weather.get('weathercode', -1))
                text += f"\n🌤 *Текущая погода на треке:*\n{emoji} {weather.get('temperature', '?')}°C (Ветер: {weather.get('windspeed', '?')} км/ч)\n"

        text += f"\n🔗 [Читать в Википедии]({circuit.get('url', '')})"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_info")]])
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)
    except Exception as e: 
        print(e)
        pass
    await callback.answer()

@dp.callback_query(F.data == 'back_to_info')
async def back_to_info_menu(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏎 Профили всех пилотов", callback_data="info_drivers")],
        [InlineKeyboardButton(text="📍 Инфо о текущей трассе", callback_data="info_circuit")]
    ])
    await callback.message.edit_text("Что именно вас интересует?", reply_markup=kb)
    await callback.answer()

@dp.message(F.text == '📜 Архив сезонов')
async def archive_menu(message: types.Message, state: FSMContext):
    add_user(message.chat.id, message.from_user.first_name)
    await message.answer("Введите год (с 1950 по текущий), чтобы получить подробные итоги сезона:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(Archive.waiting_for_year)

@dp.message(Archive.waiting_for_year)
async def process_archive_year(message: types.Message, state: FSMContext):
    year_str = message.text.strip()
    if not year_str.isdigit() or not (1950 <= int(year_str) <= datetime.now().year):
        return await message.answer("❌ Пожалуйста, введите корректный год.")
    await state.clear()
    
    tmp_msg = await message.answer(f"🔄 Поднимаю архивы за {year_str} год...")
    driver_data = await fetch_f1_data(f"{year_str}/driverStandings", params={"limit": 10})
    team_data = await fetch_f1_data(f"{year_str}/constructorStandings", params={"limit": 3}) if int(year_str) >= 1958 else None
    
    if not driver_data or 'MRData' not in driver_data:
        await tmp_msg.delete()
        return await message.answer("❌ Ошибка сервера.", reply_markup=get_reply_keyboard())

    try:
        text = f"📜 *Итоги сезона {year_str}*\n\n"
        
        if team_data and team_data['MRData']['StandingsTable']['StandingsLists']:
            teams = team_data['MRData']['StandingsTable']['StandingsLists'][0]['ConstructorStandings']
            text += "🏎 *Кубок конструкторов (Топ-3):*\n"
            for i, t in enumerate(teams):
                text += f"{i+1}. {t['Constructor']['name']} — {t['points']} очков\n"
            text += "\n"
        elif int(year_str) < 1958:
            text += "🏎 _Кубок конструкторов в этот год еще не разыгрывался_\n\n"

        standings = driver_data['MRData']['StandingsTable']['StandingsLists'][0]['DriverStandings']
        text += "🏆 *Личный зачет (Топ-10):*\n"
        for i, d in enumerate(standings):
            name = f"{d['Driver']['givenName']} {d['Driver']['familyName']}"
            team = d['Constructors'][0]['name'] if d.get('Constructors') else "Неизвестно"
            pts = d['points']
            if i == 0: text += f"👑 *Чемпион:* {name} ({team}) — {pts} очков\n"
            else: text += f"{i+1}. {name} ({team}) — {pts} очков\n"
                
        await tmp_msg.delete()
        await message.answer(text, parse_mode="Markdown", reply_markup=get_reply_keyboard())
    except Exception:
        await tmp_msg.delete()
        await message.answer("❌ Ошибка форматирования архива.", reply_markup=get_reply_keyboard())

@dp.message(F.text == '⚙️ Настройки')
async def settings_menu(message: types.Message):
    add_user(message.chat.id, message.from_user.first_name)
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
    text = "🔕 Уведомления отключены." if minutes == 0 else f"✅ Напоминания установлены: за {minutes} минут."
    await callback.message.edit_text(text)
    await callback.answer()

@dp.message(F.text == '📅 Ближайший этап')
async def process_next_race(message: types.Message):
    add_user(message.chat.id, message.from_user.first_name)
    tmp_msg = await message.answer("🔄 Загружаю расписание...")
    data = await fetch_f1_data("current/next")
    if not data: return await tmp_msg.edit_text("❌ Ошибка.")
    try:
        race = data['MRData']['RaceTable']['Races'][0]
        circuit = race.get('Circuit', {})
        loc = circuit.get('Location', {})
        lat, lon = loc.get('lat'), loc.get('long')
        
        schedule_by_date, ru_days = {}, {0: 'Пн', 1: 'Вт', 2: 'Ср', 3: 'Чт', 4: 'Пт', 5: 'Сб', 6: 'Вс'}
        
        main_race_date_str = None
        main_race_dt = None
        
        for sess in extract_all_sessions(race):
            if not sess['date'] or not sess['time']: continue
            dt = datetime.strptime(f"{sess['date']} {sess['time']}", "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Moscow"))
            date_key = f"{ru_days[dt.weekday()]}, {dt.strftime('%d.%m')}"
            schedule_by_date.setdefault(date_key, []).append(f"{dt.strftime('%H:%M')} — {sess['name']}")
            
            if sess['name'] == '🏁 Главная гонка':
                main_race_date_str = sess['date']
                main_race_dt = dt
        
        text = f"📅 *{race['raceName']}* ({loc.get('country', '')})\n\n"
        for date_key, events in schedule_by_date.items(): 
            text += f"*{date_key}:*\n" + "\n".join(events) + "\n\n"
            
        if main_race_date_str and lat and lon and main_race_dt:
            days_until = (main_race_dt.date() - datetime.now(ZoneInfo("Europe/Moscow")).date()).days
            if 0 <= days_until <= 3:
                forecast = await fetch_weather(float(lat), float(lon), target_date_str=main_race_date_str)
                if forecast:
                    emoji = get_weather_emoji(forecast.get('code', -1))
                    text += (f"🌤 *Прогноз погоды на день гонки:*\n"
                             f"{emoji} От {forecast.get('t_min', '?')}°C до {forecast.get('t_max', '?')}°C\n"
                             f"🌧 Осадки: {forecast.get('rain', '?')} мм")
            elif days_until > 3:
                text += f"_Прогноз погоды будет доступен за 3 дня до гонки._"

        await tmp_msg.edit_text(text, parse_mode="Markdown")
    except Exception as e: 
        print(e)
        await tmp_msg.edit_text("🤷‍♂️ Ошибка парсинга.")

@dp.message(F.text == '🏁 Последняя гонка')
async def process_last_race(message: types.Message):
    add_user(message.chat.id, message.from_user.first_name)
    tmp_msg = await message.answer("🔄 Загружаю результаты...")
    data = await fetch_f1_data("current/last/results")
    if not data: return await tmp_msg.edit_text("🤷‍♂️ Ошибка.")
    try:
        race = data['MRData']['RaceTable']['Races'][0]
        text = f"🏁 *Итоги: {race['raceName']}*\n\n"
        for res in race['Results'][:5]:
            text += f"{res['position']}. {res['Driver']['familyName']} ({res['Constructor']['name']}) — {res['points']} очков\n"
            
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏱ Пит-стопы", callback_data="last_race_pits"),
             InlineKeyboardButton(text="❌ Сходы", callback_data="last_race_dnfs")]
        ])
        await tmp_msg.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except: await tmp_msg.edit_text("🤷‍♂️ Ошибка парсинга.")

@dp.callback_query(F.data == 'last_race_pits')
async def process_last_pits(callback: types.CallbackQuery):
    data = await fetch_f1_data("current/last/pitstops", params={"limit": 100})
    if not data: return await callback.answer("Данные недоступны", show_alert=True)
    try:
        pits = data['MRData']['RaceTable']['Races'][0]['PitStops']
        valid_pits = [p for p in pits if ':' not in p['duration']]
        sorted_pits = sorted(valid_pits, key=lambda x: float(x['duration']))[:5]
        
        text = "⏱ *Топ-5 быстрых проездов по пит-лейну:*\n_(общее время от заезда до выезда)_\n\n"
        for i, p in enumerate(sorted_pits):
            driver = p['driverId'].replace('_', ' ').title()
            text += f"{i+1}. {driver} — {p['duration']} сек (Круг {p['lap']})\n"
            
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ К результатам гонки", callback_data="last_race_back")]])
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception: await callback.answer("Ошибка парсинга пит-стопов.", show_alert=True)

@dp.callback_query(F.data == 'last_race_dnfs')
async def process_last_dnfs(callback: types.CallbackQuery):
    data = await fetch_f1_data("current/last/results", params={"limit": 100})
    if not data: return await callback.answer("Данные недоступны", show_alert=True)
    try:
        results = data['MRData']['RaceTable']['Races'][0]['Results']
        dnfs = [r for r in results if r['status'] not in ['Finished'] and not r['status'].startswith('+')]
        
        if not dnfs: text = "❌ *Сходов нет!* Все болиды добрались до финиша."
        else:
            text = "❌ *Сходы в гонке:*\n\n"
            for d in dnfs: text += f"• {d['Driver']['familyName']} ({d['Constructor']['name']}) — {d['status']}\n"
                
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ К результатам гонки", callback_data="last_race_back")]])
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception: await callback.answer("Ошибка парсинга сходов.", show_alert=True)

@dp.callback_query(F.data == 'last_race_back')
async def process_last_race_back(callback: types.CallbackQuery):
    data = await fetch_f1_data("current/last/results")
    if not data: return await callback.answer("Ошибка")
    try:
        race = data['MRData']['RaceTable']['Races'][0]
        text = f"🏁 *Итоги: {race['raceName']}*\n\n"
        for res in race['Results'][:5]:
            text += f"{res['position']}. {res['Driver']['familyName']} ({res['Constructor']['name']}) — {res['points']} очков\n"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏱ Пит-стопы", callback_data="last_race_pits"),
             InlineKeyboardButton(text="❌ Сходы", callback_data="last_race_dnfs")]
        ])
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except: pass

@dp.message(F.text == '🏆 Личный зачет')
async def process_drivers(message: types.Message):
    add_user(message.chat.id, message.from_user.first_name)
    tmp_msg = await message.answer("🔄 Загружаю...")
    data = await fetch_f1_data("current/driverStandings", params={"limit": 10})
    if not data: return await tmp_msg.edit_text("🤷‍♂️ Ошибка.")
    try:
        text = "🏆 *Личный зачет (Топ-10):*\n\n"
        for driver in data['MRData']['StandingsTable']['StandingsLists'][0]['DriverStandings']:
            text += f"{driver['position']}. {driver['Driver']['familyName']} — {driver['points']} очков\n"
        await tmp_msg.edit_text(text, parse_mode="Markdown")
    except: await tmp_msg.edit_text("🤷‍♂️ Данные недоступны.")

@dp.message(F.text == '🏎 Кубок конструкторов')
async def process_teams(message: types.Message):
    add_user(message.chat.id, message.from_user.first_name)
    tmp_msg = await message.answer("🔄 Загружаю...")
    data = await fetch_f1_data("current/constructorStandings")
    if not data: return await tmp_msg.edit_text("🤷‍♂️ Ошибка.")
    try:
        text = "🏎 *Кубок конструкторов:*\n\n"
        for team in data['MRData']['StandingsTable']['StandingsLists'][0]['ConstructorStandings']:
            text += f"{team['position']}. {team['Constructor']['name']} — {team['points']} очков\n"
        await tmp_msg.edit_text(text, parse_mode="Markdown")
    except: await tmp_msg.edit_text("🤷‍♂️ Данные недоступны.")


@dp.message(Command('alarm'))
async def cmd_alarm(message: types.Message):
    if message.from_user.id != 733477024:
        return
        
    users = get_user_settings()
    success = 0
    
    await message.answer("🔄 Начинаю рассылку...")
    
    for user in users:
        try:
            await bot.send_message(user['chat_id'], "Пропишите /start для обновления бота")
            success += 1
            await asyncio.sleep(0.05) 
        except:
            pass
            
    await message.answer(f"✅ Рассылка успешно завершена! Доставлено: {success} пользователям.")

async def main():
    init_db()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_schedule_and_notify, 'interval', minutes=5)
    scheduler.add_job(check_race_results, 'interval', minutes=15) 
    scheduler.add_job(check_and_send_news, 'interval', hours=3)
    scheduler.add_job(check_gacha_reminders, 'interval', minutes=5)
    scheduler.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())