up:
	docker compose up --build -d --scale orders=3

down:
	docker compose down

restart:
	$(MAKE) down
	$(MAKE) up