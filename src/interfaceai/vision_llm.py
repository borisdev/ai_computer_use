"""The model client: named endpoint profiles + strict-schema structured output.

This is the injected `VisionCall` dependency that screenshot2controls expects.
It knows how to reach a model and get a validated Pydantic object back; it knows
nothing about controls, grids or screenshots.

Dispatch is litellm, and the profile table and strict-schema pass are lifted from
nobsmed-v2 `libs/llm_service/src/nobs/llm_service/llm.py`. Because litellm treats
the provider as a config string, swapping Azure OpenAI for Anthropic is a profile
change, not a code change.

Measured note on model choice: for GROUNDING a click coordinate, model tier did
not help -- gpt-4o, gpt-4.1 and gpt-5.2-chat all missed 15-22px controls by
45-80px. That is why screenshot2controls asks the model to pick a numbered dot
rather than estimate a coordinate. See its module docstring.
"""

from __future__ import annotations

import base64
from typing import Any

import litellm
from pydantic import BaseModel

from interfaceai.settings import get_settings

PROFILES: dict[str, dict[str, str]] = {
    "gpt-4.1": {
        "model": "azure/gpt-4.1",
        "api_base": "https://openai-rg-nobsmed.openai.azure.com/",
        "api_version": "2025-01-01-preview",
        "key_field": "vision_api_key",
    },
    "gpt-4o": {
        "model": "azure/gpt-4o",
        "api_base": "https://openai-rg-nobsmed.openai.azure.com/",
        "api_version": "2023-03-15-preview",
        "key_field": "vision_api_key",
        # This deployment rejects max_tokens > 4096 with a 400.
        "max_tokens": 4096,
    },
    "gpt-5.2-chat": {
        "model": "azure/gpt-5.2-chat",
        "api_base": "https://boris-m3ndov9n-eastus2.cognitiveservices.azure.com/",
        "api_version": "2025-04-01-preview",
        "key_field": "vision_api_key_eastus2",
    },
    "claude-opus": {
        "model": "anthropic/claude-opus-4-6",
        "key_field": "anthropic_api_key_for_vision",
    },
}


def _clamp_temperature(model: str, temperature: float) -> float:
    """GPT-5 and o-series accept only temperature=1.

    litellm raises UnsupportedParamsError client-side for the o-series; the
    GPT-5 family 500s server-side with an unhelpful body. Copied from
    nobsmed-v2, which found both the hard way.
    """
    if any(tag in model for tag in ("gpt-5", "o3-", "o4-")):
        return 1.0
    return temperature


def enforce_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively enforce Azure/OpenAI strict JSON schema requirements.

    Strict mode requires every object to have:
      1. additionalProperties: false
      2. required: [all property keys] -- even ones with defaults
      3. $ref nodes carrying no sibling keywords

    Pydantic satisfies none of these on its own. Without (2), Azure rejects the
    schema outright because `label`, `enabled`, `identifying_text` and
    `controls` all have defaults and so are omitted from `required`. Without
    (3), it rejects `{"$ref": ..., "description": ...}`.

    Taken from nobsmed-v2 libs/llm_service/.../llm.py, which learned it the
    hard way.
    """
    if "$ref" in schema:
        ref = schema["$ref"]
        schema.clear()
        schema["$ref"] = ref
        return schema

    if schema.get("type") == "object" or "properties" in schema:
        schema["additionalProperties"] = False
        if "properties" in schema:
            schema["required"] = list(schema["properties"].keys())

    for key in ("$defs", "definitions"):
        for defn in schema.get(key, {}).values():
            enforce_strict_schema(defn)
    if isinstance(schema.get("items"), dict):
        enforce_strict_schema(schema["items"])
    for prop in schema.get("properties", {}).values():
        if isinstance(prop, dict):
            enforce_strict_schema(prop)
    for combo in ("anyOf", "oneOf"):
        for variant in schema.get(combo, []):
            if isinstance(variant, dict):
                enforce_strict_schema(variant)
    return schema


def response_format(model: type[BaseModel]) -> dict[str, Any]:
    """Build a litellm response_format from a Pydantic model."""
    schema = enforce_strict_schema(model.model_json_schema())
    return {
        "type": "json_schema",
        "json_schema": {"name": model.__name__, "schema": schema, "strict": True},
    }


async def call_vision_llm[T: BaseModel](
    *,
    prompt: str,
    image_png: bytes,
    response_model: type[T],
    profile: str | None = None,
) -> T:
    """Send one image + prompt, return a validated instance of `response_model`.

    Conforms to the VisionCall protocol in screenshot2controls.
    """
    settings = get_settings()
    name = profile or settings.vision_profile
    if name not in PROFILES:
        raise RuntimeError(f"Unknown vision profile {name!r}. Have: {sorted(PROFILES)}")
    cfg = PROFILES[name]

    key = settings.key_named(cfg["key_field"])
    if not key:
        raise RuntimeError(
            f"Profile {name!r} needs {cfg['key_field'].upper()} in .secret -- see .secret.example."
        )

    data_url = f"data:image/png;base64,{base64.standard_b64encode(image_png).decode('ascii')}"
    response = await litellm.acompletion(
        model=cfg["model"],
        api_base=cfg.get("api_base"),
        api_key=key,
        api_version=cfg.get("api_version"),
        max_tokens=int(cfg.get("max_tokens", 8000)),
        temperature=_clamp_temperature(cfg["model"], 0),
        response_format=response_format(response_model),
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError(
            f"Empty response (finish_reason={response.choices[0].finish_reason!r}). "
            "If it is 'length' the reply was truncated -- raise max_tokens."
        )
    return response_model.model_validate_json(content)
