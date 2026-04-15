# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Назначение проекта

ВКР (дипломная работа). Тема — разработка транспортной шины (ESB) для микросервисной архитектуры на примере интернет-магазина (marketplace). Проект реализует **два варианта одного приложения** — монолит и микросервисы — для сравнительного анализа производительности, масштабируемости и архитектурных решений. Программная часть в основном завершена, основная работа — текстовая часть диплома.

## Команды

```bash
make install         # Установка: venv для тестов + Loki Docker driver
make ms              # Запуск микросервисов (3 реплики orders, 2 delivery)
make ml              # Запуск монолита
make down            # Остановка всех контейнеров
make test_ms         # Нагрузочный тест микросервисов (Locust, 200 users, порт 8001)
make test_ml         # Нагрузочный тест монолита (Locust, 5 users, порт 9000)
make test1           # aiohttp-тест (200 запросов, 5 конкурентных, порт 9000)
```

Парсер для заполнения БД товарами: `cd parser && python main.py` (читает data.json с 194 товарами из dummyjson, генерирует случайные цены 1000–15000, пишет в PostgreSQL).

## Архитектура

### Модель данных (общая для обоих вариантов)

Product(id, name, price:int) → Order(id, user_id) → OrderItem(id, order_id, product_id, quantity). Цены — целые числа (копейки/рубли). Схемы Pydantic: OrderCreate{user_id, items:[{product_id, quantity}]}, ProductIn{name, price}.

### Монолит (`monolith/`, профиль `ml`, порт 9000)

Один процесс FastAPI + синхронный SQLAlchemy (psycopg2). Весь бизнес-процесс заказа выполняется последовательно в одном HTTP-запросе:
1. `create_order_handler` — создание заказа + batch insert order_items, затем SELECT цен из БД для подсчёта total_price
2. `payment_handler` — имитация оплаты (98% успех, `random.randint(0,100) >= 2`)
3. `delivery_handler` — обновление статуса через 3 этапа (`in_assembly` → `on_the_way` → `delivered`), выполняется как BackgroundTasks

Инфраструктура: только PostgreSQL (+ Loki/Grafana/Prometheus для мониторинга).

### Микросервисы (`microservices/`, профиль `ms`, вход через Nginx порт 8001)

**5 сервисов**, взаимодействие через RabbitMQ (direct exchange `marketplace`, все очереди durable):

