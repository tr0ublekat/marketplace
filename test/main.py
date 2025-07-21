import aiohttp
import asyncio
import random

request_count = 100

headers = {
    "Content-Type": "application/json",
}


data = {
    "user_id": 0,
    "items": [{"product_id": 0, "quantity": 0}],
}


async def main():
    async with aiohttp.ClientSession() as session:

        global data

        for i in range(1, request_count+1):

            data["user_id"] = random.randint(1, 500)
            data["items"][0]["product_id"] = random.randint(1, 1000)
            data["items"][0]["quantity"] = random.randint(1, 10)

            async with session.post(
                "http://localhost:8001/orders", json=data, headers=headers
            ) as response:
                print(i, f"/{request_count}", end="\r")


asyncio.run(main())
