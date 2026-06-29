import time
import random
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
import asyncio


from config import DB_PATH
import data
from database import add_user, update_notify_time, get_user_settings
from api import fetch_f1_data, fetch_weather, get_weather_emoji
from utils import get_reply_keyboard, generate_drivers_kb, extract_all_sessions
from services import get_gacha_text_and_kb, get_detailed_profile_text, get_leaderboard_text_and_kb
from states import Archive, Predict
from loader import bot, dp
from tasks import check_and_send_news

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
        try:
            user_data = c.execute("SELECT last_pull_time, special_pity, legendary_pity, mythic_pity, epic_pity, total_pulls FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
        except sqlite3.OperationalError:
            # На случай, если кто-то нажмет кнопку до того, как база обновится
            user_data = c.execute("SELECT last_pull_time, special_pity, legendary_pity, mythic_pity, epic_pity FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
            user_data = (*user_data, 0)
            
        last_pull = user_data[0]
        sp_pity = user_data[1]
        leg_pity = user_data[2]
        myth_pity = user_data[3]
        epic_pity = user_data[4]
        total_pulls = user_data[5] if user_data[5] is not None else 0
        
        if now - last_pull < cooldown:
            rem = cooldown - (now - last_pull)
            h = rem // 3600
            m = (rem % 3600) // 60
            await callback.answer(f"⏳ Следующее открытие будет доступно через {h} ч. {m} мин.", show_alert=True)
            return
            
        total_pulls += 1
        is_hard_pity = False
        
        # Проверяем жесткий гарант
        if total_pulls % 140 == 0:
            rarity = "special"
            is_hard_pity = True
            new_sp_pity, new_leg_pity, new_myth_pity, new_epic_pity = sp_pity, leg_pity, myth_pity, epic_pity
        elif total_pulls % 70 == 0:
            rarity = "legendary"
            is_hard_pity = True
            new_sp_pity, new_leg_pity, new_myth_pity, new_epic_pity = sp_pity, leg_pity, myth_pity, epic_pity
        else:
            sp_chance = 0.01 + sp_pity
            leg_chance = 0.1 + leg_pity
            myth_chance = 1.0 + myth_pity
            epic_chance = 4.0 + epic_pity
            
            roll = random.uniform(0, 100)
            
            if roll <= sp_chance:
                rarity = "special"
                new_sp_pity = 0.0 
                new_leg_pity = leg_pity + 0.05 
                new_myth_pity = myth_pity + 0.1
                new_epic_pity = epic_pity + 0.2
            elif roll <= sp_chance + leg_chance:
                rarity = "legendary"
                new_sp_pity = sp_pity + 0.01
                new_leg_pity = 0.0 
                new_myth_pity = myth_pity + 0.1
                new_epic_pity = epic_pity + 0.2
            elif roll <= sp_chance + leg_chance + myth_chance:
                rarity = "mythic"
                new_sp_pity, new_leg_pity = sp_pity + 0.01, leg_pity + 0.05
                new_myth_pity = 0.0
                new_epic_pity = epic_pity + 0.2
            elif roll <= sp_chance + leg_chance + myth_chance + epic_chance:
                rarity = "epic"
                new_sp_pity, new_leg_pity = sp_pity + 0.01, leg_pity + 0.05
                new_myth_pity = myth_pity + 0.1
                new_epic_pity = 0.0
            elif roll <= sp_chance + leg_chance + myth_chance + epic_chance + 25.0:
                rarity = "rare"
                new_sp_pity, new_leg_pity = sp_pity + 0.01, leg_pity + 0.05
                new_myth_pity = myth_pity + 0.1
                new_epic_pity = epic_pity + 0.2
            else:
                rarity = "common"
                new_sp_pity, new_leg_pity = sp_pity + 0.01, leg_pity + 0.05
                new_myth_pity = myth_pity + 0.1
                new_epic_pity = epic_pity + 0.2
        
        driver = random.choice(data.DRIVERS_DB[rarity])
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
        
        try:
            c.execute("UPDATE users SET last_pull_time = ?, special_pity = ?, legendary_pity = ?, mythic_pity = ?, epic_pity = ?, total_pulls = ?, reminded = 0 WHERE chat_id = ?", 
                      (now, new_sp_pity, new_leg_pity, new_myth_pity, new_epic_pity, total_pulls, chat_id))
        except sqlite3.OperationalError:
            # Если база еще не обновилась
            c.execute("UPDATE users SET last_pull_time = ?, special_pity = ?, legendary_pity = ?, mythic_pity = ?, epic_pity = ?, reminded = 0 WHERE chat_id = ?", 
                      (now, new_sp_pity, new_leg_pity, new_myth_pity, new_epic_pity, chat_id))

    rarity_name = data.RARITY_INFO[rarity]['name']
    prefix = "🛡 *ГАРАНТ!*\n" if is_hard_pity else ""
    msg = f"{prefix}Выпал {rarity_name} {driver['name']} " + ("*(Дубликат! ✨ +{} XP)*".format(reward) if is_duplicate else "🎉")
    msg += "\nСледующее открытие будет доступно через 6 часов."
           
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад в Гараж", callback_data="back_to_gacha")]])
    await callback.message.edit_text(msg, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data == 'back_to_gacha')
async def back_to_gacha(callback: types.CallbackQuery):
    text, kb = get_gacha_text_and_kb(callback.message.chat.id)
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    await callback.answer()


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
        
        race_date = race.get('date')
        race_time = race.get('time', '00:00:00Z')
        
        if race_date and race_time:
            start_dt = datetime.strptime(f"{race_date} {race_time}", "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC"))
            now_utc = datetime.now(ZoneInfo("UTC"))
            
            if now_utc >= start_dt:
                return await tmp_msg.edit_text(f"🚫 *Прием прогнозов закрыт!*\n\nГонка {race_name} уже началась. Увидимся на следующем этапе!", parse_mode="Markdown")

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