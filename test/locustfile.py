from locust import HttpUser, task


class HelloWorldUser(HttpUser):
    @task
    def hello_world(self):
        self.client.post(
            "/orders",
            json={
                "user_id": 50,
                "items": [
                    {"product_id": 111, "quantity": 1},
                    {"product_id": 222, "quantity": 2},
                ],
            },
            headers={"Content-Type": "application/json"},
        )
