"""Каталог имён продуктовых событий аналитики.

`event_type` в БД — обычный String, чтобы расширяться без миграций. Сервисы и хэндлеры
должны использовать константы из `EventType` вместо сырых строк.
"""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    BOT_START = "bot_start"
    REGISTRATION_START = "registration_start"
    PROFILE_COMPLETED = "profile_completed"
    PROFILE_EDITED = "profile_edited"
    PROFILE_DELETED = "profile_deleted"
    PROFILE_VIEWED = "profile_viewed"
    LIKE = "like"
    DISLIKE = "dislike"
    SUPERLIKE = "superlike"
    MATCH = "match"
    PREMIUM_SCREEN_OPENED = "premium_screen_opened"
    PREMIUM_PURCHASED = "premium_purchased"
    PREMIUM_PURCHASE_FAILED = "premium_purchase_failed"
    CREATORS_ALLEY_OPENED = "creators_alley_opened"
    CREATOR_CARD_VIEWED = "creator_card_viewed"
    CREATOR_ALLEY_JOIN_CLICKED = "creator_alley_join_clicked"
    MINIAPP_OPENED = "miniapp_opened"
    COMPLAINT_FILED = "complaint_filed"
    USER_BLOCKED = "user_blocked"
    CONTENT_REJECTED_TEXT = "content_rejected_text"
    CONTENT_REJECTED_NSFW = "content_rejected_nsfw"
    CONTENT_SENT_TO_REVIEW = "content_sent_to_review"
    FEED_POST_CREATED = "feed_post_created"
    FEED_POST_EDITED = "feed_post_edited"
    FEED_COMMENT_CREATED = "feed_comment_created"
    FEED_REACTION_SET = "feed_reaction_set"
