# Vibe Bot — Mini App «Аллея креаторов»

React 18 + TypeScript + Vite приложение для Telegram Mini App.

## Быстрый старт

```bash
cd webapp && npm install
```

### Разработка

```bash
npm run dev
```

Vite запускается на `http://localhost:5173`.

В dev-режиме фронт работает без `X-Telegram-Init-Data` — бэкенд автоматически использует
тестового пользователя (`telegram_id=637931973`) благодаря `MINIAPP_DEV_BYPASS_AUTH=true` в `.env`.

Откройте `http://localhost:5173` в обычном Chrome — увидите ленту.

### Продакшен-сборка

```bash
npm run build
```

Артефакты попадают в `webapp/dist/`. Для деплоя скопируйте содержимое `dist/` в
`app/api/static/webapp/` (или настройте `build.outDir` в `vite.config.ts`).

### Линтинг

```bash
npm run lint
```

### Переменные окружения

Скопируйте `.env.example` в `.env` и при необходимости скорректируйте:

```bash
cp .env.example .env
```

| Переменная | Значение по умолчанию | Описание |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | URL FastAPI-бэкенда |

## Структура

```
webapp/
├── src/
│   ├── main.tsx            # bootstrap, BrowserRouter
│   ├── App.tsx             # маршруты: / → Feed, /post/:id → PostDetail
│   ├── api/
│   │   ├── client.ts       # fetch-обёртка с X-Telegram-Init-Data
│   │   └── types.ts        # TS-типы зеркалят pydantic-схемы бэка
│   ├── hooks/
│   │   └── useTelegram.ts  # обёртка над window.Telegram.WebApp
│   ├── pages/
│   │   ├── Feed.tsx        # лента с infinite scroll
│   │   └── PostDetail.tsx  # детали поста, карусель фото
│   ├── components/
│   │   ├── PostCard.tsx    # карточка поста в ленте
│   │   └── ErrorScreen.tsx # экраны ошибок (401, сеть, 404)
│   └── styles/
│       └── global.css      # reset + CSS-переменные Telegram
├── index.html              # подключает telegram-web-app.js
├── vite.config.ts          # base='/app/', proxy /api → :8000
├── tsconfig.json
└── .env.example
```

## Примечания

- Фотографии в dev-режиме — заглушки `PLACEHOLDER_PHOTO_*` (Telegram file_id).
  Они не загрузятся в браузере — компонент покажет fallback-плашку с эмодзи 🎨.
  В проде file_id разрезолвятся в реальные URL через Telegram CDN (Этап 10/деплой).
- Стили: CSS Modules. Никаких UI-китов. Тема автоматически берётся из CSS-переменных Telegram.
