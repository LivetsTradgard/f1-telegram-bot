import sqlite3
from config import DB_PATH

#цены обмена дубликатов
EXCHANGE_RATES = {
    "common": 200,
    "rare": 400,
    "epic": 800,
    "mythic": 1500,
    "legendary": 3000,
    "special": 6000
}

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
                                       ("mythic_pity", "REAL", "0.0"),
                                       ("epic_pity", "REAL", "0.0"),
                                       ("total_pulls", "INTEGER", "0"),
                                       ("reminded", "INTEGER", "0"),
                                       ("balance", "INTEGER", "1000")]: #добавка баланса
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

# НОВЫЕ ФУНКЦИИ ЭКОНОМИКИ

def get_balance(chat_id: int) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        res = conn.execute("SELECT balance FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
        return res[0] if res else 1000

def update_balance(chat_id: int, amount: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE users SET balance = balance + ? WHERE chat_id = ?", (amount, chat_id))

def get_user_duplicates(chat_id: int) -> list:
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT driver_id, rarity, count FROM inventory WHERE chat_id = ? AND count > 1", (chat_id,)).fetchall()

def exchange_duplicate(chat_id: int, driver_id: str, rarity: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        res = conn.execute("SELECT count FROM inventory WHERE chat_id = ? AND driver_id = ?", (chat_id, driver_id)).fetchone()
        if res and res[0] > 1:
            conn.execute("UPDATE inventory SET count = count - 1 WHERE chat_id = ? AND driver_id = ?", (chat_id, driver_id))
            reward = EXCHANGE_RATES.get(rarity, 0)
            conn.execute("UPDATE users SET balance = balance + ? WHERE chat_id = ?", (reward, chat_id))
            return True
    return False