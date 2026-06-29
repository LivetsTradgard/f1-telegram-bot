import time
import sqlite3
import aiohttp
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

from config import DB_PATH
from database import get_user_settings
from api import fetch_f1_data
from utils import extract_all_sessions
from loader import bot


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