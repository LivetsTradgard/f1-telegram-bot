import os
import asyncio
import aiohttp
from datetime import datetime
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')

if not TOKEN:
    print("❌ Ошибка: Переменная BOT_TOKEN не найдена!")
    exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher()

API_URL = "https://api.jolpi.ca/ergast/f1"

async def fetch_f1_data(endpoint: str) -> dict:
    async with aiohttp.ClientSession() as session:
        # таймаут
        async with session.get(f"{API_URL}/{endpoint}.json", timeout=10) as response:
            if response.status == 200:
                return await response.json()
            return None

def get_main_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(text="📅 Ближайший этап", callback_data='next_race'),
            InlineKeyboardButton(text="🏁 Последняя гонка", callback_data='last_race')
        ],
        [
            InlineKeyboardButton(text="🏆 Личный зачет", callback_data='standings_drivers'),
            InlineKeyboardButton(text="🏎 Кубок конструкторов", callback_data='standings_teams')
        ],
        [
            InlineKeyboardButton(text="📊 Сравнение телеметрии", callback_data='telemetry')
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    welcome_text = (
        "Привет! 🏎💨\n\n"
        "Я — бот-помощник по Формуле-1. Я подключен к живой базе данных и знаю всё о текущем сезоне.\n"
        "Выбери нужный раздел:"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard())


@dp.callback_query(F.data == 'next_race')
async def process_next_race(callback: types.CallbackQuery):
    await callback.answer("Загружаю расписание...")
    data = await fetch_f1_data("current/next")
    
    if not data:
        await callback.message.answer("❌ Ошибка получения данных от API.")
        return

    try:
        race = data['MRData']['RaceTable']['Races'][0]
        race_name = race['raceName']
        circuit = race['Circuit']['circuitName']
        country = race['Circuit']['Location']['country']
        date = race['date']
        time = race.get('time', 'Время не указано').replace('Z', '') # UTC время
        
        text = (
            f"📅 *Ближайший уик-энд:*\n\n"
            f"🏎 *{race_name}*\n"
            f"📍 Трасса: {circuit} ({country})\n"
            f"🏁 Старт гонки: {date} в {time} (UTC)\n\n"
            f"_(Время указано по Гринвичу, прибавь свой часовой пояс)_"
        )
    except (KeyError, IndexError):
        text = "🤷‍♂️ Не удалось распарсить данные о следующей гонке. Возможно, сезон окончен."
        
    await callback.message.answer(text, parse_mode="Markdown")


@dp.callback_query(F.data == 'last_race')
async def process_last_race(callback: types.CallbackQuery):
    await callback.answer("Загружаю результаты...")
    data = await fetch_f1_data("current/last/results")
    
    if not data:
        await callback.message.answer("❌ Ошибка получения данных.")
        return

    try:
        race = data['MRData']['RaceTable']['Races'][0]
        race_name = race['raceName']
        results = race['Results'][:5] # Берем Топ-5
        
        text = f"🏁 *Итоги: {race_name}*\n\n"
        for res in results:
            pos = res['position']
            driver = res['Driver']['familyName']
            team = res['Constructor']['name']
            points = res['points']
            text += f"{pos}. {driver} ({team}) — {points} очков\n"
    except (KeyError, IndexError):
        text = "🤷‍♂️ Не удалось загрузить результаты."
        
    await callback.message.answer(text, parse_mode="Markdown")


@dp.callback_query(F.data == 'standings_drivers')
async def process_drivers(callback: types.CallbackQuery):
    await callback.answer("Загружаю таблицу...")
    data = await fetch_f1_data("current/driverStandings")
    
    if not data:
        await callback.message.answer("❌ Ошибка получения данных.")
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
        
    await callback.message.answer(text, parse_mode="Markdown")


@dp.callback_query(F.data == 'standings_teams')
async def process_teams(callback: types.CallbackQuery):
    await callback.answer("Загружаю Кубок...")
    data = await fetch_f1_data("current/constructorStandings")
    
    if not data:
        await callback.message.answer("❌ Ошибка получения данных.")
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
        
    await callback.message.answer(text, parse_mode="Markdown")


@dp.callback_query(F.data == 'telemetry')
async def process_telemetry(callback: types.CallbackQuery):
    await callback.answer()
    text = (
        "📊 *Модуль телеметрии*\n"
        "Эта фича находится в разработке (Phase 2). Здесь мы будем парсить "
        "сырые данные через FastF1 и строить крутые графики прохождения секторов!"
    )
    await callback.message.answer(text, parse_mode="Markdown")


async def main():
    print("🏎 F1 Bot запущен и готов к работе...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())