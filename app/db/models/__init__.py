"""Регистрация моделей в Base.metadata. Импортировать здесь все модули моделей."""

from app.db.models.admin import Admin
from app.db.models.ads_rotation import AdRotationPost
from app.db.models.analytics import AnalyticsEvent
from app.db.models.creators import CreatorPost, CreatorPostPhoto, CreatorSubmission
from app.db.models.dictionaries import (
    ComplaintReason,
    CreatorCategory,
    Fandom,
    Gender,
    Interest,
    Vibe,
)
from app.db.models.feed import FeedPost, FeedPostMedia
from app.db.models.matching import (
    Block,
    Dislike,
    Like,
    Match,
    ViewedProfile,
)
from app.db.models.moderation import Complaint, ContentModerationLog, StopWord
from app.db.models.premium import Payment, PremiumSubscription
from app.db.models.profile import (
    Profile,
    ProfileDesiredFandom,
    ProfileFandom,
    ProfileInterest,
    ProfileLookingForGender,
)
from app.db.models.promo import PromoPost, PromoPostRecipient
from app.db.models.settings import AppSetting
from app.db.models.user import User
from app.db.models.vibe_by_photo import VibeByPhotoRequest

__all__ = [
    "AdRotationPost",
    "Admin",
    "AnalyticsEvent",
    "AppSetting",
    "Block",
    "Complaint",
    "ComplaintReason",
    "ContentModerationLog",
    "CreatorCategory",
    "CreatorPost",
    "CreatorPostPhoto",
    "CreatorSubmission",
    "Dislike",
    "Fandom",
    "FeedPost",
    "FeedPostMedia",
    "Gender",
    "Interest",
    "Like",
    "Match",
    "Payment",
    "PremiumSubscription",
    "Profile",
    "ProfileDesiredFandom",
    "ProfileFandom",
    "ProfileInterest",
    "ProfileLookingForGender",
    "PromoPost",
    "PromoPostRecipient",
    "StopWord",
    "User",
    "Vibe",
    "VibeByPhotoRequest",
    "ViewedProfile",
]
