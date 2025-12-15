from contextlib import asynccontextmanager

import app.schemas as schemas
from app.db import create_tables, get_db
from app.logger import logger
from app.models import Order, OrderItem, Product
from fastapi import Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}


@app.post("/orders", tags=["orders"])
async def create_order(order: schemas.OrderCreate, db: Session = Depends(get_db)):
    if not order.items:
        logger.error(f"Заказ пользователя №{order.user_id} не содержит товаров")
        return {"error": "Заказ не может быть пустым"}

    new_order = Order(user_id=order.user_id)
    db.add(new_order)
    db.flush()

    order_items = [
        OrderItem(
            order_id=new_order.id,
            product_id=item.product_id,
            quantity=item.quantity,
        )
        for item in order.items
    ]
    db.add_all(order_items)
    db.commit()

    updated_items = []
    total_price = 0

    for item in order.items:
        try:
            result = db.execute(select(Product).where(Product.id == item.product_id))
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

    logger.info(f"Успешно создан заказ №{new_order.id}")

    return updated_order
