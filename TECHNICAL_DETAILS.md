# Техническая документация проекта Marketplace

> Тема ВКР: «Исследование архитектурных и технологических подходов к построению высоконагруженных приложений»

Документ содержит подробное описание реализации каждого компонента системы с акцентом на архитектурные и технологические решения, релевантные для дипломной работы.

---

## 1. Общая архитектура

Проект реализует **один и тот же бизнес-домен** (интернет-магазин) в двух архитектурных вариантах:

- **Монолитная архитектура** — единый процесс, синхронная обработка, вертикальное масштабирование
- **Микросервисная архитектура** — 5 независимых сервисов, асинхронное межсервисное взаимодействие через ESB, горизонтальное масштабирование

Оба варианта разворачиваются из одного `docker-compose.yml` через механизм **profiles** (`ml` — монолит, `ms` — микросервисы), что обеспечивает идентичные условия инфраструктуры для корректного сравнения.

### Единая модель данных

Все сервисы работают с общей схемой БД (SQLAlchemy ORM, declarative_base):

```
products(id PK, name VARCHAR, price INTEGER)
orders(id PK, user_id INTEGER)
order_items(id PK, order_id FK→orders, product_id FK→products, quantity INTEGER)
```

Цены хранятся как целые числа. Связь Order→OrderItem реализована через SQLAlchemy relationship с back_populates.

---

## 2. Монолитное приложение

**Расположение:** `monolith/`
**Язык/фреймворк:** Python 3.11, FastAPI, Uvicorn (один worker, режим `--reload`)
**БД-драйвер:** psycopg2-binary (синхронный)
**ORM:** SQLAlchemy 2.0 (синхронный движок `create_engine`)

### 2.1 Инициализация

При старте приложения (`lifespan`) вызывается `create_tables()` — синхронный `Base.metadata.create_all(bind=engine)`. Таблицы создаются при каждом запуске (идемпотентно, SQLAlchemy проверяет существование).

Сессии БД создаются через `sessionmaker(autocommit=False, autoflush=False)` и предоставляются эндпоинтам через FastAPI Depends с генератором `get_db()`.

### 2.2 Обработка заказа (POST /orders)

Весь бизнес-процесс выполняется **последовательно внутри одного HTTP-запроса**:

**Шаг 1 — Создание заказа (`create_order_handler`):**
- Валидация: проверка что `order.items` не пуст
- Создание объекта `Order`, `db.add()` + `db.flush()` для получения `id`
- Batch insert: список `OrderItem` создаётся list comprehension, затем `db.add_all()` + `db.commit()`
- Подсчёт итоговой стоимости: для каждого item выполняется **отдельный SELECT** к таблице products (`select(Product).where(Product.id == item.product_id)`) — это потенциальное узкое место (N+1 запросов)

**Шаг 2 — Оплата (`payment_handler`):**
- Имитация платёжного шлюза: `random.randint(0, 100) >= 2` — 98% успешных транзакций
- Добавляет поле `is_success` к словарю заказа
- При неуспешной оплате — возврат ошибки клиенту

**Шаг 3 — Доставка (`delivery_handler`):**
- Три последовательных статуса: `in_assembly` → `on_the_way` → `delivered`
- Выполняется через `BackgroundTasks.add_task()` — FastAPI запускает задачи **после** отправки ответа клиенту
- Каждый вызов `delivery_handler` — отдельная фоновая задача, они выполняются последовательно в том же event loop

### 2.3 Другие эндпоинты

- `GET /orders` — не реализован отдельно (обработка через handlers)
- `POST /products`, `GET /products`, `GET /products/{id}` — CRUD без кэширования, прямые SQL-запросы
- `GET /health` — healthcheck для Docker

### 2.4 Ключевые характеристики для сравнения

- **Синхронная модель I/O**: каждый запрос к БД блокирует поток
- **Отсутствие кэширования**: цены товаров читаются из БД при каждом заказе
- **N+1 проблема**: подсчёт цены — отдельный SELECT на каждый товар в заказе
- **Один процесс**: вертикальное масштабирование ограничено ресурсами одного контейнера
- **Отсутствие межпроцессной коммуникации**: все этапы обработки — вызовы функций в одном адресном пространстве

---

## 3. Микросервисная архитектура

### 3.1 Orders Service (Python)

