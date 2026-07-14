"""Тексты для админского режима бота (Этап 10)."""

from __future__ import annotations

# --- Доступ ---
NOT_ADMIN = "Команда не найдена."

# --- Главное меню ---
ADMIN_MENU_TITLE = "Панель администратора"
ADMIN_MENU_BTN_USERS = "Пользователи"
ADMIN_MENU_BTN_COMPLAINTS = "Жалобы"
ADMIN_MENU_BTN_ALLEY = "Аллея"
ADMIN_MENU_BTN_PREMIUM = "Premium"
ADMIN_MENU_BTN_ADS = "Реклама"
ADMIN_MENU_BTN_NOTIF = "🔔 Уведомления"
ADMIN_MENU_BTN_DICTS = "Справочники"
# Скрытая общая панель ключ-значение (см. _SHOW_GENERAL_SETTINGS) — НЕ путать
# с кураторским разделом «⚙️ Настройки» (ADMIN_MENU_BTN_APP_CFG).
ADMIN_MENU_BTN_SETTINGS = "Настройки"
ADMIN_MENU_BTN_APP_CFG = "⚙️ Настройки"

# --- Категории главного админ-меню (5 разделов вместо простыни кнопок) ---
CAT_MODERATION = "🛡 Модерация"
CAT_USERS = "👥 Пользователи"
CAT_CONTENT = "📢 Контент"
CAT_ANALYTICS = "📊 Аналитика"
CAT_MODERATION_TITLE = "🛡 <b>Модерация</b>\n\nЖалобы, очередь проверки, запросы вайба, стоп-листы."
CAT_USERS_TITLE = "👥 <b>Пользователи</b>\n\nПоиск и бан пользователей, выдача Premium."
CAT_CONTENT_TITLE = "📢 <b>Контент</b>\n\nЛента, Аллея креаторов, авто-реклама."
ADMIN_MENU_BTN_REVIEW = "На проверке"
ADMIN_MENU_BTN_STOPWORDS = "Стоп-листы"
ADMIN_MENU_BTN_ANALYTICS = "Аналитика"
ADMIN_MENU_BTN_VBP = "🖼 Вайб по фото"
ADMIN_MENU_BTN_BACK = "Назад"
ADMIN_MENU_BTN_HOME = "🏠 В админ-меню"

# --- Пользователи ---
USERS_MENU = (
    "👥 <b>Пользователи</b>\n\n"
    "🔍 Найти конкретного — по Telegram ID, @username или нику.\n"
    "📤 Выгрузить всех — CSV-файлом."
)
USERS_LIST_CAPTION = "Список пользователей: {count} чел."
USERS_LIST_EMPTY = "В боте пока нет ни одного пользователя."
USERS_BTN_SEARCH = "🔍 Найти пользователя"
USERS_BTN_EXPORT = "📤 Выгрузить всех"
USERS_SEARCH_PROMPT = "Введите Telegram ID, @username или никнейм пользователя:"
USERS_NOT_FOUND = "Пользователь не найден."
USERS_CARD = (
    "<b>Пользователь #{user_id}</b>\n"
    "TG ID: <code>{telegram_id}</code>\n"
    "Username: @{username}\n"
    "Никнейм: {nickname}\n"
    "Статус: {status}\n"
    "Забанен: {banned}"
)
USERS_STATUS_ADMIN = "👑 Администратор"
USERS_STATUS_MODERATOR = "🛡 Модератор"
USERS_STATUS_PREMIUM = "💎 Premium"
USERS_STATUS_REGULAR = "👤 Обычный пользователь"
USERS_BTN_MAKE_MOD = "🛡 Сделать модератором"
USERS_BTN_REMOVE_MOD = "Снять модератора"
USERS_MOD_GRANTED = "Пользователь назначен модератором."
USERS_MOD_REVOKED = "Роль модератора снята."
USERS_BTN_BAN = "Забанить"
USERS_BTN_UNBAN = "Разбанить"
USERS_BTN_HIDE_PROFILE = "Скрыть анкету"
USERS_BTN_SHOW_PROFILE = "Открыть анкету"
USERS_BTN_OPEN_TG = "Открыть в TG"
USERS_BANNED = "Пользователь забанен."
USERS_UNBANNED = "Пользователь разбанен."
USERS_PROFILE_HIDDEN = "Анкета скрыта."
USERS_PROFILE_SHOWN = "Анкета показана."

