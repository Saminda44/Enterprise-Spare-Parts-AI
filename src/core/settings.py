"""Configuration. Paths and the flags that must be visible in every run report."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr
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
    # Excel is the active source now. PostgreSQL stores the same versioned workbook
    # tables when selected; analytics still consume the normalized parquet mirrors.
    data_backend: Literal["excel", "postgres"] = Field(
        default="excel", validation_alias=AliasChoices("DATA_BACKEND", "SPI_DATA_BACKEND")
    )
    upload_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="SPI_UPLOAD_API_KEY")

    # Step 12: are On_Orders month columns the expected arrival month, or when the PO
    # was raised? This single assumption shifts the pipeline by a quarter, so it is
    # printed in every run report.
    # Owner confirmed 2026-09-30: these are expected arrival months, not PO dates.
    on_order_interpretation: Literal["arrival", "raised"] = "arrival"
    # Owner confirmed 2026-10-02 that the supplied current_stock.xlsx is the
    # September 30 closing snapshot. A later live cycle requires this date to advance
    # with a newly supplied stock file.
    stock_snapshot_as_of: date = date(2026, 9, 30)
    # Owner confirmed 2026-10-01 that the dated On_Orders export lists all open POs.
    on_orders_verified_complete: bool = True

    plant: str = "W1B4"
    lead_time_months: int = 4
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
    # No part's buffer (safety) stock exceeds this many months of its forecast demand
    # (owner, 2026-10-02): with ROL = 1 month + buffer and a 4-month lead time, the reorder
    # level then tops out at the lead time's demand.
    buffer_cap_months: float = 3.0
    # The EOQ floor never asks for more than this many months of a part's demand (owner,
    # 2026-10-02): with the assumed order cost it raised cheap parts to ~10 months.
    eoq_cap_months: float = 3.0
    use_eoq: bool = True
    # q / beta_hat is a feedback loop: if beta_hat is low because we over-order,
    # inflating lowers it further. Off by default; the simulator must match.
    use_supply_inflation: bool = False
    supply_inflation_cap: float = 1.5

    # ── Source refresh ──────────────────────────────────────────────────────────
    # The API watches the source workbooks; when one changes (and has stopped
    # changing for source_settle_seconds, i.e. Excel finished saving) it re-ingests it
    # and re-runs only the stages downstream of it. refresh_as_of pins the cycle date a
    # refresh runs with; unset, it reuses the as_of of the last pipeline run.
    auto_refresh_sources: bool = True
    source_poll_seconds: int = 20
    source_settle_seconds: int = 10
    refresh_as_of: str | None = None

    # ── Catalogue store (PostgreSQL) ────────────────────────────────────────────
    # Extracted PDF catalogues are saved here and the Catalogues page reads them back
    # instead of re-reading each PDF. Read from the unprefixed POSTGRES_* keys that
    # .env already carries; the password is only ever held as a secret.
    postgres_host: str = Field(default="localhost", validation_alias=AliasChoices("POSTGRES_HOST"))
    postgres_port: int = Field(default=5432, validation_alias=AliasChoices("POSTGRES_PORT"))
    postgres_db: str = Field(default="spare_parts", validation_alias=AliasChoices("POSTGRES_DB"))
    postgres_user: str = Field(default="postgres", validation_alias=AliasChoices("POSTGRES_USER"))
    postgres_password: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("POSTGRES_PASSWORD")
    )
    postgres_sslmode: str = Field(
        default="prefer", validation_alias=AliasChoices("POSTGRES_SSLMODE")
    )

    def postgres_params(self) -> dict[str, Any]:
        """Connection keyword arguments for psycopg. Never logged: holds the password."""
        return {
            "host": self.postgres_host,
            "port": self.postgres_port,
            "dbname": self.postgres_db,
            "user": self.postgres_user,
            "password": self.postgres_password.get_secret_value(),
            "sslmode": self.postgres_sslmode,
        }

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
    def source_parquet_dir(self) -> Path:
        """Generated workbook mirrors, kept separate from immutable source files."""
        return self.staging_dir / "sources"

    @property
    def managed_source_dir(self) -> Path:
        """Writable, versioned Excel sources; ``data/raw`` remains immutable."""
        return self.staging_dir / "working_sources"

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
        for d in (
            self.staging_dir,
            self.source_parquet_dir,
            self.managed_source_dir,
            self.facts_dir,
            self.marts_dir,
            self.reports_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def summary(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "raw_dir": str(self.raw_dir),
            "data_backend": self.data_backend,
            "on_order_interpretation": self.on_order_interpretation,
            "stock_snapshot_as_of": self.stock_snapshot_as_of.isoformat(),
            "on_orders_verified_complete": self.on_orders_verified_complete,
            "plant": self.plant,
            "lead_time_months": self.lead_time_months,
            "review_period_months": self.review_period_months,
            "fill_rate_targets (ASSUMED)": self.fill_rate_targets,
            "annual_holding_rate (ASSUMED)": self.annual_holding_rate,
            "order_cost (ASSUMED)": self.order_cost,
            "buffer_cap_months": self.buffer_cap_months,
            "eoq_cap_months": self.eoq_cap_months,
            "use_eoq": self.use_eoq,
            "use_supply_inflation": self.use_supply_inflation,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