**Расположение:** `microservices/orders/`
**Язык/фреймворк:** Python 3.11, FastAPI, Uvicorn с `--workers 2`
**БД-драйвер:** asyncpg (полностью асинхронный)
**ORM:** SQLAlchemy 2.0 (async: `create_async_engine`, `async_sessionmaker`)
**Масштабирование:** 3 реплики контейнера за Nginx

#### Connection Pool (asyncpg)

```python
engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,        # базовый размер пула
    max_overflow=30,     # максимум дополнительных соединений
    pool_timeout=30,     # таймаут ожидания свободного соединения
    pool_pre_ping=True,  # проверка живости соединения перед использованием
    pool_recycle=3600,   # пересоздание соединений каждый час
)
```

Итого: каждый worker может держать до 50 соединений (20+30). При 3 репликах × 2 workers = до 300 соединений к PostgreSQL (max_connections=200 в конфиге PostgreSQL — потенциальное ограничение при полной нагрузке).

#### Redis-кэширование цен (`app/redis.py`)

Класс `RedisCache` реализует многоуровневую стратегию кэширования:

**Предзагрузка при старте (preload_all_prices):**
- Проблема: при старте 3 реплик одновременно, все пытаются загрузить цены в Redis → thundering herd
- Решение: **distributed lock через Redis SET NX EX** — только одна реплика выполняет предзагрузку:
  1. Проверка флага `preload_prices_complete` — если установлен, пропуск
  2. Попытка захвата блокировки `preload_prices_lock` с `nx=True, ex=30` (30 сек TTL)
  3. Если блокировка захвачена: SELECT всех цен из БД → `set_product_prices_bulk` → установка флага complete (TTL 24ч)
  4. Если не захвачена: `_wait_for_preload_completion` — polling с интервалом 1 сек, таймаут 30 сек
  5. При ошибке: принудительное снятие блокировки для retry другими репликами

**Bulk-операции:**
- `get_product_prices_bulk`: использует Redis `MGET` — одна команда вместо N отдельных GET
- `set_product_prices_bulk`: использует Redis `pipeline` — атомарная пакетная запись множества SETEX
- Ключи: `product_price:{id}`, TTL по умолчанию 3600 сек (1 час), для preload — 86400 сек (24 часа)

#### Обработка заказа (POST /orders)

1. Извлечение product_ids из запроса
2. **Bulk-чтение цен из Redis** (`mget`) — одна сетевая операция вместо N
3. Проверка что все товары найдены в кэше; если нет — ошибка
4. Подсчёт total_price на стороне приложения (не SQL)
5. Создание Order + batch insert OrderItem через `db.add_all()`
6. Публикация в RabbitMQ: `order.created` с payload `{order_id, user_id, total_price, status}`
7. Логирование времени выполнения через `time.perf_counter()`

**Отличие от монолита:** цены берутся из Redis (O(1) сетевой вызов), а не из PostgreSQL (N SELECT-ов). Публикация в RabbitMQ вместо прямого вызова payment/delivery.

#### RabbitMQ Producer (`app/rabbit.py`, `app/producer.py`)

- `RabbitMQConnection`: singleton-подобный класс, подключение через `aio_pika.connect_robust` (автопереподключение)
- Объявляет exchange `marketplace` типа `DIRECT`, durable=True
- `publish_order`: сериализация в JSON, `DeliveryMode.PERSISTENT` — сообщения переживают перезапуск RabbitMQ
- Инъекция через FastAPI Depends (`get_rabbit`)

### 3.2 Go-ESB — Enterprise Service Bus (Go)

**Расположение:** `microservices/go-esb/`
**Язык:** Go 1.22.2
**Библиотека AMQP:** streadway/amqp
**Concurrency-модель:** 10 горутин-воркеров, общий buffered channel (cap=100)

#### Роль в архитектуре

ESB — **единственный сервис, который знает о топологии системы**. Все остальные сервисы публикуют и потребляют сообщения, не зная получателя. ESB реализует паттерн **Message Router** (Enterprise Integration Patterns).

#### Подключение к RabbitMQ

- Объявляет exchange `marketplace` (direct, durable)
- Создаёт одну очередь `ebs_queue` (durable) и привязывает к трём routing keys: `order.created`, `payment.action`, `delivery.action`
- Потребление с `auto-acknowledge=true` (без подтверждений — приоритет скорости над гарантией доставки)

#### Логика маршрутизации

Switch по `msg.RoutingKey`:

