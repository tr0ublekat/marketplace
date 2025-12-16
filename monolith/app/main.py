from contextlib import asynccontextmanager

import app.handlers as handlers
import app.schemas as schemas
from app.db import create_tables, get_db
from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session
from fastapi import BackgroundTasks

statuses = ["in_assembly", "on_the_way", "delivered"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}


@app.post("/orders", tags=["orders"])
async def create_order(
    order: schemas.OrderCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    updated_order = handlers.create_order_handler(order, db)
    updated_order = handlers.payment_handler(updated_order, db)

    if not updated_order["is_success"]:
        return {"error": "Ошибка при оплате заказа"}

    for status in statuses:
        # updated_order = handlers.delivery_handler(updated_order, status, db)
        background_tasks.add_task(handlers.delivery_handler, updated_order, status, db)

    return updated_order
