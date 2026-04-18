.PHONY: test1 test2 up down install restart 

ms:
	docker compose --profile ms up -d --scale orders=3 --scale delivery=2

ml:
	docker compose --profile ml up -d
	
down:
	docker compose --profile * down

install:
	cd test && python3 -m venv .venv && .venv/bin/pip3 install -r requirements.txt
	docker plugin install grafana/loki-docker-driver:3.3.2-amd64 --alias loki --grant-all-permissions || true

test1:
	cd test && .venv/bin/python3 main.py http://localhost:9000

test1_ms:
	cd test && .venv/bin/python3 main.py http://localhost:8001

test2:
	cd test && .venv/bin/locust --headless -u 200 -r 200 --host http://localhost:8001

test_ms:
	cd test && .venv/bin/locust --headless -u 200 -r 200 --host http://localhost:8001

test_ml:
	cd test && .venv/bin/locust --headless -u 5 -r 5 --host http://localhost:9000