from fastapi import Depends, FastAPI
from app.db import AsyncSessionLocal, engine
from app.models import Base, Order, OrderItem
from app.schemas import OrderCreate, ProductItem
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.producer import publish_order


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
    yield
    print("Завершение БД...")


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def read_root():
    return {"Hello": "World"}


@app.post("/orders")
async def create_order(order: OrderCreate, db: AsyncSession = Depends(get_db)):
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

    await publish_order(order)

    return new_order


@app.get("/orders")
async def get_orders(db: AsyncSession = Depends(get_db)):
    orders = await db.execute(select(Order))
    return orders.scalars().all()
