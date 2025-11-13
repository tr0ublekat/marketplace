import random
import time
from contextlib import asynccontextmanager

from app.db import AsyncSessionLocal, engine
from app.logger import logger
from app.models import Base, Order, OrderItem, Product
from app.producer import publish_order
from app.rabbit import RabbitMQConnection, get_rabbit, rabbit_connection
from app.redis import redis_cache
from app.schemas import OrderCreate, ProductIn, ProductOut
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession


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
    await redis_cache.connect()

    async with AsyncSessionLocal() as session:
        await redis_cache.preload_all_prices(session)

    yield

    await rabbit_connection.close()
    await redis_cache.disconnect()


app = FastAPI(lifespan=lifespan)


@app.get("/health", tags=["health"])
async def health_check(db: AsyncSession = Depends(get_db)):
    # Проверяем БД
    await db.execute(text("SELECT 1"))

    # Проверяем Redis
    try:
        if redis_cache.client:
            await redis_cache.client.ping()
            redis_status = "healthy"
        else:
            redis_status = "disconnected"
    except Exception as e:
        redis_status = f"error: {e}"

    return {"status": "healthy", "database": "connected", "redis": redis_status}


@app.post("/orders", tags=["orders"])
async def create_order(
    order: OrderCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    rabbit_connection: RabbitMQConnection = Depends(get_rabbit),
):
    start = time.perf_counter()

    if not order.items:
        return {"error": "Заказ не может быть пустым"}

    # 1. Получаем ВСЕ цены из кэша (теперь они всегда там)
    product_ids = [item.product_id for item in order.items]
    cached_prices = await redis_cache.get_product_prices_bulk(product_ids)

    # 2. Проверяем что все товары найдены (должны быть, т.к. предзагружены)
    missing_products = set(product_ids) - set(cached_prices.keys())
    if missing_products:
        logger.error(f"Товары не найдены в кэше: {missing_products}")
        return {"error": f"Товары не найдены: {missing_products}"}

    # 3. Вычисляем общую сумму
    total_price = 0
    updated_items = []

    for item in order.items:
        unit_price = cached_prices[item.product_id]
        total = unit_price * item.quantity
        total_price += total
        updated_items.append(
            {**item.model_dump(), "unit_price": unit_price, "total": total}
        )

    # 4. Создаем заказ в БД - УПРОЩЕННАЯ ВЕРСИЯ
    try:
        new_order = Order(user_id=order.user_id)
        db.add(new_order)
        await db.flush()

        # Batch insert для order_items
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
        await db.rollback()
        logger.error(f"Ошибка при создании заказа в БД: {e}")
        return {"error": "Ошибка при создании заказа"}

    # 5. Формируем ответ (упрощенный)
    order_response = {
        "order_id": new_order.id,
        "user_id": new_order.user_id,
        "total_price": total_price,
        "status": "created",
    }

    # 6. Отправляем в RabbitMQ в фоне (упрощенный payload)
    # background_tasks.add_task(
    #     publish_order,
    #     {
    #         "order_id": new_order.id,
    #         "user_id": new_order.user_id,
    #         "total_price": total_price,
    #     },
    #     rabbit_connection,
    # )
    await publish_order(order_response, rabbit_connection)

    logger.info(f"Создание заказа заняло {time.perf_counter() - start:.4f} сек")
    return order_response


@app.get("/orders", tags=["orders"])
async def get_orders(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 10,
):
    start = time.perf_counter()
    stmt = (
        select(Order, OrderItem, Product)
        .join(OrderItem, Order.id == OrderItem.order_id)  # явное указание условия JOIN
        .join(
            Product, OrderItem.product_id == Product.id
        )  # явное указание условия JOIN
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    logger.info(f"Получение заказов заняло {time.perf_counter() - start:.4f} сек")

    # Обработка результата
    orders_dict = {}
    for order, order_item, product in result.all():
        if order.id not in orders_dict:
            orders_dict[order.id] = {
                "id": order.id,
                "user_id": order.user_id,
                "items": [],
            }

        orders_dict[order.id]["items"].append(
            {
                "name": product.name,
                "price": product.price,
                "quantity": order_item.quantity,
            }
        )

    return list(orders_dict.values())


@app.get("/products", tags=["products"])
async def get_products(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 10,
):
    start = time.perf_counter()
    result = await db.execute(select(Product).offset(skip).limit(limit))
    logger.info(f"Получение товаров заняло {time.perf_counter() - start:.4f} сек")
    return result.scalars().all()


@app.post("/products", tags=["products"])
async def create_product(
    product: ProductIn,
    db: AsyncSession = Depends(get_db),
):
    product = Product(name=product.name, price=product.price)
    db.add(product)
    await db.commit()
    return product


@app.get("/products/{product_id}", tags=["products"])
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    start = time.perf_counter()
    result = await db.execute(select(Product).where(Product.id == product_id))
    logger.info(f"Получение товара заняло {time.perf_counter() - start:.4f} сек")
    return result.scalars().first()


@app.post("/products/{product_id}/refresh-cache", tags=["products"])
async def refresh_product_cache(product_id: int, db: AsyncSession = Depends(get_db)):
    """Обновляет цену товара в кэше"""
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    await redis_cache.set_product_price(product_id, product.price)
    return {"status": "cache updated", "product_id": product_id, "price": product.price}