| Входящий ключ | Действие | Исходящий ключ |
|---------------|----------|----------------|
| `order.created` | Десериализация {order_id, total_price}, перенаправление на оплату | `checkout.ready` |
| `payment.action` | Проверка `is_success`: true → доставка, false → лог отказа | `delivery.send` (при успехе) |
| `delivery.action` | Логирование статуса доставки | — (notification закомментирован) |

**Закомментированная функциональность:** `sendNotification` — отправка уведомлений в `notification.action`. Подготовлена структура Notification{OrderID, Sub, Description}, но вызовы закомментированы в трёх обработчиках.

#### Worker Pool

```go
tasks := make(chan amqp.Delivery, 100)  // буферизованный канал
for i := 0; i < 10; i++ {
    go worker(ch, tasks)  // 10 горутин
}
for msg := range msgs {
    tasks <- msg  // распределение сообщений
}
```

Паттерн Fan-Out: одна горутина читает из RabbitMQ, 10 горутин обрабатывают. Буфер 100 сообщений сглаживает пики нагрузки.

### 3.3 Payment Service (Go)

**Расположение:** `microservices/payment/`
**Язык:** Go 1.22.2
**Очередь:** `payments_queue`, привязана к routing key `checkout.ready`

#### Логика обработки

1. Десериализация: `PaymentActionInput{OrderID, TotalPrice}`
2. Имитация оплаты: `rand.Intn(100) >= 2` — 98% успех (идентично монолиту)
3. Формирование результата: `PaymentActionOutput{OrderID, TotalPrice, IsSuccess}`
4. Публикация в `payment.action`

#### Concurrency

Идентичная модель worker pool: 10 горутин, buffered channel (100), auto-acknowledge.

### 3.4 Delivery Service (Python)

**Расположение:** `microservices/delivery/`
**Язык:** Python 3.11 (не FastAPI — standalone скрипт)
**Библиотека AMQP:** aio-pika (async)
**Масштабирование:** 2 реплики контейнера

#### Отличие от остальных Python-сервисов

Не является HTTP-сервером. Запускается как `python3 app/main.py` — чистый RabbitMQ consumer.

#### Логика обработки

- Очередь `delivery_send_queue`, routing key `delivery.send`
- При получении сообщения: `asyncio.create_task(delivery_action(order_id))` — неблокирующая обработка
- `delivery_action`: последовательная публикация трёх статусов в `delivery.action`:
  - `in_assembly` (на сборке)
  - `on_the_way` (в пути)
  - `delivered` (доставлен)
- Задержка между статусами закомментирована (`asyncio.sleep(random.randint(5, 10))`)

#### RabbitMQ

Собственный класс `RabbitMQConnection` (дублирует orders, но с проверкой `is_closed` для реконнекта). Сообщения с `DeliveryMode.PERSISTENT`. Потребление через `message.process()` — ручное подтверждение (в отличие от Go-сервисов с auto-ack).

### 3.5 Notifications Service (Go)

**Расположение:** `microservices/notifications/`
**Язык:** Go 1.22.2
**Очередь:** `notifications_queue`, routing key `notification.action`

#### Реализация

- Worker pool: 10 горутин, buffered channel (100)
- `handleNotificationsAction`: десериализация `{order_id, sub, description}`, логирование в stdout
- **Фактически неактивен** в текущей конфигурации — ESB не отправляет сообщения в `notification.action` (вызовы закомментированы)

---

## 4. Балансировка нагрузки (Nginx)

**Файл:** `nginx.conf`

```nginx
worker_processes auto;              # автоопределение по числу CPU
worker_rlimit_nofile 100000;        # лимит файловых дескрипторов

events {
    worker_connections 10000;       # макс. соединений на worker
    use epoll;                      # асинхронный I/O (Linux)
    multi_accept on;                # принятие нескольких соединений за раз
}

upstream orders_backend {
    server marketplace-orders-1:8000;
    server marketplace-orders-2:8000;
    server marketplace-orders-3:8000;
}
```

- Алгоритм: **round-robin** (по умолчанию) — каждый следующий запрос идёт к следующему backend
- Имена серверов: Docker Compose автоматически именует реплики как `{project}-{service}-{N}`
- `epoll` — оптимальный для Linux event notification mechanism (O(1) vs O(n) у select/poll)

---

## 5. Брокер сообщений (RabbitMQ)

### Топология обмена сообщениями

**Exchange:** `marketplace`, тип `direct`, durable

