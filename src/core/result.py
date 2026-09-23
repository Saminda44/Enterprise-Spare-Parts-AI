"""What a stage hands back, and what a run reports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class StageStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageResult:
    """The outcome of one stage. Counts reconcile: ``rows_in == rows_out + rejected``
    wherever a stage filters rather than reshapes."""

    stage: str
    status: StageStatus = StageStatus.OK
    rows_in: int = 0
    rows_out: int = 0
    rejected: int = 0
    reject_reasons: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    error: str | None = None

    def reject(self, reason: str, count: int = 1) -> None:
        """Record dropped rows against a reason — never drop silently."""
        self.rejected += count
        self.reject_reasons[reason] = self.reject_reasons.get(reason, 0) + count

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def artifact(self, name: str, path: Path | str) -> None:
        self.artifacts[name] = str(path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status.value,
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "rejected": self.rejected,
            "reject_reasons": dict(self.reject_reasons),
            "warnings": list(self.warnings),
            "artifacts": dict(self.artifacts),
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "error": self.error,
        }


@dataclass
class RunReport:
    """One record per run: what ran, what it produced, what it rejected and why."""

    run_id: str
    started_at: str
    context: dict[str, Any]
    settings: dict[str, Any] = field(default_factory=dict)
    stages: list[StageResult] = field(default_factory=list)
    finished_at: str | None = None
    elapsed_seconds: float = 0.0

    def add(self, result: StageResult) -> None:
        self.stages.append(result)

    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in StageStatus}
        for r in self.stages:
            out[r.status.value] += 1
        return out

    @property
    def ok(self) -> bool:
        return all(r.status is StageStatus.OK for r in self.stages)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "ok": self.ok,
            "counts": self.counts(),
            "context": self.context,
            "settings": self.settings,
            "stages": [r.to_dict() for r in self.stages],
        }

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path

    def render(self) -> str:
        """Plain-text run report — the thing a human reads after a cycle."""
        lines = [
            f"run {self.run_id}  as_of={self.context.get('as_of')}  "
            f"elapsed={self.elapsed_seconds:.1f}s",
        ]
        for key, value in self.settings.items():
            lines.append(f"  setting  {key} = {value}")
        lines.append(f"  {'stage':<28} {'status':<8} {'in':>9} {'out':>9} {'rej':>8}  elapsed")
        for r in self.stages:
            lines.append(
                f"  {r.stage:<28} {r.status.value:<8} {r.rows_in:>9,} {r.rows_out:>9,} "
                f"{r.rejected:>8,}  {r.elapsed_seconds:>6.2f}s"
            )
            for reason, n in r.reject_reasons.items():
                lines.append(f"      rejected {n:,}: {reason}")
            for w in r.warnings:
                lines.append(f"      warning: {w}")
            if r.error:
                lines.append(f"      error: {r.error}")
        counts = self.counts()
        lines.append(f"  {counts['ok']} ok, {counts['failed']} failed, {counts['skipped']} skipped")
        return "\n".join(lines)
