"""Stable application errors and MCP response envelopes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, NoReturn

from mcp.types import CallToolResult, TextContent

SOURCE = "https://api.chess.com/pub"


@dataclass(slots=True)
class AppError(Exception):
    """An expected error safe to expose to an MCP caller."""

    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def fail(code: str, message: str) -> NoReturn:
    raise AppError(code, message)


def success_envelope(data: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "source": SOURCE,
        "untrusted_external_data": True,
        "data": data,
    }


def error_envelope(error: AppError) -> dict[str, Any]:
    return {"ok": False, "error": {"code": error.code, "message": error.message}}


def tool_result(payload: dict[str, Any], *, is_error: bool = False) -> CallToolResult:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=payload,
        is_error=is_error,
    )
