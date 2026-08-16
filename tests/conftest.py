from __future__ import annotations

import base64

import pytest


@pytest.fixture
def token() -> str:
    return base64.urlsafe_b64encode(b"a" * 32).decode().rstrip("=")