# --- Жалобы ---
COMPLAINTS_SELECT_STATUS = "Жалобы — выберите статус:"
COMPLAINTS_HEADER = "<b>Жалобы (статус: {status})</b>\n\nВсего: {total}"
COMPLAINTS_ITEM = (
    "#{id} от {from_id} → {target_id}\n"
    "Причина: {reason}\n"
    "Комментарий: {comment}\n"
    "Статус: {status}\n"
    "Создана: {created_at}"
)
COMPLAINTS_EMPTY = "Жалоб нет."
COMPLAINTS_BTN_NEW = "Новые"
COMPLAINTS_BTN_RESOLVED = "Решённые"
COMPLAINTS_BTN_REJECTED = "Отклонённые"
COMPLAINTS_BTN_REJECT = "Отклонить"
COMPLAINTS_BTN_BAN_TARGET = "Забанить нарушителя"
COMPLAINTS_BTN_SKIP = "Пропустить"
COMPLAINTS_BTN_BACK_LIST = "Назад"
COMPLAINTS_RESOLVED = "Жалоба #{id} — решена."
COMPLAINTS_REJECTED = "Жалоба #{id} — отклонена."
COMPLAINTS_TARGET_BANNED = "Нарушитель забанен, жалоба решена."
COMPLAINTS_NOT_FOUND = "Жалоба не найдена."

# Карточка жалобы (caption под фото нарушителя).
# {profile_text}  — текст анкеты из build_rendered_profile
# {violator_nick} — nickname нарушителя (уже в profile_text, дублируется в заголовке)
# {violator_username} — @username или пустая строка
# {reporter_username} — @username репортера или его TG-id
# {reason}        — текст причины (reason_id в виде строки)
# {comment}       — комментарий к жалобе или "—"
# {page}          — номер карточки (1-based)
# {total}         — общее количество жалоб в очереди
COMPLAINTS_CARD_CAPTION = (
    "{profile_text}"
    "\n\n"
    "— Жалоба #{complaint_id} ({page}/{total})\n"
    "Репортер: {reporter_username}\n"
    "Причина: {reason}\n"
    "Комментарий: {comment}"
)
COMPLAINTS_CARD_NO_PROFILE = (
    "<b>Нарушитель</b> (user_id={violator_id}){violator_username_part}\n"
    "Анкета отсутствует или удалена.\n"
    "\n"
    "— Жалоба #{complaint_id} ({page}/{total})\n"
    "Репортер: {reporter_username}\n"
    "Причина: {reason}\n"
    "Комментарий: {comment}"
)
COMPLAINTS_REASON_UNKNOWN = "#{reason_id}"

# --- Аллея (CreatorPost) ---
ALLEY_PHOTO_MAX_REACHED = "Максимум 3 фото. Введите /done для завершения."
ALLEY_PHOTO_SAVED = "Фото {n}/3 сохранено. Ещё или /done."
ALLEY_PHOTO_REQUIRED = "Нужно хотя бы одно фото."
ALLEY_MENU = "Управление Аллеей креаторов"
ALLEY_BTN_LIST = "Список постов"
ALLEY_BTN_CREATE = "Создать пост"
ALLEY_LIST_EMPTY = "Постов нет."
ALLEY_POST_CARD = (
    "<b>Пост #{id}</b>\n"
    "Автор: {author}\n"
    "Категория: {category_id}\n"
    "Описание: {description}\n"
    "Ссылка: {telegram_link}\n"
    "Опубликован: {published}\n"
    "Истекает: {expires_at}"
)
ALLEY_BTN_EXTEND = "Продлить"
ALLEY_BTN_UNPUBLISH = "Снять"
ALLEY_BTN_DELETE = "Удалить"
ALLEY_UNPUBLISHED = "Пост снят с публикации."
ALLEY_DELETED = "Пост удалён."
ALLEY_EXTENDED = "Срок поста продлён до {expires_at}."
ALLEY_CREATE_ASK_AUTHOR = "Введите отображаемое имя автора:"
ALLEY_CREATE_ASK_CATEGORY = "Выберите категорию поста:"
ALLEY_CREATE_ASK_DESC = "Введите описание поста:"
ALLEY_CREATE_ASK_LINK = "Введите ссылку на Telegram-канал автора:"
ALLEY_CREATE_ASK_PHOTOS = "Загружайте фото поста по одному (до 3 штук). /done — завершить."
ALLEY_CREATE_ASK_DURATION = "Выберите срок размещения:"
ALLEY_CREATE_BTN_1M = "1 месяц"
ALLEY_CREATE_BTN_3M = "3 месяца"
ALLEY_CREATE_BTN_6M = "6 месяцев"
ALLEY_CREATE_BTN_12M = "12 месяцев"
ALLEY_CREATED = "Пост #{id} создан и опубликован."
ALLEY_EXTEND_ASK_DURATION = "На сколько месяцев продлить?"
ALLEY_FILTER_BTN_PUBLISHED = "Опубликованные"
ALLEY_FILTER_BTN_ALL = "Все"
ALLEY_FILTER_BTN_EXPIRED = "Истёкшие"