| Routing Key | Producer | Queue | Consumer |
|-------------|----------|-------|----------|
| `order.created` | orders | `ebs_queue` | go-esb |
| `checkout.ready` | go-esb | `payments_queue` | payment |
| `payment.action` | payment | `ebs_queue` | go-esb |
| `delivery.send` | go-esb | `delivery_send_queue` | delivery |
| `delivery.action` | delivery | `ebs_queue` | go-esb |
| `notification.action` | go-esb* | `notifications_queue` | notifications |

*\* — закомментировано*

### Гарантии доставки

- **Durable exchange + durable queues**: переживают перезапуск RabbitMQ
- **Persistent messages** (Python-сервисы): `DeliveryMode.PERSISTENT` — сообщения сохраняются на диск
- **Auto-acknowledge** (Go-сервисы): сообщение удаляется из очереди сразу при получении — приоритет производительности
- **Manual acknowledge** (delivery): `message.process()` — подтверждение после обработки

### Паттерн взаимодействия

```
orders → [order.created] → ESB → [checkout.ready] → payment
payment → [payment.action] → ESB → [delivery.send] → delivery
delivery → [delivery.action] → ESB → (лог / notification*)
```

ESB выступает как **центральный маршрутизатор** — ни один сервис не знает адреса другого. Это реализация паттерна **Enterprise Service Bus** из Enterprise Integration Patterns (Hohpe, Woolf). Сервисы взаимодействуют исключительно через именованные каналы (routing keys), что обеспечивает слабую связанность (loose coupling).

---

## 6. Стек мониторинга и наблюдаемости

### 6.1 Сбор логов: Loki

**Механизм:** Docker logging driver `grafana/loki-docker-driver:3.3.2-amd64` — логи собираются непосредственно Docker Engine, приложения пишут в stdout/stderr без дополнительных библиотек.

**Конфигурация драйвера (docker-compose.yml):**
```yaml
logging:
  driver: "loki"
  options:
    loki-url: "http://localhost:3100/loki/api/v1/push"
    loki-batch-size: "10000"     # размер пакета логов
    loki-batch-wait: "5s"        # интервал отправки
    loki-retries: 3              # повторные попытки
    mode: "non-blocking"         # не блокирует контейнер при недоступности Loki
    max-size: "10m"              # макс. размер буфера
```

`non-blocking` режим критически важен — при падении Loki контейнеры продолжают работать, логи буферизуются до `max-size`.

**Конфигурация Loki (`loki-config.yaml`):**
- Хранение: filesystem (chunks + boltdb-shipper для индексов)
- Ingestion: WAL (Write-Ahead Log) включён, chunk_target_size=1MB, кодирование snappy
- Лимиты: ingestion_rate_mb=128, burst=256, max_entries_limit_per_query=5000
- KV-store: inmemory (single-instance deployment)

### 6.2 Метрики контейнеров: Prometheus + cAdvisor

**cAdvisor** — агент Google для сбора метрик контейнеров (CPU, memory, network, filesystem). Монтирует хостовые директории `/`, `/var/run`, `/sys`, `/var/lib/docker` в read-only режиме. Требует `privileged: true`.

**Prometheus** — scrape_interval=5s, единственный target: `cadvisor:8080`. Хранение в TSDB, web lifecycle API включён.

Метрики позволяют сравнить потребление ресурсов контейнерами монолита и микросервисов при одинаковой нагрузке.

### 6.3 Визуализация: Grafana

