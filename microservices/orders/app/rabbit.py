import aio_pika
import os
from contextlib import asynccontextmanager
from app.logger import logger

RABBITMQ_URL = os.getenv("RABBITMQ_URL")


class RabbitMQConnection:
    def __init__(self):
        self.connection = None
        self.channel = None
        self.exchange = None

    async def connect(self):
        if not self.connection:
            self.connection = await aio_pika.connect_robust(RABBITMQ_URL)
            self.channel = await self.connection.channel()
            self.exchange = await self.channel.declare_exchange(
                "marketplace", aio_pika.ExchangeType.DIRECT, durable=True
            )
            logger.info("Соединение с RabbitMQ установлено")
        return self

    async def close(self):
        if self.connection:
            await self.connection.close()
            self.connection = None
            self.channel = None
            self.exchange = None
            logger.info("Соединение с RabbitMQ закрыто")


rabbit_connection = RabbitMQConnection()


async def get_rabbit():
    await rabbit_connection.connect()
    return rabbit_connection