# --- Premium ---
PREMIUM_MENU = "Управление Premium"
PREMIUM_SEARCH_PROMPT = "Введите telegram_id, @username или никнейм пользователя:"
PREMIUM_NOT_FOUND = "Пользователь не найден."
PREMIUM_USER_CARD = (
    "<b>Пользователь #{user_id}</b>\n"
    "TG ID: <code>{telegram_id}</code>\n"
    "Premium: {premium}\n"
    "До: {premium_until}"
)
PREMIUM_ASK_DURATION = "Выберите длительность Premium:"
PREMIUM_BTN_30D = "30 дней"
PREMIUM_BTN_90D = "90 дней"
PREMIUM_BTN_365D = "365 дней"
PREMIUM_GRANT_ASK_DURATION = "Выберите длительность:"
PREMIUM_BTN_GRANT = "Выдать Premium"
PREMIUM_BTN_REVOKE = "Отозвать Premium"
PREMIUM_GRANTED = "Premium выдан пользователю #{user_id} до {until}."
PREMIUM_REVOKED = "Premium отозван у пользователя #{user_id}."

# --- Реклама (PromoPost) ---
PROMO_MENU = "Реклама и рассылки"
PROMO_BTN_CREATE = "Создать рассылку"
PROMO_BTN_CREATE_ANNOUNCEMENT = "Создать объявление"
PROMO_BTN_LIST = "Список рассылок"
PROMO_BTN_ROTATION = "🔄 Ротация рекламы"
PROMO_CREATE_ASK_TEXT = "Введите текст рассылки:"
PROMO_CREATE_ASK_MEDIA = "Прикрепите медиа (фото/видео) или отправьте /skip:"
PROMO_CREATE_ASK_SEGMENT = "Выберите аудиторию:"
PROMO_CREATE_BTN_ALL = "Все"
PROMO_CREATE_BTN_FREE = "Без Premium"
PROMO_CREATE_BTN_PREMIUM = "С Premium"
PROMO_CREATE_ASK_SCHEDULE = (
    "Введите дату/время в формате ГГГГ-ММ-ДД ЧЧ:ММ или /now для немедленной отправки:"
)
PROMO_CREATED = "Рассылка #{id} создана."
PROMO_SCHEDULED = "Рассылка #{id} запланирована на {scheduled_at}."
PROMO_LAUNCHED = "Рассылка #{id} поставлена в очередь — начнётся в течение минуты."
ANNOUNCEMENT_CREATE_ASK_TEXT = "Введите текст объявления для всех пользователей:"
ANNOUNCEMENT_CREATE_ASK_MEDIA = (
    "Прикрепите медиа к объявлению (фото/видео/GIF) или отправьте /skip:"
)
ANNOUNCEMENT_LAUNCHED = (
    "Объявление #{id} поставлено в очередь для {count} пользователей — "
    "рассылка начнётся в течение минуты."
)
ANNOUNCEMENT_NO_RECIPIENTS = "Нет получателей для объявления."
PROMO_SCHEDULE_INVALID = "Неверный формат даты. Используйте ГГГГ-ММ-ДД ЧЧ:ММ."
PROMO_STATUS = (
    "<b>Рассылка #{id}</b>\n"
    "Статус: {status}\n"
    "Всего: {total}\n"
    "Доставлено: {delivered}\n"
    "Ошибок: {failed}"
)
PROMO_LIST_ITEM = "#{id} [{status}] {title_or_text}"
PROMO_EMPTY = "Рассылок нет."
PROMO_BTN_STATUS = "Посмотреть статус"

# --- Справочники ---
DICTS_BTN_ACTIONS = "Действия"

