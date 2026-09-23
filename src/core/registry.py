"""Stage registry and the fail-closed DAG runner.

A stage whose upstream failed does not run. Order is deterministic: ready stages are
taken alphabetically, so two runs over the same graph execute identically.
"""

from __future__ import annotations

import time
import traceback
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.core.context import PlanningContext
from src.core.errors import CycleError, RegistryError
from src.core.result import RunReport, StageResult, StageStatus

StageFn = Callable[[PlanningContext], StageResult]


@dataclass(frozen=True)
class Stage:
    name: str
    fn: StageFn
    depends_on: tuple[str, ...] = ()
    description: str = ""


@dataclass
class Registry:
    """Holds the stage graph. Stages register themselves on import."""

    stages: dict[str, Stage] = field(default_factory=dict)

    def add(self, stage: Stage) -> Stage:
        if stage.name in self.stages:
            raise RegistryError(f"stage {stage.name!r} is already registered")
        self.stages[stage.name] = stage
        return stage

    def register(
        self,
        name: str,
        *,
        depends_on: Sequence[str] = (),
        description: str = "",
    ) -> Callable[[StageFn], StageFn]:
        """Decorator form: ``@REGISTRY.register("03_orders", depends_on=["02_parts"])``."""

        def decorator(fn: StageFn) -> StageFn:
            self.add(Stage(name=name, fn=fn, depends_on=tuple(depends_on), description=description))
            return fn

        return decorator

    def get(self, name: str) -> Stage:
        try:
            return self.stages[name]
        except KeyError as exc:
            raise RegistryError(f"unknown stage {name!r}") from exc

    def clear(self) -> None:
        self.stages.clear()

    # ── ordering ────────────────────────────────────────────────────────────────
    def order(self, targets: Iterable[str] | None = None) -> list[str]:
        """Topological order (Kahn), restricted to ``targets`` and their ancestors."""
        selected = self._closure(targets)
        indegree = {n: 0 for n in selected}
        dependents: dict[str, list[str]] = {n: [] for n in selected}
        for name in selected:
            for dep in self.stages[name].depends_on:
                if dep in selected:
                    indegree[name] += 1
                    dependents[dep].append(name)

        ready = sorted(n for n, d in indegree.items() if d == 0)
        ordered: list[str] = []
        while ready:
            name = ready.pop(0)
            ordered.append(name)
            for child in dependents[name]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
                    ready.sort()

        if len(ordered) != len(selected):
            stuck = sorted(set(selected) - set(ordered))
            raise CycleError(f"stage graph contains a cycle involving: {', '.join(stuck)}")
        return ordered

    def _closure(self, targets: Iterable[str] | None) -> set[str]:
        """Targets plus everything they transitively depend on."""
        for name, stage in self.stages.items():
            for dep in stage.depends_on:
                if dep not in self.stages:
                    raise RegistryError(f"stage {name!r} depends on unknown stage {dep!r}")
        if targets is None:
            return set(self.stages)

        wanted: set[str] = set()
        pending = list(targets)
        while pending:
            name = pending.pop()
            if name in wanted:
                continue
            wanted.add(self.get(name).name)
            pending.extend(self.stages[name].depends_on)
        return wanted

    # ── execution ───────────────────────────────────────────────────────────────
    def run(
        self,
        ctx: PlanningContext,
        *,
        targets: Iterable[str] | None = None,
        skip: Iterable[str] | None = None,
        settings_summary: dict[str, object] | None = None,
        report_path: Path | None = None,
    ) -> RunReport:
        """Execute in dependency order, fail-closed, and return the run report.

        ``skip`` treats a stage as already satisfied — for re-running the tail of the
        pipeline without repeating an expensive upstream stage whose artifacts are
        unchanged on disk. Skipped stages count as OK so their dependents still run.
        """
        order = self.order(targets)
        skipped = set(skip or ())
        report = RunReport(
            run_id=uuid.uuid4().hex[:12],
            started_at=datetime.now(UTC).isoformat(timespec="seconds"),
            context=ctx.summary(),
            settings=dict(settings_summary or {}),
        )
        outcomes: dict[str, StageStatus] = {}
        run_started = time.perf_counter()

        for name in order:
            stage = self.stages[name]
            if name in skipped:
                result = StageResult(stage=name, status=StageStatus.OK)
                result.warn("skipped by request — existing artifacts reused unchanged")
                outcomes[name] = StageStatus.OK
                report.add(result)
                continue
            blockers = [d for d in stage.depends_on if outcomes.get(d) is not StageStatus.OK]
            if blockers:
                result = StageResult(stage=name, status=StageStatus.SKIPPED)
                result.error = f"upstream not ok: {', '.join(sorted(blockers))}"
                outcomes[name] = StageStatus.SKIPPED
                report.add(result)
                continue

            started = time.perf_counter()
            try:
                result = stage.fn(ctx)
                if not isinstance(result, StageResult):
                    raise RegistryError(
                        f"stage {name!r} returned {type(result).__name__}, expected StageResult"
                    )
                result.stage = name
            except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
                result = StageResult(stage=name, status=StageStatus.FAILED)
                result.error = f"{type(exc).__name__}: {exc}"
                result.warn(traceback.format_exc(limit=3).strip().splitlines()[-1])
            result.elapsed_seconds = time.perf_counter() - started
            outcomes[name] = result.status
            report.add(result)

        report.elapsed_seconds = time.perf_counter() - run_started
        report.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
        if report_path is not None:
            report.write(report_path)
        return report


REGISTRY = Registry()
"""The process-wide graph. Step modules register into this on import."""
