from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
import os

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(
    str(DATABASE_URL),
    echo=False,
    pool_size=10,
    max_overflow=5,
    pool_timeout=30,
    pool_recycle=1800,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)
