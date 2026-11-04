"""ToolResult keeps status, error_kind and is_error consistent (DD-045)."""

from __future__ import annotations

import pytest

from claysandbox.contracts.tools import ToolResult


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, ("ok", None, False)),
        ({"text": "x"}, ("ok", None, False)),
        ({"is_error": True}, ("error", "tool_error", True)),  # the pre-DD-045 form
        ({"status": "timeout"}, ("timeout", "tool_timeout", True)),
        ({"status": "error"}, ("error", "tool_error", True)),
        ({"error_kind": "server_unavailable"}, ("error", "server_unavailable", True)),
        ({"error_kind": "tool_timeout"}, ("timeout", "tool_timeout", True)),
        ({"is_error": False, "error_kind": None}, ("ok", None, False)),
    ],
)
def test_fields_are_consistent(kwargs: dict, expected: tuple) -> None:
    r = ToolResult(**kwargs)
    assert (r.status, r.error_kind, r.is_error) == expected


def test_round_trips_through_json() -> None:
    r = ToolResult(text="t", error_kind="server_unavailable")
    assert ToolResult.model_validate_json(r.model_dump_json()) == r
