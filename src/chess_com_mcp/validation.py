"""Pure validation and normalization helpers."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from .errors import fail

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,50}$", re.ASCII)
_CLUB_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$", re.ASCII)
_TITLES = frozenset({"GM", "WGM", "IM", "WIM", "FM", "WFM", "NM", "WNM", "CM", "WCM"})
_CATEGORIES = frozenset({"weekly", "monthly", "all_time"})


def _validate_string(value: Any, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str or not pattern.fullmatch(value):
        fail("invalid_input", f"{label} has an invalid format.")
    return value


def username(value: Any) -> str:
    return _validate_string(value, _USERNAME_RE, "Username")


def club_url_id(value: Any) -> str:
    return _validate_string(value, _CLUB_RE, "Club ID")


def title(value: Any) -> str:
    if type(value) is not str:
        fail("invalid_input", "Title has an invalid format.")
    normalized = value.upper()
    if normalized not in _TITLES:
        fail("invalid_input", "Title is not supported.")
    return normalized


def category(value: Any) -> str:
    if type(value) is not str or value not in _CATEGORIES:
        fail("invalid_input", "Club member category is not supported.")
    return value


def integer(value: Any, label: str, minimum: int, maximum: int | None = None) -> int:
    if type(value) is not int:
        fail("invalid_input", f"{label} must be an integer.")
    if value < minimum or (maximum is not None and value > maximum):
        upper = f" and at most {maximum}" if maximum is not None else ""
        fail("invalid_input", f"{label} must be at least {minimum}{upper}.")
    return value


def year(value: Any, *, current_year: int | None = None) -> int:
    current = current_year if current_year is not None else datetime.now(UTC).year
    return integer(value, "Year", 1990, current)


def month(value: Any) -> int:
    return integer(value, "Month", 1, 12)


def offset(value: Any) -> int:
    return integer(value, "Offset", 0)


def limit(value: Any, *, maximum: int) -> int:
    return integer(value, "Limit", 1, maximum)


def pgn_max_chars(value: Any) -> int:
    return integer(value, "Maximum characters", 1000, 100000)