# --- Справочники: раздел «Вайбы» (пикер страниц с коллажами) ---
VIBES_PAGE_CAPTION = (
    "🎨 <b>Вайбы</b> · стр. {page}/{total}\n\nНажмите номер вайба, чтобы открыть и переименовать."
)
VIBES_PAGE_NO_IMAGE = "\n\n⚠️ У этой страницы нет картинки-коллажа — загрузите её кнопкой ниже."
VIBES_BTN_PAGE_IMAGE = "🖼 Заменить картинку страницы"
VIBES_CARD = "🎨 <b>Вайб №{number}</b>\n\nНазвание: <b>{title}</b>\nСтатус: {status}"
VIBES_STATUS_ACTIVE = "✅ активен"
VIBES_STATUS_INACTIVE = "❌ выключен"
VIBES_BTN_RENAME = "✏️ Переименовать"
VIBES_BTN_DISABLE = "🚫 Выключить"
VIBES_BTN_ENABLE = "✅ Включить"
VIBES_BTN_BACK_TO_PAGE = "⬅️ К странице"
VIBES_ASK_TITLE = "Пришлите новое название для вайба №{number} (сейчас: «{title}»)."
VIBES_TITLE_EMPTY = "Название не может быть пустым. Пришлите текст."
VIBES_TITLE_UPDATED = "✅ Вайб №{number} переименован: «{title}»."
VIBES_ASK_IMAGE = (
    "Пришлите новую картинку-коллаж для страницы {page}/{total} (вайбы {first}–{last})."
)
VIBES_IMAGE_NOT_PHOTO = "Нужно фото. Пришлите картинку-коллаж страницы."
VIBES_IMAGE_UPDATED = "✅ Картинка страницы {page}/{total} обновлена."
VIBES_NOT_FOUND = "Вайб №{number} не найден в справочнике."
DICTS_ASK_NUMBER_INVALID = "Введите число."
DICTS_ERROR_NO_SESSION = "Ошибка: нет db_session."
DICTS_MENU = "Справочники"
DICTS_BTN_FANDOMS = "Фандомы"
DICTS_BTN_INTERESTS = "Интересы"
DICTS_BTN_VIBES = "Вайбы"
DICTS_BTN_CREATOR_CATS = "Категории Аллеи"
DICTS_BTN_COMPLAINT_REASONS = "Причины жалоб"
DICTS_LIST_HEADER = "<b>{name}</b> (всего: {total})"
DICTS_ITEM = "#{id} [{code}] {title} — {'✅' if active else '❌'}"
DICTS_EMPTY = "Список пуст."
DICTS_BTN_ADD = "Добавить"
DICTS_BTN_EDIT = "Редактировать"
DICTS_BTN_DEACTIVATE = "Деактивировать"
DICTS_BTN_ACTIVATE = "Активировать"
DICTS_ADD_ASK_CODE = "Введите код (уникальный, латиница/цифры):"
DICTS_ADD_ASK_TITLE = "Введите название:"
DICTS_ADD_ASK_NUMBER = "Введите номер вайба (число):"
DICTS_ADD_ASK_IMAGE = "Отправьте изображение для вайба:"
DICTS_ADDED = "Запись добавлена."
DICTS_UPDATED = "Запись обновлена."
DICTS_DEACTIVATED = "Запись деактивирована."
DICTS_ACTIVATED = "Запись активирована."
DICTS_NOT_FOUND = "Запись не найдена."
DICTS_EDIT_ASK_TITLE = "Введите новое название (или /skip):"
DICTS_EDIT_ASK_IMAGE = "Отправьте новое изображение для вайба (или /skip):"

# --- На проверке ---
REVIEW_AUTHOR_BANNED_POST_DELETED = "Автор забанен, пост удалён."
REVIEW_ERROR_NO_ITEM_ID = "Ошибка: нет item_id."
REVIEW_MENU = "На проверке"
REVIEW_PROFILES_BTN = "Анкеты"
REVIEW_POSTS_BTN = "Посты Аллеи"
REVIEW_PROFILE_CARD = (
    "<b>Анкета на проверке</b>\n"
    "ID анкеты: #{profile_id}\n"
    "Пользователь: #{user_id}\n"
    "Никнейм: {nickname}"
)
REVIEW_POST_CARD = (
    "<b>Пост Аллеи на проверке</b>\nID поста: #{post_id}\nАвтор: {author}\nОписание: {description}"
)
REVIEW_BTN_APPROVE = "Одобрить"
REVIEW_BTN_REJECT = "Отклонить"
REVIEW_BTN_BAN_USER = "Забанить пользователя"
REVIEW_BTN_DELETE_POST = "Удалить пост"
REVIEW_ASK_REASON = "Введите причину отклонения/бана:"
REVIEW_APPROVED = "Одобрено."
REVIEW_REJECTED = "Отклонено."
REVIEW_EMPTY = "Нет элементов на проверке."

