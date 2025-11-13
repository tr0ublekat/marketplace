from locust import HttpUser, task
import random


class HelloWorldUser(HttpUser):
    @task
    def hello_world(self):
        self.client.post(
            "/orders",
            json={
                "user_id": 50,
                "items": [
                    {"product_id": random.randint(1, 190), "quantity": 1},
                    {"product_id": random.randint(1, 190), "quantity": 2},
                ],
            },
            headers={"Content-Type": "application/json"},
        )
