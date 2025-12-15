import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(str(DATABASE_URL), echo=False)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    with SessionLocal() as session:
        yield session


def create_tables():
    from app.models import Base, Order, OrderItem, Product

    Base.metadata.create_all(bind=engine)
