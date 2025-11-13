import json
import os
import random
import asyncio
import requests
from sqlalchemy import Column, ForeignKey, Integer, String, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    price = Column(Integer)


engine = create_async_engine(
    str("postgresql+asyncpg://psql_user:psql_password@localhost:5432/go_esb"),
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
    url = "https://dummyjson.com/products?limit=1000"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    response = requests.get(url, headers=headers)

    products = {}
    for product in response.json()["products"]:
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
