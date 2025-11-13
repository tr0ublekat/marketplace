import time
from fastapi import Depends, FastAPI, Request, BackgroundTasks
from app.db import AsyncSessionLocal, engine
from app.models import Base, Order, OrderItem, Product
from app.schemas import OrderCreate, ProductIn, ProductOut
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


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}


@app.post("/orders", tags=["orders"])
async def create_order(
    order: OrderCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    rabbit_connection: RabbitMQConnection = Depends(get_rabbit),
):
    start = time.perf_counter()

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

    logger.info(f"Добавление в БД заняло {time.perf_counter() - start:.4f} сек")

    start = time.perf_counter()

    updated_items = []
    total_price = 0

    for item in order.items:
        # unit_price = random.randint(100, 1500)
        try:
            result = await db.execute(
                select(Product).where(Product.id == item.product_id)
            )
            unit_price = result.scalars().first().price
        except Exception as e:
            logger.error(f"Ошибка при получении цены товара: {e}")
            return {"error": "Товар не найден"}

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

    logger.info(f"Обновление заказа заняло {time.perf_counter() - start:.4f} сек")

    # start = time.perf_counter()

    try:
        background_tasks.add_task(publish_order, updated_order, rabbit_connection)
        # logger.info(
        #     f"Публикация в RabbitMQ заняла {time.perf_counter() - start:.4f} сек"
        # )
    except Exception as e:
        logger.error(f"Ошибка при публикации в RabbitMQ: {e}")

    return updated_order


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