# Кнопки карточки анкеты на ручной проверке (новый edit-based флоу).
REVIEW_BTN_APPROVE_NEW = "✅ Одобрить"
REVIEW_BTN_REJECT_NEW = "❌ Отклонить"
REVIEW_BTN_SKIP = "⏭ Пропустить"

# Caption медиа-карточки анкеты на проверке.
# {page}          — номер карточки (1-based)
# {total}         — общее количество анкет в очереди
# {user_id}       — внутренний User.id
# {username_part} — " (@username)" или пустая строка
# {tg_id}         — telegram_id пользователя
# {profile_text}  — текст из build_rendered_profile
REVIEW_PROFILE_CARD_CAPTION = (
    "📋 Анкета на проверке {page}/{total}\n"
    "\n"
    "Пользователь: <code>id={user_id}</code> / tg:<code>{tg_id}</code>{username_part}\n"
    "─────────────────\n"
    "{profile_text}"
)

# Fallback-caption когда build_rendered_profile вернул None.
REVIEW_PROFILE_CARD_NO_RENDER = (
    "📋 Анкета на проверке {page}/{total}\n"
    "\n"
    "Пользователь: <code>id={user_id}</code> / tg:<code>{tg_id}</code>{username_part}\n"
    "Анкета не может быть отрендерена (отсутствует справочник)."
)

# --- Стоп-слова ---
STOPWORDS_EDIT_ASK_PATTERN = "Введите новый паттерн (или /skip для отмены):"
STOPWORDS_CANCELLED = "Отменено."
STOPWORDS_MENU = "Стоп-листы"
STOPWORDS_LIST_HEADER = "Стоп-слова (категория: {category}, всего: {total})"
STOPWORDS_ITEM = "#{id} [{kind}] [{category}] {pattern} {state}"
STOPWORD_STATE_ON = "активно"
STOPWORD_STATE_OFF = "неактивно"
STOPWORD_TOGGLED = "Стоп-слово #{id}: {state}."
STOPWORDS_EMPTY = "Стоп-слов нет."
STOPWORDS_BTN_ADD = "Добавить"
STOPWORDS_BTN_TOGGLE = "Вкл/Выкл"
STOPWORDS_BTN_EDIT = "Редактировать"
STOPWORDS_BTN_FILTER_CATEGORY = "Фильтр по категории"
STOPWORDS_BTN_SEARCH = "Поиск"
STOPWORDS_ADD_ASK_PATTERN = "Введите паттерн (слово или регулярное выражение):"
STOPWORDS_ADD_ASK_KIND = "Тип паттерна:"
STOPWORDS_BTN_KIND_WORD = "Слово"
STOPWORDS_BTN_KIND_REGEX = "Regex"
STOPWORDS_ADD_ASK_CATEGORY = "Категория:"
STOPWORDS_ADDED = "Стоп-слово добавлено (ID: #{id})."
STOPWORDS_TOGGLED = "Стоп-слово #{id}: {'активно' if active else 'неактивно'}."
STOPWORDS_UPDATED = "Стоп-слово обновлено."
STOPWORDS_REGEX_ERROR = "Ошибка в регулярном выражении: {error}. Исправьте паттерн."
STOPWORDS_SEARCH_PROMPT = "Введите подстроку для поиска:"
STOPWORDS_NOT_FOUND = "Ничего не найдено."

# --- Настройки ---
SETTINGS_MENU = "Настройки приложения"
SETTINGS_LIST_HEADER = "Список настроек:"
SETTINGS_ITEM = "<code>{key}</code> = <code>{value}</code>"
SETTINGS_EDIT_ASK_VALUE = (
    "Введите новое значение для <code>{key}</code> (текущее: <code>{current}</code>):"
)
SETTINGS_UPDATED = "Настройка <code>{key}</code> обновлена."
SETTINGS_NOT_FOUND = "Настройка не найдена."
SETTINGS_EMPTY = "Нет настроек."
SETTINGS_BTN_EDIT = "Редактировать"
SETTINGS_KEY_NOT_FOUND = "Ошибка: ключ не найден."

