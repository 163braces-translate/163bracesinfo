"""Weekday labels shared by the performance table and the stats charts."""

from django.utils.translation import get_language

# Monday first, matching datetime.date.weekday() and the ORM's iso_week_day.
WEEKDAY_LABELS = {
    "zh-hant": ["一", "二", "三", "四", "五", "六", "日"],
    "en": ["Mon.", "Tue.", "Wed.", "Thu.", "Fri.", "Sat.", "Sun."],
}


def weekday_labels(language=None):
    """
    Return the seven weekday labels for `language`, Monday first.

    Falls back to Chinese for anything that is not English, so an
    unexpected locale still renders the site's primary language.
    """
    language = language or get_language() or ""
    key = "en" if language.lower().startswith("en") else "zh-hant"
    return WEEKDAY_LABELS[key]


def weekday_label(date, language=None):
    """Return the weekday label for a single date, or "" when it is None."""
    if not date:
        return ""
    return weekday_labels(language)[date.weekday()]
