import random

import app.schemas as schemas
from app.db import get_db
from app.logger import logger
from app.models import Order, OrderItem, Product
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session


def create_order_handler(order: schemas.OrderCreate, db: Session = Depends(get_db)):
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


def payment_handler(updated_order: dict, db: Session = Depends(get_db)):
    is_success = random.randint(0, 100) >= 2
    updated_order["is_success"] = is_success

    if not is_success:
        logger.error(f"Ошибка при оплате заказа №{updated_order['order_id']}")
    else:
        logger.info(f"Заказ №{updated_order['order_id']} оплачен")

    return updated_order


def delivery_handler(updated_order: dict, status: str, db: Session = Depends(get_db)):
    updated_order["status"] = status
    logger.info(f"Заказ №{updated_order['order_id']} переходит в статус {status}")

    return updated_order
