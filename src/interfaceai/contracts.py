"""The base model every persisted contract in this project derives from.

Lifted out of `screenshot2controls` so the domain layer (vocabulary,
capabilities) does not have to import the perception layer to get a base class.
The settings are the ones that make an artifact safe to write to disk and read
back byte-identically: `extra="forbid"` so an unknown key is a load error
rather than a silently ignored field, and base64 for bytes so a template PNG
survives a JSON round trip.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )
