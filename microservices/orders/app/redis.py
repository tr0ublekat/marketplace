import json
import os
import asyncio
from contextlib import asynccontextmanager

import redis.asyncio as redis
from app.logger import logger
from app.models import Product
from sqlalchemy import select


class RedisCache:
    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.client = None
        self.preload_lock_key = "preload_prices_lock"
        self.preload_complete_key = "preload_prices_complete"

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
        """Предзагружаем все цены товаров в Redis с блокировкой"""
        # Проверяем, не была ли уже выполнена предзагрузка
        if await self.client.get(self.preload_complete_key):
            logger.info("Предзагрузка уже выполнена ранее, пропускаем")
            return

        # Пробуем захватить блокировку
        lock_acquired = await self.client.set(
            self.preload_lock_key,
            "1",
            nx=True,
            ex=30,  # Блокировка на 30 секунд
        )

        if not lock_acquired:
            logger.info("Предзагрузка выполняется другим процессом, ждем...")
            # Ждем пока другой процесс завершит предзагрузку
            await self._wait_for_preload_completion()
            return

        try:
            logger.info("Захватили блокировку для предзагрузки цен")

            # Проверяем еще раз на случай если предзагрузка завершилась пока мы ждали блокировку
            if await self.client.get(self.preload_complete_key):
                logger.info("Предзагрузка уже выполнена, освобождаем блокировку")
                return

            # Выполняем предзагрузку
            result = await db_session.execute(select(Product.id, Product.price))
            all_prices = {row.id: row.price for row in result.all()}

            if all_prices:
                await self.set_product_prices_bulk(all_prices, expire=86400)  # 24 часа

                # Помечаем что предзагрузка завершена
                await self.client.setex(self.preload_complete_key, 86400, "1")
                logger.info(f"Preloaded {len(all_prices)} product prices to Redis")
            else:
                logger.warning("No products found for preloading")

        except Exception as e:
            logger.error(f"Ошибка при предзагрузке цен: {e}")
            # В случае ошибки снимаем блокировку, чтобы другие процессы могли попробовать
            await self.client.delete(self.preload_lock_key)
            raise
        finally:
            # Всегда освобождаем блокировку
            await self.client.delete(self.preload_lock_key)
            logger.info("Блокировка предзагрузки освобождена")

    async def _wait_for_preload_completion(self, timeout: int = 30):
        """Ожидает завершения предзагрузки другим процессом"""
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout:
            # Проверяем завершена ли предзагрузка
            if await self.client.get(self.preload_complete_key):
                logger.info("Предзагрузка завершена другим процессом")
                return

            # Проверяем освобождена ли блокировка (значит что-то пошло не так)
            if not await self.client.get(self.preload_lock_key):
                logger.info("Блокировка освобождена, можно попробовать снова")
                return

            # Ждем перед следующей проверкой
            await asyncio.sleep(1)

        logger.warning("Таймаут ожидания предзагрузки")

        # Принудительно снимаем блокировку если таймаут
        if await self.client.get(self.preload_lock_key):
            logger.warning("Принудительно снимаем блокировку по таймауту")
            await self.client.delete(self.preload_lock_key)

    async def reset_preload_status(self):
        """Сброс статуса предзагрузки (для тестирования)"""
        if self.client:
            await self.client.delete(self.preload_complete_key)
            await self.client.delete(self.preload_lock_key)
            logger.info("Статус предзагрузки сброшен")


redis_cache = RedisCache()
