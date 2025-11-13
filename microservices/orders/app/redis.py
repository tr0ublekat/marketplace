import json
import os
from contextlib import asynccontextmanager

import redis.asyncio as redis
from app.logger import logger
from app.models import Product
from sqlalchemy import select


class RedisCache:
    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.client = None

    async def connect(self):
        self.client = redis.from_url(
            self.redis_url, encoding="utf-8", decode_responses=True
        )

    async def disconnect(self):
        if self.client:
            await self.client.close()

    async def get_product_price(self, product_id: int) -> float | None:
        if not self.client:
            return None

        price = await self.client.get(f"product_price:{product_id}")
        return float(price) if price else None

    async def set_product_price(
        self, product_id: int, price: float, expire: int = 3600
    ):
        if self.client:
            await self.client.setex(f"product_price:{product_id}", expire, str(price))

    async def get_product_prices_bulk(self, product_ids: list[int]) -> dict[int, float]:
        if not self.client:
            return {}

        keys = [f"product_price:{pid}" for pid in product_ids]
        values = await self.client.mget(keys)

        result = {}
        for product_id, price in zip(product_ids, values):
            if price is not None:
                result[product_id] = float(price)

        return result

    async def set_product_prices_bulk(
        self, price_dict: dict[int, float], expire: int = 3600
    ):
        if not self.client:
            return

        pipeline = self.client.pipeline()
        for product_id, price in price_dict.items():
            pipeline.setex(f"product_price:{product_id}", expire, str(price))
        await pipeline.execute()

    async def preload_all_prices(self, db_session):
        """Предзагружаем все цены товаров в Redis при старте"""
        result = await db_session.execute(select(Product.id, Product.price))
        all_prices = {row.id: row.price for row in result.all()}
        await self.set_product_prices_bulk(all_prices, expire=86400)  # 24 часа
        logger.info(f"Preloaded {len(all_prices)} product prices to Redis")


redis_cache = RedisCache()
