"""Configuration. Paths and the flags that must be visible in every run report."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def project_root() -> Path:
    """Nearest ancestor holding pyproject.toml."""
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return here.parents[2]


class Settings(BaseSettings):
    """Environment-driven settings, prefix ``SPI_``. No secrets in code."""

    model_config = SettingsConfigDict(
        env_prefix="SPI_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    root: Path = Field(default_factory=project_root)

    # Where source workbooks land. Manual drop into data/raw today; point this at a
    # watched folder later without touching a loader.
    source_dir: Path | None = None

    # Step 12: are On_Orders month columns the expected arrival month, or when the PO
    # was raised? This single assumption shifts the pipeline by a quarter, so it is
    # printed in every run report.
    on_order_interpretation: Literal["arrival", "raised"] = "arrival"

    plant: str = "W1B4"
    lead_time_months: int = 3
    review_period_months: int = 1
    currency: str = "LKR"

    # ── Step 13/14 business parameters ──────────────────────────────────────────
    # NONE of these exist in any supplied source file. They are assumptions, printed in
    # every run report and overridable by environment variable, and every number Step 13
    # produces moves with them. They must be replaced with the owner's real figures
    # before the policy is trusted.
    fill_rate_target_a: float = 0.98
    fill_rate_target_b: float = 0.95
    fill_rate_target_c: float = 0.90
    annual_holding_rate: float = 0.20  # share of unit value per year
    order_cost: float = 5000.0  # LKR per purchase order line
    default_moq: float = 1.0
    default_pack_size: float = 1.0
    use_eoq: bool = True
    # q / beta_hat is a feedback loop: if beta_hat is low because we over-order,
    # inflating lowers it further. Off by default; the simulator must match.
    use_supply_inflation: bool = False
    supply_inflation_cap: float = 1.5

    @property
    def fill_rate_targets(self) -> dict[str, float]:
        return {
            "A": self.fill_rate_target_a,
            "B": self.fill_rate_target_b,
            "C": self.fill_rate_target_c,
        }

    @property
    def raw_dir(self) -> Path:
        return self.source_dir or (self.root / "data" / "raw")

    @property
    def staging_dir(self) -> Path:
        return self.root / "data" / "staging"

    @property
    def facts_dir(self) -> Path:
        return self.root / "data" / "facts"

    @property
    def marts_dir(self) -> Path:
        return self.root / "data" / "marts"

    @property
    def reports_dir(self) -> Path:
        return self.root / "data" / "reports"

    def ensure_dirs(self) -> None:
        """Create the writable layers. ``raw`` is never created or written here."""
        for d in (self.staging_dir, self.facts_dir, self.marts_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)

    def summary(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "raw_dir": str(self.raw_dir),
            "on_order_interpretation": self.on_order_interpretation,
            "plant": self.plant,
            "lead_time_months": self.lead_time_months,
            "review_period_months": self.review_period_months,
            "fill_rate_targets (ASSUMED)": self.fill_rate_targets,
            "annual_holding_rate (ASSUMED)": self.annual_holding_rate,
            "order_cost (ASSUMED)": self.order_cost,
            "use_eoq": self.use_eoq,
            "use_supply_inflation": self.use_supply_inflation,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
