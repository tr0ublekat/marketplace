from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
import os

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(str(DATABASE_URL), echo=True, pool_size=20, max_overflow=10)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)