- Datasource: Loki (http://loki:3100), provisioned автоматически через YAML
- Анонимный доступ с ролью Admin (`GF_AUTH_ANONYMOUS_ENABLED=true`)
- Порт 3000

---

## 7. Нагрузочное тестирование

### 7.1 Locust (`test/locustfile.py`)

```python
class HelloWorldUser(HttpUser):
    @task
    def hello_world(self):
        self.client.post("/orders", json={
            "user_id": 50,
            "items": [
                {"product_id": random.randint(1, 190), "quantity": 1},
                {"product_id": random.randint(1, 190), "quantity": 2},
            ],
        })
```

- Один тип нагрузки: создание заказа с 2 товарами
- Случайные product_id (1–190) — тестирует кэш Redis на различных ключах
- Фиксированный user_id=50

**Параметры запуска:**
- Микросервисы: 200 concurrent users, spawn rate 200/s, host `localhost:8001`
- Монолит: 5 concurrent users, spawn rate 5/s, host `localhost:9000`

Разница в 40 раз (200 vs 5) отражает ожидаемую разницу в пропускной способности.

### 7.2 aiohttp-тест (`test/main.py`)

- 200 запросов, семафор concurrency=5
- Отправляет на `localhost:9000` (монолит)
- Замеряет: общее время, RPS (requests per second)
- Каждый запрос: случайный user_id (1–500), 1 товар с random product_id и quantity (1–5)

---

## 8. Утилита заполнения данных (`parser/`)

- Читает `data.json` (194 товара из API dummyjson.com, загружены заранее)
- Для каждого товара генерирует случайную цену `random.randint(1000, 15000)`
- Записывает напрямую в PostgreSQL через async SQLAlchemy (asyncpg)
- Подключение: хардкод `postgresql+asyncpg://pguser:pgpassword@localhost:5444/marketplace`
- Создаёт таблицы при необходимости (`Base.metadata.create_all`)

---

## 9. Контейнеризация

### Общие паттерны Dockerfile

**Python-сервисы** (monolith, orders, delivery):
- Base image: `python:3.11-slim` (минимальный размер)
- Оптимизация кэша Docker: сначала COPY requirements.txt → pip install, затем COPY исходников
- `--no-cache-dir` при pip install — уменьшение размера образа

**Go-сервисы** (go-esb, payment, notifications):
- Base image: `golang:1.22.2` (не multi-stage — финальный образ содержит SDK)
- Go modules: сначала COPY go.mod+go.sum → `go mod download`, затем COPY исходников + `go build`
- Бинарь: `go build -o {service-name} ./app`

### Docker Compose orchestration

- **Dependency management:** `depends_on` с `condition: service_healthy` — сервисы запускаются только после прохождения healthcheck зависимостей
- **Health checks:** все сервисы имеют healthcheck (interval=10s, timeout=5s, retries=5)
  - PostgreSQL: `pg_isready`
  - RabbitMQ: `rabbitmqctl status`
  - Redis: `redis-cli ping`
  - Orders: `curl -f http://0.0.0.0:8000/health`
  - Loki: `wget --spider http://localhost:3100/ready`
- **Volumes:** persistent для pg_data, rabbitmq_data, loki_data, grafana_data, prometheus_data
- **Restart policy:** `unless-stopped` для Nginx, RabbitMQ, go-esb, Prometheus, cAdvisor

---

## 10. Сравнительная таблица архитектурных решений

| Аспект | Монолит | Микросервисы |
|--------|---------|--------------|
| **I/O модель** | Синхронная (psycopg2) | Асинхронная (asyncpg, aio-pika) |
| **Кэширование** | Отсутствует | Redis (preload + bulk MGET) |
| **Получение цен** | N SELECT-ов к БД | 1 MGET к Redis |
| **Межкомпонентная связь** | Вызов функций | RabbitMQ через ESB |
| **Масштабирование** | 1 процесс | 3 реплики orders + Nginx, 2 реплики delivery |
| **Concurrency** | 1 worker (sync) | 2 workers × 3 реплики + Go goroutines |
| **Гарантия оплаты** | В рамках HTTP-запроса | Асинхронная через очередь |
| **Доставка** | BackgroundTasks (in-process) | Отдельный сервис с persistent messages |
| **Связанность** | Tight coupling (прямые вызовы) | Loose coupling (только routing keys) |
| **Fault isolation** | Один сбой → всё падает | Сбой payment не влияет на orders |
| **Observability** | Loki + Prometheus | Loki + Prometheus + per-service логи |
| **Сложность развёртывания** | 1 контейнер + PostgreSQL | 10+ контейнеров, orchestration |
| **Языки** | Только Python | Python + Go (polyglot) |

---

## 11. Паттерны проектирования в проекте

1. **Enterprise Service Bus (ESB)** — go-esb как центральный маршрутизатор, реализация паттерна Message Router
2. **Fan-Out Worker Pool** — Go-сервисы: 1 reader → buffered channel → N goroutines
3. **Distributed Lock** — Redis NX+EX для координации предзагрузки между репликами
4. **Cache-Aside** — orders читает из Redis, при промахе — ошибка (preload гарантирует наличие)
5. **Dependency Injection** — FastAPI Depends для db sessions и RabbitMQ connection
6. **Saga Pattern** (неявный) — цепочка order→payment→delivery через ESB, каждый шаг — отдельная транзакция
7. **Backend for Frontend** — Nginx как единая точка входа, скрывающая реплики
8. **Health Check Pattern** — все сервисы имеют healthcheck, orchestration через depends_on conditions
9. **Sidecar Logging** — Docker logging driver как sidecar для сбора логов без изменения кода приложений
