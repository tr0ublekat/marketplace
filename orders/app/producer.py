import json
import aio_pika
from app.schemas import OrderCreate


RABBITMQ_URL = "amqp://rmq_admin:rmq_password@localhost/"


async def publish_order(order: OrderCreate):
    connection = await aio_pika.connect_robust(RABBITMQ_URL)

    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange("events", aio_pika.ExchangeType.TOPIC)
        message_body = order.model_dump_json()
        message = aio_pika.Message(body=message_body.encode())

        await exchange.publish(message, routing_key="order.created")