# --- Лента (Feed) — раздел админки (Волна 2B) ---
FEED_ADMIN_MENU = "Управление Лентой"
ADMIN_MENU_BTN_FEED = "Лента"
FEED_ADMIN_BTN_ACTIVE = "Активные посты"
FEED_ADMIN_BTN_HIDDEN = "Скрытые посты"
FEED_ADMIN_BTN_PENDING = "На проверке"
FEED_ADMIN_BTN_BACK = "Назад"
FEED_ADMIN_LIST_EMPTY = "Постов нет."
FEED_ADMIN_POST_CARD = (
    "<b>Пост #{id}</b>\n"
    "Автор: {author_name} (user_id={author_user_id})\n"
    "Статус: {status}\n"
    "На проверке: {pending}\n"
    "Текст: {text}\n"
    "Создан: {created_at}\n"
    "Истекает: {expires_at}"
)
FEED_ADMIN_BTN_HIDE = "Скрыть пост"
FEED_ADMIN_BTN_DELETE = "Удалить пост (block)"
FEED_ADMIN_BTN_APPROVE = "Одобрить (снять флаг проверки)"
FEED_ADMIN_BTN_DELETE_COMMENT = "Удалить комментарий"
FEED_ADMIN_BTN_RESTRICT = "Ограничить в комментариях"
FEED_ADMIN_BTN_UNRESTRICT = "Снять ограничение"
FEED_ADMIN_POST_HIDDEN = "Пост #{id} скрыт."
FEED_ADMIN_POST_DELETED = "Пост #{id} заблокирован."
FEED_ADMIN_POST_APPROVED = "Пост #{id} одобрен."
FEED_ADMIN_COMMENT_DELETED = "Комментарий #{id} удалён."
FEED_ADMIN_COMMENT_NOT_FOUND = "Комментарий не найден."
FEED_ADMIN_POST_NOT_FOUND = "Пост не найден."
FEED_ADMIN_RESTRICT_ASK_HOURS = (
    "Введите количество часов ограничения в комментариях для пользователя #{user_id}:"
)
FEED_ADMIN_RESTRICT_INVALID_HOURS = "Введите целое число больше 0."
FEED_ADMIN_RESTRICTED = "Пользователь #{user_id} ограничен в комментариях до {until}."
FEED_ADMIN_UNRESTRICTED = "Ограничение с пользователя #{user_id} снято."
FEED_ADMIN_ASK_COMMENT_ID = "Введите ID комментария для удаления:"
FEED_ADMIN_INVALID_ID = "Введите корректный числовой ID."

# Кнопки карточки поста в ленте (edit-based одиночная карточка с пагинацией).
FEED_BTN_APPROVE = "✅ Одобрить"
FEED_BTN_HIDE = "🙈 Скрыть пост"
FEED_BTN_DELETE_BLOCK = "🗑 Удалить (block)"
FEED_BTN_DEL_COMMENTS = "🧹 Удалить комментарии"
FEED_BTN_RESTRICT = "🔇 Ограничить в комментариях"
FEED_BTN_UNRESTRICT = "🔊 Снять ограничение"
FEED_BTN_SKIP = "⏭ Пропустить"

# Caption одиночной карточки поста ленты (admin feed review).
# {page}          — номер карточки (1-based)
# {total}         — общее количество постов в выборке
# {user_id}       — author_user_id (может быть пустым)
# {username_part} — " | author_name" или пустая строка
# {status_label}  — локализованный статус
# {photo_counter} — "📸 фото 1 из N\n" если несколько медиа, иначе пустая строка
# {body}          — текст поста (обрезается truncate_caption)
FEED_REVIEW_POST_CARD_CAPTION = (
    "📋 Пост Ленты {page}/{total}\n"
    "\n"
    "Автор: <code>id={user_id}</code>{username_part}\n"
    "Статус: {status_label}\n"
    "{photo_counter}"
    "─────────────────\n"
    "{body}"
)

# --- Аналитика ---
ANALYTICS_SELECT_PERIOD = "Выберите период:"
ANALYTICS_HEADER = "Аналитика за {period}"
ANALYTICS_EVENT_ROW = "{event_type}: {count}"
ANALYTICS_TOP_VIOLATORS = "<b>Топ нарушителей:</b>"
ANALYTICS_VIOLATOR_ROW = '<a href="tg://user?id={telegram_id}">{telegram_id}</a>: {count} жалоб'
ANALYTICS_CONVERSION = "Конверсия в Premium: {rate:.1%}"
ANALYTICS_NO_DATA = "Нет данных за период."
ANALYTICS_BTN_DAY = "День"
ANALYTICS_BTN_WEEK = "Неделя"
ANALYTICS_BTN_MONTH = "Месяц"
