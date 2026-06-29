from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

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