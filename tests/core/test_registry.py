"""The DAG: order, fail-closed behaviour, and an end-to-end two-stage run."""

from __future__ import annotations

import json
from datetime import date

import pytest
from src.core.context import PlanningContext
from src.core.errors import CycleError, RegistryError
from src.core.registry import Registry, Stage
from src.core.result import StageResult, StageStatus


@pytest.fixture
def ctx() -> PlanningContext:
    return PlanningContext(as_of=date(2025, 12, 1))


def _stage(name: str, *, deps: tuple[str, ...] = (), rows: int = 10) -> Stage:
    def run(_: PlanningContext) -> StageResult:
        return StageResult(stage=name, rows_in=rows, rows_out=rows)

    return Stage(name=name, fn=run, depends_on=deps)


def test_two_stage_stub_runs_end_to_end(ctx: PlanningContext, tmp_path) -> None:
    """Step 00's definition of done: the DAG executes end to end on a two-stage stub."""
    registry = Registry()
    seen: list[str] = []

    @registry.register("00_extract", description="stub extract")
    def extract(_: PlanningContext) -> StageResult:
        seen.append("00_extract")
        return StageResult(stage="", rows_in=100, rows_out=90)

    @registry.register("01_transform", depends_on=["00_extract"], description="stub transform")
    def transform(_: PlanningContext) -> StageResult:
        seen.append("01_transform")
        result = StageResult(stage="", rows_in=90, rows_out=85)
        result.reject("no part master match", 5)
        result.warn("lead time fell back to the planning assumption")
        return result

    report_path = tmp_path / "run.json"
    report = registry.run(
        ctx, settings_summary={"on_order_interpretation": "arrival"}, report_path=report_path
    )

    assert seen == ["00_extract", "01_transform"], "ran in dependency order"
    assert report.ok
    assert report.counts() == {"ok": 2, "failed": 0, "skipped": 0}

    transform_result = report.stages[1]
    assert transform_result.stage == "01_transform", "runner stamps the stage name"
    assert transform_result.rejected == 5
    assert transform_result.reject_reasons == {"no part master match": 5}

    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert written["ok"] is True
    assert written["settings"]["on_order_interpretation"] == "arrival"
    assert written["context"]["as_of"] == "2025-12-01"
    assert [s["stage"] for s in written["stages"]] == ["00_extract", "01_transform"]


def test_downstream_is_skipped_when_upstream_fails(ctx: PlanningContext) -> None:
    registry = Registry()

    @registry.register("00_extract")
    def extract(_: PlanningContext) -> StageResult:
        raise ValueError("source file is unreadable")

    ran = []

    @registry.register("01_transform", depends_on=["00_extract"])
    def transform(_: PlanningContext) -> StageResult:
        ran.append("01_transform")
        return StageResult(stage="")

    report = registry.run(ctx)

    assert ran == [], "a stage whose upstream failed does not run"
    assert report.stages[0].status is StageStatus.FAILED
    assert "source file is unreadable" in (report.stages[0].error or "")
    assert report.stages[1].status is StageStatus.SKIPPED
    assert "00_extract" in (report.stages[1].error or "")
    assert not report.ok


def test_skip_propagates_through_the_chain(ctx: PlanningContext) -> None:
    registry = Registry()
    registry.add(_stage("a"))
    registry.add(Stage(name="b", fn=_boom, depends_on=("a",)))
    registry.add(_stage("c", deps=("b",)))

    report = registry.run(ctx)
    statuses = {r.stage: r.status for r in report.stages}

    assert statuses == {
        "a": StageStatus.OK,
        "b": StageStatus.FAILED,
        "c": StageStatus.SKIPPED,
    }


def _boom(_: PlanningContext) -> StageResult:
    raise RuntimeError("boom")


def test_order_is_topological_and_deterministic() -> None:
    registry = Registry()
    registry.add(_stage("z"))
    registry.add(_stage("m", deps=("z",)))
    registry.add(_stage("a", deps=("z",)))
    registry.add(_stage("end", deps=("m", "a")))

    order = registry.order()

    assert order[0] == "z"
    assert order[-1] == "end"
    assert order.index("a") < order.index("end")
    assert registry.order() == order, "repeat calls give the same order"


def test_targets_pull_in_their_dependencies_only() -> None:
    registry = Registry()
    registry.add(_stage("a"))
    registry.add(_stage("b", deps=("a",)))
    registry.add(_stage("unrelated"))

    assert registry.order(["b"]) == ["a", "b"]


def test_cycle_is_rejected() -> None:
    registry = Registry()
    registry.add(_stage("a", deps=("b",)))
    registry.add(_stage("b", deps=("a",)))

    with pytest.raises(CycleError, match="cycle"):
        registry.order()


def test_unknown_dependency_is_rejected() -> None:
    registry = Registry()
    registry.add(_stage("a", deps=("ghost",)))

    with pytest.raises(RegistryError, match="ghost"):
        registry.order()


def test_duplicate_registration_is_rejected() -> None:
    registry = Registry()
    registry.add(_stage("a"))

    with pytest.raises(RegistryError, match="already registered"):
        registry.add(_stage("a"))


def test_stage_returning_the_wrong_type_fails_closed(ctx: PlanningContext) -> None:
    registry = Registry()
    registry.add(Stage(name="bad", fn=lambda _: {"rows": 1}))  # type: ignore[arg-type,return-value]

    report = registry.run(ctx)

    assert report.stages[0].status is StageStatus.FAILED
    assert "expected StageResult" in (report.stages[0].error or "")


def test_render_mentions_every_stage(ctx: PlanningContext) -> None:
    registry = Registry()
    registry.add(_stage("a"))
    registry.add(_stage("b", deps=("a",)))

    text = registry.run(ctx, settings_summary={"plant": "W1B4"}).render()

    assert "a" in text and "b" in text
    assert "plant = W1B4" in text
    assert "2 ok, 0 failed, 0 skipped" in text
