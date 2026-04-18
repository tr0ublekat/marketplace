import aiohttp
import asyncio
import random
import sys
import time

host = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:9000"
request_count = 200
concurrency = 5  # сколько запросов одновременно

headers = {
    "Content-Type": "application/json",
}

count = 0


async def send_request(session, i):
    global count

    data = {
        "user_id": random.randint(1, 500),
        "items": [
            {"product_id": random.randint(1, 190), "quantity": random.randint(1, 5)}
        ],
    }
    async with session.post(
        f"{host}/orders", json=data, headers=headers
    ) as response:
        count += 1
        print(f"{count}/{request_count}", end="\r")
        pass


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
