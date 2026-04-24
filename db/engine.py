from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config import Config

DATABASE_URL = Config.DB_URL 

engine = create_async_engine(DATABASE_URL, echo=True)
async_session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    from db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)