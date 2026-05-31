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

class Archive(StatesGroup):
    waiting_for_year = State()

class Predict(StatesGroup):
    waiting_p1 = State()
    waiting_p2 = State()
    waiting_p3 = State()

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY)")
        try:
            c.execute("ALTER TABLE users ADD COLUMN notify_time INTEGER DEFAULT 60")
        except sqlite3.OperationalError:
            pass
            
        try:
            c.execute("ALTER TABLE users ADD COLUMN name TEXT DEFAULT 'Гонщик'")
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

def add_user(chat_id, name=None):
    user_name = name or "Гонщик"
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR IGNORE INTO users (chat_id, notify_time, name) VALUES (?, 60, ?)", (chat_id, user_name))
        conn.execute("UPDATE users SET name = ? WHERE chat_id = ?", (user_name, chat_id))

def update_notify_time(chat_id, minutes):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE users SET notify_time = ? WHERE chat_id = ?", (minutes, chat_id))

def get_user_settings():
    with sqlite3.connect(DB_PATH) as conn:
        return [{"chat_id": row[0], "notify_time": row[1]} for row in conn.execute("SELECT chat_id, notify_time FROM users")]

async def fetch_f1_data(endpoint: str, params: dict = None) -> dict:
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        headers = {"User-Agent": "F1TelegramBot/1.0"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(f"{API_URL}/{endpoint}.json", params=params) as response:
                if response.status == 200:
                    return await response.json()
                return None
    except Exception as e:
        print(f"API Error ({endpoint}): {e}")
        return None

def get_reply_keyboard():
    keyboard = [
        [KeyboardButton(text="📅 Ближайший этап"), KeyboardButton(text="🏁 Последняя гонка")],
        [KeyboardButton(text="🏆 Личный зачет"), KeyboardButton(text="🏎 Кубок конструкторов")],
        [KeyboardButton(text="🔎 Инфо и Профили"), KeyboardButton(text="📜 Архив сезонов")],
        [KeyboardButton(text="🔮 Прогнозы на подиум"), KeyboardButton(text="📊 Рейтинг игроков")],
        [KeyboardButton(text="⏱ Live-тайминг"), KeyboardButton(text="⚙️ Настройки")]
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
            
        
            if sess['name'] == '🏁 Главная гонка' and 1435 < delta_minutes <= 1440:
                for user in users:
                    msg = (f"⏳ До старта {race_name} остались ровно сутки!\n\n"
                           f"Самое время сделать прогноз на подиум. Нажми кнопку «🔮 Прогнозы на подиум» в меню, "
                           f"чтобы проверить свою интуицию!")
                    try:
                        await bot.send_message(user['chat_id'], msg)
                    except:
                        pass

        
            for user in users:
                offset = user['notify_time']
                if offset == 0:
                    continue
                    
                if offset - 5 < delta_minutes <= offset:
                    dt_moscow = dt_utc.astimezone(ZoneInfo("Europe/Moscow")).strftime("%H:%M")
                    if offset == 1440: time_str = "ровно через 24 часа"
                    elif offset >= 60: time_str = f"через {offset // 60} час(а)"
                    else: time_str = f"через {offset} минут"
                        
                    msg = f"🔔 *Напоминание!*\n\n{sess['name']} в рамках {race_name} начнется {time_str} (в {dt_moscow} по Мск)!"
                    try:
                        await bot.send_message(user['chat_id'], msg, parse_mode="Markdown")
                    except:
                        pass
    except Exception:
        pass

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
                
                # точность
                for i in range(3):
                    if pred_podium[i] == actual_podium[i]:
                        score += 33.34  # найс в 10 попал
                    elif pred_podium[i] in actual_podium:
                        score += 16.67  # ай скосил бывает
                        
                percent = round(score)
                if percent >= 99: percent = 100
                
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
                       f"🎯 *Точность твоего прогноза: {percent}%*")
                
                try:
                    await bot.send_message(chat_id, msg, parse_mode="Markdown")
                except:
                    pass
                
                # прогноз уже был
                conn.execute("UPDATE predictions SET scored = 1, accuracy = ? WHERE chat_id = ? AND race_id = ?", (percent, chat_id, race_id))
    except Exception as e:
        print(f"Results scoring error: {e}")

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    add_user(message.chat.id, message.from_user.first_name)
    user_name = message.from_user.first_name or "фанат автоспорта"
    welcome_text = (f"Привет, {user_name}! 🏎💨\n\nЯ — твой личный бот-помощник по Формуле-1.\n"
                    f"Используй кнопки внизу для навигации!")
    await message.answer(welcome_text, reply_markup=get_reply_keyboard())

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
    if not next_race_data:
        return await tmp_msg.edit_text("❌ Ошибка соединения с API.")
        
    try:
        race = next_race_data['MRData']['RaceTable']['Races'][0]
        race_id = f"{race['season']}_{race['round']}"
        race_name = race['raceName']
        
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            existing = c.execute("SELECT p1, p2, p3 FROM predictions WHERE chat_id = ? AND race_id = ?", (message.chat.id, race_id)).fetchone()
            
        if existing:
            return await tmp_msg.edit_text(f"✅ Ты уже сделал прогноз на {race_name}!\nЖди завершения гонки для подсчета очков.")
            
        drivers_data = await fetch_f1_data("current/driverStandings", params={"limit": 100})
        raw_drivers = drivers_data['MRData']['StandingsTable']['StandingsLists'][0]['DriverStandings']
        drivers_list = [{'id': d['Driver']['driverId'], 'name': d['Driver']['familyName']} for d in raw_drivers]
        
        await state.update_data(race_id=race_id, race_name=race_name, drivers=drivers_list, selected=[])
        await state.set_state(Predict.waiting_p1)
        
        kb = generate_drivers_kb(drivers_list)
        await tmp_msg.edit_text(f"🔮 *Прогноз на {race_name}*\n\n🥇 Выбери гонщика, который займет **ПЕРВОЕ** место:", parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await tmp_msg.edit_text("❌ Ошибка формирования прогноза.")

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
    
    if not current_state:
        return await callback.answer("Сессия устарела. Начни заново.", show_alert=True)
        
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
                f"Бот пришлет результаты и начислит % точности сразу после гонки!")
        await callback.message.edit_text(text, parse_mode="Markdown")
        
    await callback.answer()

@dp.message(F.text == '📊 Рейтинг игроков')
async def process_leaderboard(message: types.Message):
    add_user(message.chat.id, message.from_user.first_name)
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        data = c.execute("""
            SELECT u.name, AVG(p.accuracy), COUNT(p.race_id)
            FROM predictions p
            JOIN users u ON p.chat_id = u.chat_id
            WHERE p.scored = 1
            GROUP BY p.chat_id
            ORDER BY AVG(p.accuracy) DESC, COUNT(p.race_id) DESC
            LIMIT 10
        """).fetchall()
        
    if not data:
        return await message.answer("📊 *Рейтинг пока пуст.*\nДождитесь расчета первых прогнозов после гонки!", parse_mode="Markdown")
        
    text = "📊 *Глобальный рейтинг интуиции (Топ-10):*\n\n"
    for i, (name, avg_acc, count) in enumerate(data):
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
        text += f"{medal} {name} — {int(avg_acc)}% (прогнозов: {count})\n"
        
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == '⏱ Live-тайминг')
async def process_live_timing(message: types.Message):
    add_user(message.chat.id, message.from_user.first_name)
    text = ("⏱ *Текстовый Live-тайминг*\n\n"
            "📡 Модуль подключается к серверам трансляции...\n\n"
            "_(Примечание: Прямо сейчас активных сессий нет или бесплатное API задерживает данные. "
            "Обычно телеметрия обновляется через некоторое время после клетчатого флага)_")
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
        text = (f"📍 *{circuit.get('circuitName', '')}*\n🏙 Город: {loc.get('locality', '')}\n"
                f"🌍 Страна: {loc.get('country', '')}\n🔗 [Википедия]({circuit.get('url', '')})")
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_info")]])
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)
    except: pass
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
    await message.answer("Введите год (с 1950 по текущий), чтобы получить итоги сезона (Топ-5 пилотов):", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(Archive.waiting_for_year)

@dp.message(Archive.waiting_for_year)
async def process_archive_year(message: types.Message, state: FSMContext):
    year_str = message.text.strip()
    if not year_str.isdigit() or not (1950 <= int(year_str) <= datetime.now().year):
        return await message.answer("❌ Пожалуйста, введите корректный год.")
    await state.clear()
    tmp_msg = await message.answer(f"🔄 Извлекаю топ-5 пилотов за {year_str} год...")
    driver_data = await fetch_f1_data(f"{year_str}/driverStandings", params={"limit": 5})
    
    if not driver_data or 'MRData' not in driver_data:
        await tmp_msg.delete()
        return await message.answer("❌ Ошибка сервера.", reply_markup=get_reply_keyboard())

    try:
        standings = driver_data['MRData']['StandingsTable']['StandingsLists'][0]['DriverStandings']
        text = f"📜 *Итоги сезона {year_str} (Топ-5)*\n\n"
        for i, d in enumerate(standings):
            name = f"{d['Driver']['givenName']} {d['Driver']['familyName']}"
            team = d['Constructors'][0]['name'] if d.get('Constructors') else "Неизвестно"
            pts = d['points']
            if i == 0: text += f"👑 *Чемпион:* {name} ({team}) — {pts} очков\n\n*Остальные лидеры:*\n"
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
        schedule_by_date, ru_days = {}, {0: 'Пн', 1: 'Вт', 2: 'Ср', 3: 'Чт', 4: 'Пт', 5: 'Сб', 6: 'Вс'}
        for sess in extract_all_sessions(race):
            if not sess['date'] or not sess['time']: continue
            dt = datetime.strptime(f"{sess['date']} {sess['time']}", "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Moscow"))
            date_key = f"{ru_days[dt.weekday()]}, {dt.strftime('%d.%m')}"
            schedule_by_date.setdefault(date_key, []).append(f"{dt.strftime('%H:%M')} — {sess['name']}")
        
        text = f"📅 *{race['raceName']}*\n\n"
        for date_key, events in schedule_by_date.items(): text += f"*{date_key}:*\n" + "\n".join(events) + "\n\n"
        await tmp_msg.edit_text(text, parse_mode="Markdown")
    except: await tmp_msg.edit_text("🤷‍♂️ Ошибка парсинга.")

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
    if not data:
        return await callback.answer("Данные недоступны", show_alert=True)
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
    except Exception:
        await callback.answer("Ошибка парсинга пит-стопов.", show_alert=True)

@dp.callback_query(F.data == 'last_race_dnfs')
async def process_last_dnfs(callback: types.CallbackQuery):
    data = await fetch_f1_data("current/last/results", params={"limit": 100})
    if not data:
        return await callback.answer("Данные недоступны", show_alert=True)
    try:
        results = data['MRData']['RaceTable']['Races'][0]['Results']
        dnfs = [r for r in results if r['status'] not in ['Finished'] and not r['status'].startswith('+')]
        
        if not dnfs:
            text = "❌ *Сходов нет!* Все болиды добрались до финиша."
        else:
            text = "❌ *Сходы в гонке:*\n\n"
            for d in dnfs:
                text += f"• {d['Driver']['familyName']} ({d['Constructor']['name']}) — {d['status']}\n"
                
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ К результатам гонки", callback_data="last_race_back")]])
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await callback.answer("Ошибка парсинга сходов.", show_alert=True)

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

async def main():
    init_db()
    
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_schedule_and_notify, 'interval', minutes=5)
    scheduler.add_job(check_race_results, 'interval', minutes=15) 
    scheduler.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())