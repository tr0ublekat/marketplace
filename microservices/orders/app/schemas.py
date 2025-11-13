from pydantic import BaseModel
from typing import List


class ProductItem(BaseModel):
    product_id: int
    quantity: int


class OrderCreate(BaseModel):
    user_id: int
    items: List[ProductItem]


class ProductIn(BaseModel):
    name: str
    price: int


class ProductOut(BaseModel):
    id: int
    name: str
    price: int
