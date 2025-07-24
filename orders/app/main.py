import time
from fastapi import Depends, FastAPI, Request
from app.db import AsyncSessionLocal, engine
from app.models import Base, Order, OrderItem
from app.schemas import OrderCreate
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert, select
from app.producer import publish_order
from app.rabbit import RabbitMQConnection, rabbit_connection, get_rabbit
from app.logger import logger
import random


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def on_startup():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        logger.fatal(f"Ошибка при инициализации БД: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await on_startup()
    await rabbit_connection.connect()
    yield
    logger.info("Завершение RabbitMQ...")
    await rabbit_connection.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/orders")
async def create_order(
    order: OrderCreate,
    db: AsyncSession = Depends(get_db),
    rabbit_connection: RabbitMQConnection = Depends(get_rabbit),
):
    # start = time.perf_counter()
    try:

        if not order.items:
            logger.error(f"Заказ пользователя №{order.user_id} не содержит товаров")
            return {"error": "Заказ не может быть пустым"}

        new_order = Order(user_id=order.user_id)
        db.add(new_order)
        await db.flush()

        order_items = [
            OrderItem(
                order_id=new_order.id,
                product_id=item.product_id,
                quantity=item.quantity,
            )
            for item in order.items
        ]
        db.add_all(order_items)
        await db.commit()

    except Exception as e:
        logger.error(f"Ошибка при добавлении заказа: {e}")

    # logger.info(f"Добавление в БД заняло {time.perf_counter() - start:.4f} сек")

    # start = time.perf_counter()

    updated_items = []
    total_price = 0

    for item in order.items:
        unit_price = random.randint(100, 1500)
        total = unit_price * item.quantity
        total_price += total
        updated_items.append(
            {**item.model_dump(), "unit_price": unit_price, "total": total}
        )

    updated_order = {
        "order_id": new_order.id,
        "user_id": new_order.user_id,
        "items": updated_items,
        "total_price": total_price,
    }

    # logger.info(f"Обновление заказа заняло {time.perf_counter() - start:.4f} сек")

    # start = time.perf_counter()

    try:
        await publish_order(updated_order, rabbit_connection)
        # logger.info(
        #     f"Публикация в RabbitMQ заняла {time.perf_counter() - start:.4f} сек"
        # )
    except Exception as e:
        logger.error(f"Ошибка при публикации в RabbitMQ: {e}")

    return updated_order


@app.get("/orders")
async def get_orders(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 10,
):
    start = time.perf_counter()
    result = await db.execute(select(Order).offset(skip).limit(limit))
    logger.info(f"Получение заказов заняло {time.perf_counter() - start:.4f} сек")
    return result.scalars().all()
