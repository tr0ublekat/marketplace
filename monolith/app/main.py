from contextlib import asynccontextmanager

import app.handlers as handlers
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
    updated_order = handlers.create_order_handler(order, db)
    updated_order = handlers.payment_handler(updated_order, db)

    if not updated_order["is_success"]:
        return {"error": "Ошибка при оплате заказа"}

    return updated_order
