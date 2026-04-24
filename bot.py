import asyncio
import logging
from db.engine import init_db
from aiogram import Bot, Dispatcher
from config import Config
from handlers import start, analysis
from aiogram.fsm.storage.memory import MemoryStorage

async def main():

    logging.basicConfig(level=logging.INFO)
    
    bot = Bot(token=Config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_routers(
        start.router,
        analysis.router
    )

    logging.info("Бот працює в штатному режимі!")
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бота вимкнено!")