**orders** (Python/FastAPI, async, 2 worker'а Uvicorn, 3 реплики за Nginx round-robin):
- Async SQLAlchemy + asyncpg, пул: pool_size=20, max_overflow=30, pool_recycle=3600
- Redis-кэш цен товаров: при старте preload_all_prices с distributed lock (nx+ex=30s) + флаг preload_complete (TTL 24ч). Bulk-чтение через MGET, запись через pipeline.
- POST /orders: цены из Redis (mget), подсчёт total, batch insert в БД, публикация `order.created` в RabbitMQ (persistent message)
- GET /orders: JOIN Order+OrderItem+Product с пагинацией
- POST/GET /products, GET /products/{id}, POST /products/{id}/refresh-cache

**go-esb** (Go, 10 горутин-воркеров) — центральный маршрутизатор сообщений (ESB). Слушает `ebs_queue`, подписанную на routing keys: `order.created`, `payment.action`, `delivery.action`. Логика маршрутизации:
- `order.created` → публикует `checkout.ready` (отправляет на оплату)
- `payment.action` → если is_success=true, публикует `delivery.send`; если false — логирует отказ
- `delivery.action` → логирует статус (уведомления закомментированы)
- Может отправлять `notification.action` (сейчас вызовы sendNotification закомментированы)

**payment** (Go, 10 горутин-воркеров) — слушает `payments_queue` по ключу `checkout.ready`. Имитирует оплату (98% успех). Публикует результат в `payment.action` с полем is_success.

**delivery** (Python, aio-pika) — слушает `delivery_send_queue` по ключу `delivery.send`. Для каждого заказа последовательно публикует 3 статуса (`in_assembly`, `on_the_way`, `delivered`) в `delivery.action`. Масштабируется до 2 реплик.

**notifications** (Go, 10 горутин-воркеров) — слушает `notifications_queue` по ключу `notification.action`. Логирует уведомления. Сейчас не получает сообщений, т.к. sendNotification в ESB закомментирован.

### Полный поток обработки заказа (микросервисы)

```
Client → Nginx → orders (POST /orders)
  orders: Redis→цены, БД→insert, RabbitMQ→"order.created"
  go-esb: получает order.created → публикует "checkout.ready"
  payment: получает checkout.ready → mock оплата → публикует "payment.action"
  go-esb: получает payment.action → если успех → публикует "delivery.send"
  delivery: получает delivery.send → публикует 3× "delivery.action"
  go-esb: получает delivery.action → логирует (notification закомментирован)
```

### Инфраструктура (docker-compose.yml)

| Сервис | Образ | Порт | Профиль | Назначение |
|--------|-------|------|---------|------------|
| PostgreSQL 16 | postgres:16 | 5444 | ml,ms | БД, max_connections=200 |
| RabbitMQ 3 | rabbitmq:3-management | 5666/15666 | ms | Брокер сообщений |
| Redis 7 | redis:7-alpine | 6333 | ms | Кэш цен, 256MB, allkeys-lru |
| Nginx | nginx:alpine | 8001 | ms | Балансировщик (round-robin, 3 upstream) |
| Loki 2.9 | grafana/loki:2.9.0 | 3100 | ml,ms | Агрегация логов |
| Grafana 10.3 | grafana/grafana:10.3.0 | 3000 | ml,ms | Визуализация (анонимный доступ) |
| Prometheus | prom/prometheus | 9090 | ml,ms | Метрики (scrape 5s) |
| cAdvisor | gcr.io/cadvisor | 8080 | ml,ms | Метрики контейнеров |

Все сервисы пишут логи в Loki через Docker logging driver (non-blocking, batch 10000, 5s wait). Health checks на всех сервисах (10s interval, 5s timeout, 5 retries).

### Нагрузочное тестирование (`test/`)

- **Locust** (`locustfile.py`): POST /orders с 2 случайными товарами (product_id 1–190). Для ms: 200 users/200 spawn rate; для ml: 5/5.
- **aiohttp** (`main.py`): 200 запросов с семафором concurrency=5, замер RPS и общего времени. Шлёт на порт 9000 (монолит).

### Ключевые технологические решения для диплома

1. **ESB как центральный маршрутизатор** — go-esb реализует паттерн Enterprise Service Bus, все inter-service коммуникации проходят через него. Сервисы не знают друг о друге напрямую.
2. **Async vs Sync** — микросервис orders полностью асинхронный (asyncpg, aio-pika, async redis), монолит — синхронный (psycopg2). Позволяет сравнить подходы.
3. **Кэширование с distributed lock** — Redis preload с NX-блокировкой предотвращает thundering herd при старте 3 реплик orders.
4. **Горизонтальное масштабирование** — orders: 3 реплики + Nginx, delivery: 2 реплики. Go-сервисы масштабируются внутри через горутины (10 воркеров).
5. **Observability стек** — Loki (логи) + Prometheus/cAdvisor (метрики контейнеров) + Grafana (визуализация). Позволяет наглядно сравнить потребление ресурсов.
6. **Docker Compose profiles** — один файл конфигурации для обоих вариантов развёртывания, упрощает сравнение.

### Стек технологий

- **Python 3.11**: FastAPI, SQLAlchemy 2.0 (sync + async), Pydantic, aio-pika, redis-py, uvicorn
- **Go 1.22**: streadway/amqp, goroutines + channels для concurrency
- **Инфраструктура**: Docker Compose, Nginx, PostgreSQL 16, RabbitMQ 3, Redis 7, Loki 2.9, Grafana 10.3, Prometheus, cAdvisor
- **Тестирование**: Locust, aiohttp
