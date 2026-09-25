"""Azure/OpenAI strict mode rejects what Pydantic emits by default.

Approach lifted from nobsmed-v2 libs/llm_service/.../llm.py.
"""

from interfaceai.screenshot2controls import ScreenOutput
from interfaceai.vision_llm import enforce_strict_schema


def schema() -> dict:
    return enforce_strict_schema(ScreenOutput.model_json_schema())


def test_fields_with_defaults_become_required() -> None:
    """Without this, Azure 400s on any field Pydantic gave a default."""
    s = schema()
    assert set(s["required"]) == set(s["properties"])


def test_every_object_forbids_extra_properties() -> None:
    s = schema()
    objects = [s, *(d for d in s.get("$defs", {}).values() if "properties" in d)]
    assert all(o["additionalProperties"] is False for o in objects)


def test_ref_nodes_carry_no_siblings() -> None:
    """Azure rejects {"$ref": ..., "description": ...} -- $ref must stand alone."""

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                assert set(node) == {"$ref"}, f"$ref with siblings: {sorted(node)}"
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema())
