.PHONY: test up down install restart

up:
	docker compose up --build -d --scale orders=3 --scale delivery=3 --scale notifications=3

down:
	docker compose down

install:
	cd test && python3 -m venv .venv && .venv/bin/pip3 install -r requirements.txt
	docker plugin install grafana/loki-docker-driver:3.3.2-amd64 --alias loki --grant-all-permissions

test:
	cd test && .venv/bin/python3 main.py

restart:
	$(MAKE) down
	$(MAKE) up