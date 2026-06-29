import os
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import init_db
from loader import bot, dp
from tasks import check_schedule_and_notify, check_race_results, check_and_send_news, check_gacha_reminders
import handlers

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