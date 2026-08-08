import json
import re
from typing import Any

from sqlalchemy import JSON, Column

_POSTGRES_JSON_CAST = re.compile(r"::(?:pg_catalog\.)?jsonb?\s*$", re.IGNORECASE)


def _without_balanced_outer_parentheses(expression: str) -> str:
    value = expression.strip()
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        encloses_entire_expression = True
        for index, character in enumerate(value):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0 and index != len(value) - 1:
                    encloses_entire_expression = False
                    break
        if not encloses_entire_expression or depth != 0:
            break
        value = value[1:-1].strip()
    return value


def _canonical_json_default(expression: str | None) -> str | None:
    if expression is None:
        return None
    value = _without_balanced_outer_parentheses(expression)
    value = _POSTGRES_JSON_CAST.sub("", value).strip()
    value = _without_balanced_outer_parentheses(value)
    if value.startswith("E'") and value.endswith("'"):
        value = value[2:-1]
    elif value.startswith("'") and value.endswith("'"):
        value = value[1:-1]
    value = value.replace("''", "'")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return "".join(value.split())
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compare_server_default(
    context: object,
    inspected_column: Column[Any],
    metadata_column: Column[Any],
    inspected_default: str | None,
    metadata_default: object,
    rendered_metadata_default: str | None,
) -> bool | None:
    del context, metadata_default
    if not isinstance(inspected_column.type, JSON) and not isinstance(
        metadata_column.type,
        JSON,
    ):
        return None
    return _canonical_json_default(inspected_default) != _canonical_json_default(
        rendered_metadata_default
    )
