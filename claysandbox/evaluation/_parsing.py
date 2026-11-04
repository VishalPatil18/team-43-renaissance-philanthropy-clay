"""JSON output parsing shared by workflow, output and process evaluators."""

import json
import re
from typing import Any

_FENCE = re.compile(r"^\s*```[A-Za-z0-9_-]*\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


class ParseError(ValueError):
    """An evaluator cannot parse the supplied output."""


def load_json_value(raw: Any) -> Any:
    """A dict/list as is; a string is JSON-decoded after stripping a markdown code fence."""
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    m = _FENCE.match(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ParseError(f"final output is not valid JSON: {e}") from e
