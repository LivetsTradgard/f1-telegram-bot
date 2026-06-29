import sqlite3
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import DB_PATH
import data
from utils import get_rank_info

def get_gacha_text_and_kb(chat_id: int):
    total_drivers = sum(len(cat) for cat in data.DRIVERS_DB.values())
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        
        try:
            pulls_data = c.execute("SELECT total_pulls FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
            total_pulls = pulls_data[0] if pulls_data and pulls_data[0] is not None else 0
        except sqlite3.OperationalError:
            total_pulls = 0
            
        count = c.execute("SELECT SUM(count) FROM inventory WHERE chat_id = ?", (chat_id,)).fetchone()[0] or 0
        unique = c.execute("SELECT COUNT(*) FROM inventory WHERE chat_id = ?", (chat_id,)).fetchone()[0] or 0
        cards = c.execute("SELECT driver_id, rarity, count FROM inventory WHERE chat_id = ? ORDER BY count DESC", (chat_id,)).fetchall()
        
    next_leg = 70 - (total_pulls % 70)
    next_spec = 140 - (total_pulls % 140)
        
    text = (f"🎴 *Твой гараж*\n\n"
            f"Прогресс коллекции: {unique} из {total_drivers} пилотов\n"
            f"Всего карточек: {count}\n"
            f"🔄 Открыто паков: {total_pulls}\n\n"
            f"🟡 Гарант на Легенду через: {next_leg}\n"
            f"✨ Гарант на Особую через: {next_spec}\n\n")
            
    if not cards:
        text += "_Твоя коллекция пока пуста. Нажми «Открыть», чтобы получить первого пилота!_\n"
    else:
        text += "*Текущая коллекция:*\n"
        collection = {"special": [], "legendary": [], "mythic": [], "epic": [], "rare": [], "common": []}
        all_drivers = {d['id']: d for category in data.DRIVERS_DB.values() for d in category}
        
        for d_id, rarity, cnt in cards:
            if d_id in all_drivers:
                collection[rarity].append((all_drivers[d_id], cnt))
                
        for rarity in ["special", "legendary", "mythic", "epic", "rare", "common"]:
            if collection[rarity]:
                text += f"{data.RARITY_INFO[rarity]['name']}:\n"
                for driver, cnt in collection[rarity]:
                    cnt_str = f" x{cnt}" if cnt > 1 else ""
                    text += f"  {driver['emoji']} {driver['name']}{cnt_str}\n"
                text += "\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Открыть", callback_data="pull_card")]
    ])
    
    return text, kb

def get_detailed_profile_text(chat_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        user_data = c.execute("SELECT name, xp, special_pity, legendary_pity, mythic_pity, epic_pity FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
        if not user_data: return "Пользователь не найден."
        user_name, xp, sp_pity, leg_pity, myth_pity, epic_pity = user_data
        
        stats = c.execute("SELECT AVG(accuracy), COUNT(race_id) FROM predictions WHERE chat_id = ? AND scored = 1", (chat_id,)).fetchone()
        
        active_condition = "(last_pull_time > 0 OR chat_id IN (SELECT chat_id FROM predictions))"
        rank_query = c.execute(f"SELECT COUNT(*) FROM users WHERE xp > ? AND {active_condition}", (xp,)).fetchone()[0]
        place = rank_query + 1 
        total_players = c.execute(f"SELECT COUNT(*) FROM users WHERE {active_condition}").fetchone()[0]
        
        cards = c.execute("SELECT driver_id, rarity, count FROM inventory WHERE chat_id = ?", (chat_id,)).fetchall()
        total_drivers = sum(len(cat) for cat in data.DRIVERS_DB.values())
        unique = len(cards)
        
    rank_name, next_xp = get_rank_info(xp)
    
    text = f"👤 *Профиль: {user_name}*\n\n⚜️ *Звание:* {rank_name}\n✨ *Опыт:* {xp} XP\n"
    if next_xp: text += f"📈 *До след. ранга:* {next_xp - xp} XP\n\n"
    else: text += f"🌟 *Достигнут максимальный ранг!*\n\n"
    
    text += f"🎴 *Собрано пилотов:* {unique} из {total_drivers}\n"
    text += f"🍀 *Текущий шанс на Особую:* {0.01 + sp_pity:.2f}%\n"
    text += f"🟡 *Текущий шанс на Легенду:* {0.1 + leg_pity:.2f}%\n"
    text += f"🟣 *Текущий шанс на Мифик:* {1.0 + myth_pity:.2f}%\n"
    text += f"🔵 *Текущий шанс на Эпик:* {4.0 + epic_pity:.2f}%\n\n"
    
    if unique > 0:
        text += "*Топ-5 карточек в гараже:*\n"
        rarity_weight = {"special": 5, "legendary": 4, "mythic": 3, "epic": 2, "rare": 1, "common": 0}
        all_drivers = {d['id']: d for category in data.DRIVERS_DB.values() for d in category}
        sorted_cards = sorted(cards, key=lambda x: (rarity_weight.get(x[1], 0), x[2]), reverse=True)
        
        for d_id, rarity, cnt in sorted_cards[:5]:
            d = all_drivers.get(d_id)
            if d: text += f"• {data.RARITY_INFO[rarity]['name'].split(' ')[0]} {d['emoji']} {d['name']} (x{cnt})\n"
        text += "\n"
        
    if stats[1] > 0 and stats[0] is not None:
        text += (f"🎯 *Точность прогнозов:* {int(stats[0])}%\n"
                 f"🏁 *Сделано прогнозов:* {stats[1]}\n"
                 f"🏆 *Место в рейтинге:* {place} из {max(1, total_players)}\n")
    return text

def get_leaderboard_text_and_kb():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        data_rows = c.execute("""
            SELECT u.chat_id, u.name, u.xp, COALESCE(AVG(p.accuracy), 0),
                   (SELECT COUNT(DISTINCT driver_id) FROM inventory WHERE chat_id = u.chat_id) as cards_count
            FROM users u
            LEFT JOIN predictions p ON u.chat_id = p.chat_id AND p.scored = 1
            WHERE u.last_pull_time > 0 OR u.chat_id IN (SELECT chat_id FROM predictions)
            GROUP BY u.chat_id
            ORDER BY u.xp DESC, AVG(p.accuracy) DESC
            LIMIT 10
        """).fetchall()
        
    if not data_rows: 
        return "📊 *Рейтинг пока пуст.*", None
        
    text = "📊 *Глобальный рейтинг (Топ-10):*\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    
    for i, (uid, name, xp, avg_acc, cards_count) in enumerate(data_rows):
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
        rank_name, _ = get_rank_info(xp)
        cards_count = cards_count if cards_count else 0
        
        text += f"{medal} *{name}* — {xp} XP\n_{rank_name}_ | 🎴 Пилотов: {cards_count}\n\n"
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"{medal} Профиль: {name}", callback_data=f"show_prof_{uid}")])
        
    text += "_Нажми на игрока ниже, чтобы посмотреть его профиль!_"
    return text, kb