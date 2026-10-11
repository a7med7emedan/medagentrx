# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
"""Model metadata (``model.yaml``) describing one candidate version."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from medagentrx.errors import InputError
from medagentrx.io.paths import resolve_input
from medagentrx.io.text import read_text_limited
from medagentrx.plan.models import Identifier, Sha256
from medagentrx.safe_yaml import parse_yaml

DEFAULT_MAX_METADATA_BYTES = 100_000

Version = Annotated[str, Field(min_length=1, max_length=64)]


class ModelMeta(BaseModel):
    """Metadata of a candidate model version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Version = Field(description="Version of the candidate model.")
    previous_version: Version = Field(description="Version the candidate replaces.")
    modification_id: Identifier = Field(description="Plan modification this update applies.")
    architecture_sha256: Sha256 = Field(description="SHA-256 of the architecture definition.")
    intended_use_sha256: Sha256 = Field(description="SHA-256 of the intended-use statement.")
    trained_at: dt.datetime | dt.date = Field(description="When training finished, ISO 8601.")
    training_manifest_sha256: Sha256 = Field(description="SHA-256 of the training manifest.")


def load_model_meta(
    path: str | Path,
    *,
    max_bytes: int = DEFAULT_MAX_METADATA_BYTES,
    base: Path | None = None,
) -> ModelMeta:
    """Load and validate ``model.yaml``.

    Raises:
        InputError: If the file is unsafe, unreadable or not valid.
    """
    source = str(path)
    real = resolve_input(path, base=base)
    data = parse_yaml(read_text_limited(real, max_bytes=max_bytes), source=source, error=InputError)
    if not isinstance(data, dict):
        raise InputError(f"{source}: model metadata must be a mapping")
    try:
        return ModelMeta.model_validate(data)
    except ValidationError as exc:
        details = [
            f"{'.'.join(map(str, e['loc'])) or '<root>'}: {e['msg']}"
            for e in exc.errors(include_url=False)
        ]
        raise InputError(f"{source}: model metadata is not valid", details) from None
