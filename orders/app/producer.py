import json
import os
import aio_pika
from app.schemas import OrderCreate
from app.logger import logger


RABBITMQ_URL = os.getenv("RABBITMQ_URL")


async def publish_order(order: dict):
    connection = await aio_pika.connect_robust(RABBITMQ_URL)

    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            "marketplace", aio_pika.ExchangeType.DIRECT, durable=True
        )
        message_body = bytes(json.dumps(order), encoding="utf-8")
        message = aio_pika.Message(
            body=message_body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT
        )

        await exchange.publish(message, routing_key="order.created")

        logger.info(f"Публикация сообщения order.created: {order}")
