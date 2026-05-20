"""Клавиатуры и CallbackData для админского режима (Этап 10)."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ---------------------------------------------------------------------------
# CallbackData классы
# ---------------------------------------------------------------------------


class AdminMenuCb(CallbackData, prefix="adm_menu"):
    action: str  # users|complaints|alley|premium|ads|dicts|settings|review|stopwords|analytics


class AdminUserActionCb(CallbackData, prefix="adm_user"):
    action: str  # ban|unban|hide_profile|show_profile|search|make_mod|remove_mod
    target_user_id: int = 0


class AdminComplaintActionCb(CallbackData, prefix="adm_cpl"):
    action: str  # reject|ban_target|list_new|list_resolved|list_rejected|skip|card
    complaint_id: int = 0
    offset: int = 0  # текущая позиция в очереди (для пагинации карточки)
    status: str = "new"  # статус очереди (new|in_progress|resolved|rejected)


class AdminAlleyCb(CallbackData, prefix="adm_alley"):
    action: str  # list|create|open|extend|unpublish|delete|dur_1|dur_3|dur_6|dur_12
    post_id: int = 0


class AdminPremiumCb(CallbackData, prefix="adm_prem"):
    action: str  # grant|revoke|dur_30|dur_90|dur_365
    target_user_id: int = 0


class AdminPromoCb(CallbackData, prefix="adm_promo"):
    action: str  # create|list|status|segment_all|segment_free|segment_premium|now|scheduled
    promo_id: int = 0


class AdminDictCb(CallbackData, prefix="adm_dict"):
    action: str  # fandoms|interests|vibes|cats|reasons|add|edit|deactivate|activate|open
    model: str = ""  # fandom|interest|vibe|creator_category|complaint_reason
    item_id: int = 0


class AdminReviewCb(CallbackData, prefix="adm_rev"):
    # action: profiles|posts|approve_profile|reject_profile|ban_profile_user
    # | approve_post|delete_post|ban_post_author
    action: str
    item_id: int = 0


class AdminStopWordCb(CallbackData, prefix="adm_sw"):
    action: str  # list|add|toggle|edit|search|cat_all|cat_hate|cat_link|cat_adult|cat_other
    sw_id: int = 0
    category: str = ""


class AdminSettingsCb(CallbackData, prefix="adm_set"):
    action: str  # list|edit
    key: str = ""


class AdminAnalyticsCb(CallbackData, prefix="adm_ana"):
    period: str  # day|week|month


class AdminFeedCb(CallbackData, prefix="adm_feed"):
    # action: list_active|list_hidden|list_pending
    #        |hide_post|delete_post|approve_post
    #        |delete_comment|ask_comment_id
    #        |restrict|unrestrict
    action: str
    item_id: int = 0  # post_id или comment_id в зависимости от action


class AdminReviewProfileCb(CallbackData, prefix="adm_rvp"):
    # action: approve|reject|skip|card|list|menu
    action: str
    profile_id: int = 0
    offset: int = 0


# ---------------------------------------------------------------------------
# Keyboard builders
# ---------------------------------------------------------------------------


def admin_back_home_kb() -> InlineKeyboardMarkup:
    """Мини-клавиатура с единственной кнопкой возврата в главное меню /admin.

    Для сообщений, которые иначе остались бы без клавиатуры (финал FSM,
    пустые списки, текстовые промпты).
    """
    from app.texts.admin import ADMIN_MENU_BTN_HOME

    b = InlineKeyboardBuilder()
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    return b.as_markup()


def admin_main_menu_kb() -> InlineKeyboardMarkup:
    from app.texts.admin import (
        ADMIN_MENU_BTN_ADS,
        ADMIN_MENU_BTN_ALLEY,
        ADMIN_MENU_BTN_ANALYTICS,
        ADMIN_MENU_BTN_COMPLAINTS,
        ADMIN_MENU_BTN_DICTS,
        ADMIN_MENU_BTN_FEED,
        ADMIN_MENU_BTN_PREMIUM,
        ADMIN_MENU_BTN_REVIEW,
        ADMIN_MENU_BTN_SETTINGS,
        ADMIN_MENU_BTN_STOPWORDS,
        ADMIN_MENU_BTN_USERS,
    )

    b = InlineKeyboardBuilder()
    b.button(text=ADMIN_MENU_BTN_USERS, callback_data=AdminMenuCb(action="users"))
    b.button(text=ADMIN_MENU_BTN_COMPLAINTS, callback_data=AdminMenuCb(action="complaints"))
    b.button(text=ADMIN_MENU_BTN_ALLEY, callback_data=AdminMenuCb(action="alley"))
    b.button(text=ADMIN_MENU_BTN_FEED, callback_data=AdminMenuCb(action="feed"))
    b.button(text=ADMIN_MENU_BTN_PREMIUM, callback_data=AdminMenuCb(action="premium"))
    b.button(text=ADMIN_MENU_BTN_ADS, callback_data=AdminMenuCb(action="ads"))
    b.button(text=ADMIN_MENU_BTN_DICTS, callback_data=AdminMenuCb(action="dicts"))
    b.button(text=ADMIN_MENU_BTN_SETTINGS, callback_data=AdminMenuCb(action="settings"))
    b.button(text=ADMIN_MENU_BTN_REVIEW, callback_data=AdminMenuCb(action="review"))
    b.button(text=ADMIN_MENU_BTN_STOPWORDS, callback_data=AdminMenuCb(action="stopwords"))
    b.button(text=ADMIN_MENU_BTN_ANALYTICS, callback_data=AdminMenuCb(action="analytics"))
    b.adjust(2)
    return b.as_markup()


def users_menu_kb() -> InlineKeyboardMarkup:
    """Меню раздела «Пользователи»: поиск + назад. Список выгружается файлом."""
    from app.texts.admin import ADMIN_MENU_BTN_BACK, USERS_BTN_SEARCH

    b = InlineKeyboardBuilder()
    b.button(text=USERS_BTN_SEARCH, callback_data=AdminUserActionCb(action="search"))
    b.button(text=ADMIN_MENU_BTN_BACK, callback_data=AdminMenuCb(action="menu"))
    b.adjust(1)
    return b.as_markup()


def user_action_kb(
    target_user_id: int,
    *,
    telegram_id: int,
    is_banned: bool,
    is_hidden: bool,
    is_moderator: bool = False,
    username: str | None = None,
    can_manage_moderators: bool = False,
    target_is_admin: bool = False,
) -> InlineKeyboardMarkup:
    from app.texts.admin import (
        ADMIN_MENU_BTN_HOME,
        USERS_BTN_BAN,
        USERS_BTN_HIDE_PROFILE,
        USERS_BTN_MAKE_MOD,
        USERS_BTN_OPEN_TG,
        USERS_BTN_REMOVE_MOD,
        USERS_BTN_SHOW_PROFILE,
        USERS_BTN_UNBAN,
    )

    b = InlineKeyboardBuilder()
    if is_banned:
        b.button(
            text=USERS_BTN_UNBAN,
            callback_data=AdminUserActionCb(action="unban", target_user_id=target_user_id),
        )
    else:
        b.button(
            text=USERS_BTN_BAN,
            callback_data=AdminUserActionCb(action="ban", target_user_id=target_user_id),
        )
    if is_hidden:
        b.button(
            text=USERS_BTN_SHOW_PROFILE,
            callback_data=AdminUserActionCb(action="show_profile", target_user_id=target_user_id),
        )
    else:
        b.button(
            text=USERS_BTN_HIDE_PROFILE,
            callback_data=AdminUserActionCb(action="hide_profile", target_user_id=target_user_id),
        )
    # Назначение/снятие модератора — только полному админу и не для админ-цели
    # (администратора модератором не назначают). Модератор кнопки не видит.
    if can_manage_moderators and not target_is_admin:
        if is_moderator:
            b.button(
                text=USERS_BTN_REMOVE_MOD,
                callback_data=AdminUserActionCb(action="remove_mod", target_user_id=target_user_id),
            )
        else:
            b.button(
                text=USERS_BTN_MAKE_MOD,
                callback_data=AdminUserActionCb(action="make_mod", target_user_id=target_user_id),
            )
    # «Открыть в TG»: target_user_id — внутренний User.id, для ссылки нужен
    # настоящий telegram_id. С username берём t.me-ссылку (всегда валидна),
    # иначе — tg://user?id. tg://user?id с чужим/внутренним id → BUTTON_USER_INVALID.
    if username:
        b.button(text=USERS_BTN_OPEN_TG, url=f"https://t.me/{username}")
    else:
        b.button(text=USERS_BTN_OPEN_TG, url=f"tg://user?id={telegram_id}")
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2)
    return b.as_markup()


def complaint_list_kb() -> InlineKeyboardMarkup:
    from app.texts.admin import (
        ADMIN_MENU_BTN_BACK,
        COMPLAINTS_BTN_NEW,
        COMPLAINTS_BTN_REJECTED,
        COMPLAINTS_BTN_RESOLVED,
    )

    b = InlineKeyboardBuilder()
    b.button(text=COMPLAINTS_BTN_NEW, callback_data=AdminComplaintActionCb(action="list_new"))
    b.button(
        text=COMPLAINTS_BTN_RESOLVED, callback_data=AdminComplaintActionCb(action="list_resolved")
    )
    b.button(
        text=COMPLAINTS_BTN_REJECTED, callback_data=AdminComplaintActionCb(action="list_rejected")
    )
    b.button(text=ADMIN_MENU_BTN_BACK, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2)
    return b.as_markup()


def complaint_card_kb(
    complaint_id: int,
    offset: int,
    status: str,
) -> InlineKeyboardMarkup:
    """Клавиатура карточки жалобы (пагинированный просмотр одной жалобы).

    Кнопки: Отклонить | Забанить нарушителя | Пропустить | Назад | В админ-меню
    «Пропустить» = перейти к offset+1 без смены статуса текущей жалобы.
    «Назад» = перейти к offset-1 (если offset > 0), иначе в список фильтрации.
    """
    from app.texts.admin import (
        ADMIN_MENU_BTN_BACK,
        ADMIN_MENU_BTN_HOME,
        COMPLAINTS_BTN_BAN_TARGET,
        COMPLAINTS_BTN_REJECT,
        COMPLAINTS_BTN_SKIP,
    )

    b = InlineKeyboardBuilder()
    b.button(
        text=COMPLAINTS_BTN_REJECT,
        callback_data=AdminComplaintActionCb(
            action="reject",
            complaint_id=complaint_id,
            offset=offset,
            status=status,
        ),
    )
    b.button(
        text=COMPLAINTS_BTN_BAN_TARGET,
        callback_data=AdminComplaintActionCb(
            action="ban_target",
            complaint_id=complaint_id,
            offset=offset,
            status=status,
        ),
    )
    b.button(
        text=COMPLAINTS_BTN_SKIP,
        callback_data=AdminComplaintActionCb(
            action="skip",
            complaint_id=complaint_id,
            offset=offset + 1,
            status=status,
        ),
    )
    # «Назад»: возвращаемся на offset-1 или в список фильтрации
    if offset > 0:
        b.button(
            text=ADMIN_MENU_BTN_BACK,
            callback_data=AdminComplaintActionCb(
                action="card",
                complaint_id=0,
                offset=offset - 1,
                status=status,
            ),
        )
    else:
        b.button(
            text=ADMIN_MENU_BTN_BACK,
            callback_data=AdminMenuCb(action="complaints"),
        )
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2)
    return b.as_markup()


def alley_main_kb() -> InlineKeyboardMarkup:
    from app.texts.admin import ADMIN_MENU_BTN_BACK, ALLEY_BTN_CREATE, ALLEY_BTN_LIST

    b = InlineKeyboardBuilder()
    b.button(text=ALLEY_BTN_LIST, callback_data=AdminAlleyCb(action="list"))
    b.button(text=ALLEY_BTN_CREATE, callback_data=AdminAlleyCb(action="create"))
    b.button(text=ADMIN_MENU_BTN_BACK, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2)
    return b.as_markup()


def alley_post_kb(post_id: int) -> InlineKeyboardMarkup:
    from app.texts.admin import (
        ADMIN_MENU_BTN_BACK,
        ADMIN_MENU_BTN_HOME,
        ALLEY_BTN_DELETE,
        ALLEY_BTN_EXTEND,
        ALLEY_BTN_UNPUBLISH,
    )

    b = InlineKeyboardBuilder()
    b.button(text=ALLEY_BTN_EXTEND, callback_data=AdminAlleyCb(action="extend", post_id=post_id))
    b.button(
        text=ALLEY_BTN_UNPUBLISH, callback_data=AdminAlleyCb(action="unpublish", post_id=post_id)
    )
    b.button(text=ALLEY_BTN_DELETE, callback_data=AdminAlleyCb(action="delete", post_id=post_id))
    b.button(text=ADMIN_MENU_BTN_BACK, callback_data=AdminAlleyCb(action="list"))
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2)
    return b.as_markup()


def alley_duration_kb(prefix: str = "dur") -> InlineKeyboardMarkup:
    from app.texts.admin import (
        ADMIN_MENU_BTN_HOME,
        ALLEY_CREATE_BTN_1M,
        ALLEY_CREATE_BTN_3M,
        ALLEY_CREATE_BTN_6M,
        ALLEY_CREATE_BTN_12M,
    )

    b = InlineKeyboardBuilder()
    b.button(text=ALLEY_CREATE_BTN_1M, callback_data=AdminAlleyCb(action=f"{prefix}_1"))
    b.button(text=ALLEY_CREATE_BTN_3M, callback_data=AdminAlleyCb(action=f"{prefix}_3"))
    b.button(text=ALLEY_CREATE_BTN_6M, callback_data=AdminAlleyCb(action=f"{prefix}_6"))
    b.button(text=ALLEY_CREATE_BTN_12M, callback_data=AdminAlleyCb(action=f"{prefix}_12"))
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2)
    return b.as_markup()


def premium_action_kb(target_user_id: int, *, is_premium: bool) -> InlineKeyboardMarkup:
    from app.texts.admin import ADMIN_MENU_BTN_HOME, PREMIUM_BTN_GRANT, PREMIUM_BTN_REVOKE

    b = InlineKeyboardBuilder()
    b.button(
        text=PREMIUM_BTN_GRANT,
        callback_data=AdminPremiumCb(action="grant", target_user_id=target_user_id),
    )
    if is_premium:
        b.button(
            text=PREMIUM_BTN_REVOKE,
            callback_data=AdminPremiumCb(action="revoke", target_user_id=target_user_id),
        )
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2)
    return b.as_markup()


def premium_duration_kb(target_user_id: int) -> InlineKeyboardMarkup:
    from app.texts.admin import (
        ADMIN_MENU_BTN_HOME,
        PREMIUM_BTN_30D,
        PREMIUM_BTN_90D,
        PREMIUM_BTN_365D,
    )

    b = InlineKeyboardBuilder()
    b.button(
        text=PREMIUM_BTN_30D,
        callback_data=AdminPremiumCb(action="dur_30", target_user_id=target_user_id),
    )
    b.button(
        text=PREMIUM_BTN_90D,
        callback_data=AdminPremiumCb(action="dur_90", target_user_id=target_user_id),
    )
    b.button(
        text=PREMIUM_BTN_365D,
        callback_data=AdminPremiumCb(action="dur_365", target_user_id=target_user_id),
    )
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    b.adjust(3)
    return b.as_markup()


def promo_segment_kb() -> InlineKeyboardMarkup:
    from app.texts.admin import (
        ADMIN_MENU_BTN_HOME,
        PROMO_CREATE_BTN_ALL,
        PROMO_CREATE_BTN_FREE,
        PROMO_CREATE_BTN_PREMIUM,
    )

    b = InlineKeyboardBuilder()
    b.button(
        text=PROMO_CREATE_BTN_ALL,
        callback_data=AdminPromoCb(action="segment_all"),
    )
    b.button(
        text=PROMO_CREATE_BTN_FREE,
        callback_data=AdminPromoCb(action="segment_free"),
    )
    b.button(
        text=PROMO_CREATE_BTN_PREMIUM,
        callback_data=AdminPromoCb(action="segment_premium"),
    )
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    b.adjust(3)
    return b.as_markup()


def dicts_menu_kb() -> InlineKeyboardMarkup:
    from app.texts.admin import (
        ADMIN_MENU_BTN_BACK,
        DICTS_BTN_COMPLAINT_REASONS,
        DICTS_BTN_CREATOR_CATS,
        DICTS_BTN_FANDOMS,
        DICTS_BTN_INTERESTS,
        DICTS_BTN_VIBES,
    )

    b = InlineKeyboardBuilder()
    b.button(text=DICTS_BTN_FANDOMS, callback_data=AdminDictCb(action="fandoms", model="fandom"))
    b.button(
        text=DICTS_BTN_INTERESTS, callback_data=AdminDictCb(action="interests", model="interest")
    )
    b.button(text=DICTS_BTN_VIBES, callback_data=AdminDictCb(action="vibes", model="vibe"))
    b.button(
        text=DICTS_BTN_CREATOR_CATS,
        callback_data=AdminDictCb(action="cats", model="creator_category"),
    )
    b.button(
        text=DICTS_BTN_COMPLAINT_REASONS,
        callback_data=AdminDictCb(action="reasons", model="complaint_reason"),
    )
    b.button(text=ADMIN_MENU_BTN_BACK, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2)
    return b.as_markup()


def dict_item_kb(model: str, item_id: int, *, is_active: bool) -> InlineKeyboardMarkup:
    from app.texts.admin import (
        ADMIN_MENU_BTN_BACK,
        ADMIN_MENU_BTN_HOME,
        DICTS_BTN_ACTIVATE,
        DICTS_BTN_DEACTIVATE,
        DICTS_BTN_EDIT,
    )

    b = InlineKeyboardBuilder()
    b.button(
        text=DICTS_BTN_EDIT,
        callback_data=AdminDictCb(action="edit", model=model, item_id=item_id),
    )
    if is_active:
        b.button(
            text=DICTS_BTN_DEACTIVATE,
            callback_data=AdminDictCb(action="deactivate", model=model, item_id=item_id),
        )
    else:
        b.button(
            text=DICTS_BTN_ACTIVATE,
            callback_data=AdminDictCb(action="activate", model=model, item_id=item_id),
        )
    _MODEL_TO_ACTION: dict[str, str] = {
        "fandom": "fandoms",
        "interest": "interests",
        "vibe": "vibes",
        "creator_category": "cats",
        "complaint_reason": "reasons",
    }
    back_action = _MODEL_TO_ACTION.get(model, model + "s")
    b.button(text=ADMIN_MENU_BTN_BACK, callback_data=AdminDictCb(action=back_action, model=model))
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2)
    return b.as_markup()


def review_menu_kb() -> InlineKeyboardMarkup:
    from app.texts.admin import ADMIN_MENU_BTN_BACK, REVIEW_POSTS_BTN, REVIEW_PROFILES_BTN

    b = InlineKeyboardBuilder()
    b.button(text=REVIEW_PROFILES_BTN, callback_data=AdminReviewCb(action="profiles"))
    b.button(text=REVIEW_POSTS_BTN, callback_data=AdminReviewCb(action="posts"))
    b.button(text=ADMIN_MENU_BTN_BACK, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2)
    return b.as_markup()


def review_profile_card_kb(*, profile_id: int, offset: int) -> InlineKeyboardMarkup:
    """Клавиатура карточки анкеты на проверке (пагинированный просмотр).

    Ряд 1: Одобрить | Отклонить
    Ряд 2: Пропустить
    Ряд 3: В админ-меню
    «Пропустить» переходит к offset+1 без изменения статуса текущей анкеты.
    """
    from app.texts.admin import (
        ADMIN_MENU_BTN_HOME,
        REVIEW_BTN_APPROVE_NEW,
        REVIEW_BTN_REJECT_NEW,
        REVIEW_BTN_SKIP,
    )

    b = InlineKeyboardBuilder()
    b.button(
        text=REVIEW_BTN_APPROVE_NEW,
        callback_data=AdminReviewProfileCb(
            action="approve",
            profile_id=profile_id,
            offset=offset,
        ),
    )
    b.button(
        text=REVIEW_BTN_REJECT_NEW,
        callback_data=AdminReviewProfileCb(
            action="reject",
            profile_id=profile_id,
            offset=offset,
        ),
    )
    b.button(
        text=REVIEW_BTN_SKIP,
        callback_data=AdminReviewProfileCb(
            action="skip",
            profile_id=profile_id,
            offset=offset + 1,
        ),
    )
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2, 1, 1)
    return b.as_markup()


def review_post_kb(post_id: int) -> InlineKeyboardMarkup:
    from app.texts.admin import (
        ADMIN_MENU_BTN_BACK,
        ADMIN_MENU_BTN_HOME,
        REVIEW_BTN_APPROVE,
        REVIEW_BTN_BAN_USER,
        REVIEW_BTN_DELETE_POST,
    )

    b = InlineKeyboardBuilder()
    b.button(
        text=REVIEW_BTN_APPROVE,
        callback_data=AdminReviewCb(action="approve_post", item_id=post_id),
    )
    b.button(
        text=REVIEW_BTN_DELETE_POST,
        callback_data=AdminReviewCb(action="delete_post", item_id=post_id),
    )
    b.button(
        text=REVIEW_BTN_BAN_USER,
        callback_data=AdminReviewCb(action="ban_post_author", item_id=post_id),
    )
    b.button(text=ADMIN_MENU_BTN_BACK, callback_data=AdminReviewCb(action="posts"))
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2)
    return b.as_markup()


def stopword_list_kb(sw_id: int) -> InlineKeyboardMarkup:
    from app.texts.admin import ADMIN_MENU_BTN_HOME, STOPWORDS_BTN_EDIT, STOPWORDS_BTN_TOGGLE

    b = InlineKeyboardBuilder()
    b.button(
        text=STOPWORDS_BTN_TOGGLE,
        callback_data=AdminStopWordCb(action="toggle", sw_id=sw_id),
    )
    b.button(
        text=STOPWORDS_BTN_EDIT,
        callback_data=AdminStopWordCb(action="edit", sw_id=sw_id),
    )
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2)
    return b.as_markup()


def feed_admin_menu_kb() -> InlineKeyboardMarkup:
    from app.texts.admin import (
        ADMIN_MENU_BTN_BACK,
        FEED_ADMIN_BTN_ACTIVE,
        FEED_ADMIN_BTN_HIDDEN,
        FEED_ADMIN_BTN_PENDING,
    )

    b = InlineKeyboardBuilder()
    b.button(text=FEED_ADMIN_BTN_ACTIVE, callback_data=AdminFeedCb(action="list_active"))
    b.button(text=FEED_ADMIN_BTN_HIDDEN, callback_data=AdminFeedCb(action="list_hidden"))
    b.button(text=FEED_ADMIN_BTN_PENDING, callback_data=AdminFeedCb(action="list_pending"))
    b.button(text=ADMIN_MENU_BTN_BACK, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2)
    return b.as_markup()


def feed_post_actions_kb(post_id: int, *, is_pending: bool) -> InlineKeyboardMarkup:
    from app.texts.admin import (
        ADMIN_MENU_BTN_BACK,
        ADMIN_MENU_BTN_HOME,
        FEED_ADMIN_BTN_APPROVE,
        FEED_ADMIN_BTN_DELETE,
        FEED_ADMIN_BTN_DELETE_COMMENT,
        FEED_ADMIN_BTN_HIDE,
        FEED_ADMIN_BTN_RESTRICT,
        FEED_ADMIN_BTN_UNRESTRICT,
    )

    b = InlineKeyboardBuilder()
    b.button(
        text=FEED_ADMIN_BTN_HIDE,
        callback_data=AdminFeedCb(action="hide_post", item_id=post_id),
    )
    b.button(
        text=FEED_ADMIN_BTN_DELETE,
        callback_data=AdminFeedCb(action="delete_post", item_id=post_id),
    )
    if is_pending:
        b.button(
            text=FEED_ADMIN_BTN_APPROVE,
            callback_data=AdminFeedCb(action="approve_post", item_id=post_id),
        )
    b.button(
        text=FEED_ADMIN_BTN_DELETE_COMMENT,
        callback_data=AdminFeedCb(action="ask_comment_id", item_id=post_id),
    )
    b.button(
        text=FEED_ADMIN_BTN_RESTRICT,
        callback_data=AdminFeedCb(action="restrict", item_id=post_id),
    )
    b.button(
        text=FEED_ADMIN_BTN_UNRESTRICT,
        callback_data=AdminFeedCb(action="unrestrict", item_id=post_id),
    )
    b.button(text=ADMIN_MENU_BTN_BACK, callback_data=AdminMenuCb(action="feed"))
    b.button(text=ADMIN_MENU_BTN_HOME, callback_data=AdminMenuCb(action="menu"))
    b.adjust(2)
    return b.as_markup()


def analytics_kb() -> InlineKeyboardMarkup:
    from app.texts.admin import (
        ADMIN_MENU_BTN_BACK,
        ANALYTICS_BTN_DAY,
        ANALYTICS_BTN_MONTH,
        ANALYTICS_BTN_WEEK,
    )

    b = InlineKeyboardBuilder()
    b.button(text=ANALYTICS_BTN_DAY, callback_data=AdminAnalyticsCb(period="day"))
    b.button(text=ANALYTICS_BTN_WEEK, callback_data=AdminAnalyticsCb(period="week"))
    b.button(text=ANALYTICS_BTN_MONTH, callback_data=AdminAnalyticsCb(period="month"))
    b.button(text=ADMIN_MENU_BTN_BACK, callback_data=AdminMenuCb(action="menu"))
    b.adjust(3)
    return b.as_markup()
