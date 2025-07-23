.PHONY: test up down install restart

up:
	docker compose up --build -d --scale orders=3

down:
	docker compose down

install:
	cd test && python3 -m venv .venv && .venv/bin/pip3 install -r requirements.txt

test:
	cd test && .venv/bin/python3 main.py

restart:
	$(MAKE) down
	$(MAKE) up