"""The planning context handed to every stage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class PlanningContext:
    """Immutable run parameters. Every stage receives one; no stage reads global state.

    Business meaning: ``as_of`` is the cycle date the run plans for. Everything downstream
    derives its window from it, so no step ever hard-codes a date range.
    """

    as_of: date
    lead_time_months: int = 4
    review_period_months: int = 1
    plant: str = "W1B4"
    currency: str = "LKR"
    config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.lead_time_months < 0:
            raise ValueError(f"lead_time_months must be >= 0, got {self.lead_time_months}")
        if self.review_period_months < 1:
            raise ValueError(f"review_period_months must be >= 1, got {self.review_period_months}")
        if not self.plant:
            raise ValueError("plant must be a non-empty plant code")
        object.__setattr__(self, "config", MappingProxyType(dict(self.config)))

    @property
    def protection_interval_months(self) -> int:
        """P = L + R. The window safety stock must cover."""
        return self.lead_time_months + self.review_period_months

    def option(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def summary(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "lead_time_months": self.lead_time_months,
            "review_period_months": self.review_period_months,
            "protection_interval_months": self.protection_interval_months,
            "plant": self.plant,
            "currency": self.currency,
            "config": dict(self.config),
        }
