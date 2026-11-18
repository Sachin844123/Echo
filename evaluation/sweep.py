"""Explicit finite weight settings for tuning-only sweeps; no automatic selection."""

from pathlib import Path

from pydantic import Field, ValidationError, model_validator

from app.core.config import RerankWeights
from evaluation.dataset import EvaluationError, Identifier, StrictModel, read_json


class WeightSetting(StrictModel):
    id: Identifier
    weights: RerankWeights

    @model_validator(mode="after")
    def explicit_weights(self):
        if self.weights.model_fields_set != set(RerankWeights.model_fields):
            raise ValueError("sweep settings must explicitly name every weight")
        return self


class WeightSweep(StrictModel):
    settings: list[WeightSetting] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_settings(self):
        ids, weights = set(), set()
        for setting in self.settings:
            values = tuple(setting.weights.model_dump().values())
            if setting.id.casefold() in ids or values in weights:
                raise ValueError("duplicate sweep setting")
            ids.add(setting.id.casefold())
            weights.add(values)
        return self


def load_sweep(path: Path | None) -> WeightSweep | None:
    if path is None:
        return None
    try:
        return WeightSweep.model_validate(read_json(path, 128 * 1024))
    except ValidationError:
        raise EvaluationError("invalid_weight_sweep") from None
