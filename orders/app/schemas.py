from pydantic import BaseModel
from typing import List


class ProductItem(BaseModel):
    product_id: int
    quantity: int


class OrderCreate(BaseModel):
    user_id: int
    items: List[ProductItem]
