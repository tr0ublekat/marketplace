import json
import aio_pika
from app.logger import logger
from app.rabbit import RabbitMQConnection


async def publish_order(order: dict, rabbit_connection: RabbitMQConnection):
    try:
        message_body = bytes(json.dumps(order), encoding="utf-8")
        message = aio_pika.Message(
            body=message_body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT
        )

        if rabbit_connection.exchange is None:
            logger.error("RabbitMQ exchange не инициализирован")
            return

        await rabbit_connection.exchange.publish(message, routing_key="order.created")

        logger.info(f"Публикация сообщения order.created: {order}")

    except Exception as e:
        logger.error(f"Ошибка при публикации сообщения в RabbitMQ: {e}")
