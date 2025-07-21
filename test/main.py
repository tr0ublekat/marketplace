import aiohttp
import asyncio
import random
import time

request_count = 1000
concurrency = 100  # сколько запросов одновременно

headers = {
    "Content-Type": "application/json",
}


async def send_request(session, i):
    data = {
        "user_id": random.randint(1, 500),
        "items": [
            {"product_id": random.randint(1, 1000), "quantity": random.randint(1, 10)}
        ],
    }
    async with session.post(
        "http://localhost:8001/orders", json=data, headers=headers
    ) as response:
        # Можно проверять response.status если нужно
        # await response.text() если нужен ответ
        print(i, end="\r")


async def bounded_send(semaphore, session, i):
    async with semaphore:
        await send_request(session, i)


async def main():
    start = time.time()
    semaphore = asyncio.Semaphore(concurrency)
    async with aiohttp.ClientSession() as session:
        tasks = [
            bounded_send(semaphore, session, i) for i in range(1, request_count + 1)
        ]
        await asyncio.gather(*tasks)
    end = time.time()
    print(f"\nОбщее время выполнения: {end - start:.2f} секунд(ы)")
    print(f"Запросов в секунду: {request_count / (end - start):.2f}")


asyncio.run(main())
