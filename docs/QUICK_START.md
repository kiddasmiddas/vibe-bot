# Vibe Bot — Быстрый запуск

Минимальный сценарий для поднятия бота на чистом Linux-сервере.
Команды копируй по порядку, каждый блок — один шаг.

---

## 1. Что нужно на сервере

- Ubuntu 22.04+ (или совместимый Linux).
- Доступ `sudo`.
- Установлены **Docker** и **docker compose v2**.

Если их ещё нет — одной командой:
```bash
curl -fsSL https://get.docker.com | sudo sh
```

---

## 2. Положить код

```bash
sudo mkdir -p /opt/vibe-bot && sudo chown $USER /opt/vibe-bot
cd /opt/vibe-bot
git clone <repo-url> .
```

---

## 3. Настроить токены

```bash
cp .env.example .env
nano .env
```

Минимум, что вписать:

| Поле | Где взять |
|---|---|
| `BOT_TOKEN` | у `@BotFather` после `/newbot` |
| `ADMIN_TELEGRAM_IDS` | твой Telegram-ID через `@userinfobot` (если несколько админов — через запятую) |
| `YOOKASSA_PROVIDER_TOKEN` | у `@BotFather` → бот → Payments → подключить ЮKassa *(можно оставить пустым, если Premium пока не нужен)* |

Остальное можно оставить как есть.

---

## 4. Поднять всё

```bash
docker compose -f docker/docker-compose.yml up -d
```

Эта команда сама:
- собирает образ;
- запускает PostgreSQL, Redis, бот и API;
- ждёт пока БД станет healthy.

---

## 5. Накатить схему БД

```bash
docker exec vibe-bot python -m alembic upgrade head
```

Должно вывести что-то вроде `Running upgrade … -> 8121a079ffae`. Это нужно сделать **один раз**, перед первым запуском, и **повторять после каждого обновления кода**.

---

## 6. Проверить, что бот живой

```bash
docker compose -f docker/docker-compose.yml logs --tail=10 bot
```

В выводе должна быть строка `vibe-bot is starting`. Если её нет — см. `docker compose ps`, контейнер должен быть `Up`.

Открой Telegram, найди своего бота по username, отправь `/start` — должен ответить.

---

## Обновить бота (после изменений в коде)

```bash
cd /opt/vibe-bot
git pull
docker compose -f docker/docker-compose.yml build bot
docker exec vibe-bot python -m alembic upgrade head
docker compose -f docker/docker-compose.yml up -d bot api
```

---

## Остановить / перезапустить

```bash
docker compose -f docker/docker-compose.yml restart bot      # быстрый рестарт
docker compose -f docker/docker-compose.yml stop             # остановить всё
docker compose -f docker/docker-compose.yml down             # остановить + убрать контейнеры (данные БД сохранятся в volume)
```

---

## Если что-то пошло не так

| Симптом | Что делать |
|---|---|
| Бот не отвечает в Telegram | `docker compose logs --tail=50 bot` — ищи ошибки |
| `BOT_TOKEN` поменялся | отредактируй `.env`, затем `docker compose restart bot` |
| Нужно зайти в БД | `docker exec -it vibe-postgres psql -U vibe -d vibe` |
| Хочется сбэкапить БД | `docker exec vibe-postgres pg_dump -U vibe vibe > backup.sql` |
