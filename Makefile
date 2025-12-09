.PHONY: test1 test2 up down install restart

up:
	docker compose up -d --scale orders=3 --scale delivery=2 --scale notifications=2 --scale go-esb=2

down:
	docker compose down

install:
	cd test && python3 -m venv .venv && .venv/bin/pip3 install -r requirements.txt
	docker plugin install grafana/loki-docker-driver:3.3.2-amd64 --alias loki --grant-all-permissions || true

test1:
	cd test && .venv/bin/python3 main.py

test2:
	cd test && .venv/bin/locust --headless -u 200 -r 200 --host http://localhost:8001

restart:
	$(MAKE) down
	$(MAKE) up