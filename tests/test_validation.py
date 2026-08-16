from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chess_com_mcp import validation
from chess_com_mcp.errors import AppError


@pytest.mark.parametrize("value", ["a", "A_1-b", "x" * 50])
def test_username_accepts_safe_ascii(value: str) -> None:
    assert validation.username(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "x" * 51, "ümlaut", "has/slash", "has.dot", "white space", "percent%20", "query?", "fragment#"],
)
def test_username_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(AppError, match="invalid format") as caught:
        validation.username(value)
    assert caught.value.code == "invalid_input"


def test_club_id_boundaries() -> None:
    assert validation.club_url_id("x") == "x"
    assert validation.club_url_id("x" * 80) == "x" * 80
    with pytest.raises(AppError):
        validation.club_url_id("x" * 81)


@pytest.mark.parametrize("value", ["GM", "wgm", "im", "WIM", "FM", "WFM", "NM", "WNM", "CM", "WCM"])
def test_title_normalizes_allowlist(value: str) -> None:
    assert validation.title(value) == value.upper()


@pytest.mark.parametrize("value", ["", "XX", "GM ", 1])
def test_title_rejects_unknown_values(value: object) -> None:
    with pytest.raises(AppError):
        validation.title(value)


@pytest.mark.parametrize("value", ["weekly", "monthly", "all_time"])
def test_categories(value: str) -> None:
    assert validation.category(value) == value


def test_date_and_integer_boundaries() -> None:
    current = datetime.now(UTC).year
    assert validation.year(1990, current_year=current) == 1990
    assert validation.year(current, current_year=current) == current
    assert validation.month(1) == 1
    assert validation.month(12) == 12
    assert validation.offset(0) == 0
    assert validation.limit(500, maximum=500) == 500
    assert validation.pgn_max_chars(1000) == 1000
    assert validation.pgn_max_chars(100000) == 100000


@pytest.mark.parametrize(
    ("call", "value"),
    [
        (lambda value: validation.year(value, current_year=2026), 1989),
        (lambda value: validation.year(value, current_year=2026), 2027),
        (validation.month, 0),
        (validation.month, 13),
        (validation.offset, -1),
        (lambda value: validation.limit(value, maximum=100), 0),
        (lambda value: validation.limit(value, maximum=100), 101),
        (validation.pgn_max_chars, 999),
        (validation.pgn_max_chars, 100001),
        (validation.offset, True),
    ],
)
def test_numeric_validation_rejects_invalid_values(call: object, value: object) -> None:
    with pytest.raises(AppError):
        call(value)  # type: ignore[operator]
