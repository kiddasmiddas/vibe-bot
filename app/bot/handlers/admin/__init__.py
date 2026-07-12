"""Пакет admin-хэндлеров.  Экспортирует единый admin_router."""

from __future__ import annotations

from aiogram import Router

from app.bot.handlers.admin.ads_rotation import router as ads_rotation_router
from app.bot.handlers.admin.analytics import router as analytics_router
from app.bot.handlers.admin.complaints import router as complaints_router
from app.bot.handlers.admin.creators import router as creators_router
from app.bot.handlers.admin.dictionaries import router as dicts_router
from app.bot.handlers.admin.feed import router as feed_router
from app.bot.handlers.admin.menu import router as menu_router
from app.bot.handlers.admin.notifications import router as notifications_router
from app.bot.handlers.admin.premium import router as premium_router
from app.bot.handlers.admin.promo import router as promo_router
from app.bot.handlers.admin.review import router as review_router
from app.bot.handlers.admin.settings import router as settings_router
from app.bot.handlers.admin.stopwords import router as stopwords_router
from app.bot.handlers.admin.users import router as users_router
from app.bot.handlers.admin.vibe_by_photo import router as vibe_by_photo_router
from app.bot.handlers.admin.vibes import router as vibes_router

admin_router = Router(name="admin")

# Подключаем все sub-роутеры.  Порядок важен: menu первым — он обрабатывает /admin.
admin_router.include_router(menu_router)
admin_router.include_router(users_router)
admin_router.include_router(complaints_router)
admin_router.include_router(creators_router)
admin_router.include_router(feed_router)
admin_router.include_router(premium_router)
admin_router.include_router(promo_router)
admin_router.include_router(ads_rotation_router)
admin_router.include_router(notifications_router)
admin_router.include_router(dicts_router)
admin_router.include_router(vibes_router)
admin_router.include_router(review_router)
admin_router.include_router(stopwords_router)
admin_router.include_router(settings_router)
admin_router.include_router(analytics_router)
admin_router.include_router(vibe_by_photo_router)

__all__ = ["admin_router"]
