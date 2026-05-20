# Vibe Bot

Telegram-бот для знакомств и общения «по вайбу» среди anime / manga / art / creative
аудитории. Подбор по фандомам, интересам и вайбу, Premium-подписка, лента «Аллея креаторов»
как Telegram Mini App.

Полное ТЗ — `docs/TZ_v1.1.docx`. Быстрый старт — `docs/QUICK_START.md`.

## Стек

- Python 3.12, aiogram 3.x (async)
- SQLAlchemy 2.0 (async, `Mapped[...]`), Alembic, PostgreSQL 16
- Redis 7 (FSM storage + кэш настроек)
- FastAPI + React 18 + Vite (Mini App)
- APScheduler, loguru, pydantic-settings
- Docker + docker-compose, nginx (TLS / webhook)
- ruff, pytest, uv

## Быстрый старт — локально

Требуется Python 3.12 и [uv](https://docs.astral.sh/uv/).

```bash
# 1. Зависимости
uv sync

# 2. Конфиг
cp .env.example .env
# отредактировать BOT_TOKEN и прочее

# 3. Поднять Postgres + Redis (например, через docker compose)
docker compose -f docker/docker-compose.yml up -d postgres redis

# 4. Миграции
uv run alembic upgrade head

# 5. Запуск (polling-режим — для разработки)
uv run python -m app.main --polling
```

## Запуск через Docker

```bash
cp .env.example .env
docker compose -f docker/docker-compose.yml up --build
```

Это поднимет `postgres`, `redis` и `bot`. Nginx добавится в этапе деплоя.

## Команды

```bash
# Зависимости
uv sync

# Линт + формат
uv run ruff check --fix .
uv run ruff format .

# Тесты
uv run pytest
uv run pytest tests/unit -q
uv run pytest -k matching

# Миграции
uv run alembic revision --autogenerate -m "что_меняли"
uv run alembic upgrade head
uv run alembic downgrade -1

# Запуск бота (long-polling, dev)
uv run python -m app.main --polling
```

## Структура проекта

```
app/
├── main.py            # entrypoint
├── config.py          # Settings из .env
├── logger.py          # loguru
├── db/                # модели + репозитории + base
├── services/          # бизнес-логика
├── bot/               # dispatcher, handlers, FSM, keyboards, middlewares
├── scheduler/         # APScheduler-джобы
├── api/               # FastAPI для Mini App
└── texts/             # все строки UI (RU)
webapp/                # React Mini App
alembic/               # миграции
docker/                # Dockerfile, compose, nginx
tests/                 # unit + integration
docs/                  # ТЗ и руководства
```

Архитектурный инвариант: **handlers → services → repositories**. SQL — только в
репозиториях. Строки UI — только в `app/texts/`.

## Документация

- `docs/TZ_v1.1.docx` — техническое задание.
- `docs/ADDENDUM_v1.2.docx` — Mini App + контент-модерация.
- `docs/QUICK_START.md` — пошаговый деплой на чистый Linux-сервер.
- `docs/ONBOARDING.md` — введение для разработчика.
- `docs/USER_GUIDE.md` — гайд для пользователей бота.
