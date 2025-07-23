from fastapi import Depends, FastAPI
from app.db import AsyncSessionLocal, engine
from app.models import Base, Order, OrderItem
from app.schemas import OrderCreate, ProductItem
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.producer import publish_order
from app.logger import logger
from app.rabbit import RabbitMQConnection, rabbit_connection, get_rabbit
import random


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def on_startup():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        print(f"Ошибка при инициализации БД: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await on_startup()
    await rabbit_connection.connect()
    yield
    print("Завершение БД...")
    await rabbit_connection.close()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def read_root():
    return {"Hello": "World"}


@app.post("/orders")
async def create_order(order: OrderCreate, db: AsyncSession = Depends(get_db), rabbit_connection: RabbitMQConnection = Depends(get_rabbit)):
    new_order = Order(user_id=order.user_id)
    db.add(new_order)
    await db.flush()

    for item in order.items:
        otder_item = OrderItem(
            order_id=new_order.id, product_id=item.product_id, quantity=item.quantity
        )
        db.add(otder_item)

    await db.commit()
    await db.refresh(new_order)

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

    await publish_order(updated_order, rabbit_connection)

    return updated_order


@app.get("/orders")
async def get_orders(db: AsyncSession = Depends(get_db)):
    orders = await db.execute(select(Order))
    return orders.scalars().all()
