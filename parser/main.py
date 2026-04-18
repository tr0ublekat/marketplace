import json
import os
import random
import asyncio
from dotenv import load_dotenv
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

load_dotenv(dotenv_path="../.env")

Base = declarative_base()


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    price = Column(Integer)


POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
POSTGRES_DB = os.getenv("POSTGRES_DB")
DATABASE_URL = f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@localhost:5444/{POSTGRES_DB}"

engine = create_async_engine(
    DATABASE_URL,
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


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# Пример получения товаров из DNS
async def get_dns_products():
    # url = "https://dummyjson.com/products?limit=1000"

    # headers = {
    #     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    #     "Accept": "application/json",
    # }

    # response = requests.get(url, headers=headers)

    # print('Got data from dummyjson!')

    import json
    products = {}
    with open('data.json') as f:
        products_data = json.load(f)

    for product in products_data["products"]:
        unit_price = random.randint(1000, 15000)
        name = product["title"]

        products[name] = unit_price

    # add to database
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for name, price in products.items():
            product = Product(name=name, price=price)
            await conn.execute(product.__table__.insert(), product.__dict__)


if __name__ == "__main__":
    asyncio.run(get_dns_products())
