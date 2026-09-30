"""PlanningContext: frozen, validated, and the source of the protection interval."""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest
from src.core.context import PlanningContext


def test_defaults_match_the_locked_scope() -> None:
    ctx = PlanningContext(as_of=date(2025, 12, 1))

    assert ctx.lead_time_months == 4
    assert ctx.review_period_months == 1
    assert ctx.plant == "W1B4"
    assert ctx.currency == "LKR"


def test_protection_interval_is_lead_plus_review() -> None:
    assert PlanningContext(as_of=date(2025, 12, 1)).protection_interval_months == 5
    assert (
        PlanningContext(as_of=date(2025, 12, 1), lead_time_months=2).protection_interval_months == 3
    )


def test_context_is_frozen() -> None:
    ctx = PlanningContext(as_of=date(2025, 12, 1))

    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.plant = "W124"  # type: ignore[misc]


def test_config_cannot_be_mutated_through_the_context() -> None:
    """No stage mutates anything it did not create."""
    supplied = {"on_order_interpretation": "arrival"}
    ctx = PlanningContext(as_of=date(2025, 12, 1), config=supplied)

    with pytest.raises(TypeError):
        ctx.config["on_order_interpretation"] = "raised"  # type: ignore[index]

    supplied["on_order_interpretation"] = "raised"
    assert ctx.option("on_order_interpretation") == "arrival", "context copied the mapping"


def test_option_falls_back_to_default() -> None:
    ctx = PlanningContext(as_of=date(2025, 12, 1))
    assert ctx.option("missing", "fallback") == "fallback"


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"lead_time_months": -1}, "lead_time_months"),
        ({"review_period_months": 0}, "review_period_months"),
        ({"plant": ""}, "plant"),
    ],
)
def test_invalid_parameters_raise(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        PlanningContext(as_of=date(2025, 12, 1), **kwargs)  # type: ignore[arg-type]


def test_summary_carries_what_the_run_report_prints() -> None:
    summary = PlanningContext(as_of=date(2025, 12, 1)).summary()

    assert summary["as_of"] == "2025-12-01"
    assert summary["protection_interval_months"] == 5
    assert summary["plant"] == "W1B4"
