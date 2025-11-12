import os
import random
import aio_pika
import json
from logger import logger
import asyncio

RABBITMQ_URL = os.getenv("RABBITMQ_URL")
statuses = ["in_assembly", "on_the_way", "delivered"]


class RabbitMQConnection:
    def __init__(self):
        self.connection = None
        self.channel = None
        self.exchange = None

    async def connect(self):
        if not self.connection or self.connection.is_closed:
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


async def publish_delivery_status(order_id: int, status: str):
    await rabbit_connection.connect()
    exchange = rabbit_connection.exchange

    if exchange is None:
        logger.error("RabbitMQ exchange не инициализирован")
        return

    delivery_action = {"order_id": order_id, "status": status}
    message_body = bytes(json.dumps(delivery_action), encoding="utf-8")
    message = aio_pika.Message(
        body=message_body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT
    )

    await exchange.publish(message, routing_key="delivery.action")
    logger.info(f"Публикация сообщения delivery.action: {delivery_action}")


async def delivery_action(order_id: int):
    for status in statuses:
        # await asyncio.sleep(random.randint(5, 10))
        await publish_delivery_status(order_id, status)


async def handle_delivery_send(message: aio_pika.abc.AbstractIncomingMessage):
    async with message.process():
        order = json.loads(message.body.decode())
        order_id = order.get("order_id")
        asyncio.create_task(delivery_action(order_id))


async def main():
    await rabbit_connection.connect()
    channel = rabbit_connection.channel
    exchange = rabbit_connection.exchange

    if exchange is None:
        logger.error("RabbitMQ exchange не инициализирован")
        return

    if channel is None:
        logger.error("RabbitMQ channel не инициализирован")
        return

    queue = await channel.declare_queue("delivery_send_queue", durable=True)
    await queue.bind(exchange, routing_key="delivery.send")
    await queue.consume(handle_delivery_send)

    logger.info("delivery-service запущен.")
    try:
        await asyncio.Future()
    finally:
        await rabbit_connection.close()


if __name__ == "__main__":
    asyncio.run(main())
