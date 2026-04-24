#ТЕСТОВИЙ ФАЙЛИК ДЛЯ ПЕРЕВІРКИ ЗВ'ЯЗКУ З ЛОКАЛЬНОЮ БД
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from config import Config

async def test_conn():
    try:
        engine = create_async_engine(Config.DB_URL)
        async with engine.connect() as conn:
            print("З'єднання з MSSQL встановлено!")
    except Exception as e:
        print(f"Помилка підключення {e}")

if __name__ == "__main__":
    asyncio.run(test_conn())