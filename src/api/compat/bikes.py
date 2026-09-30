"""Motorcycle pages: unit-sales analysis, the registration forecast and the parc.

Sales targets and uplift assumptions are planner inputs, not pipeline outputs, so they
live in a small JSON store beside the marts. Everything else is read from a published
mart.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, Body, Query
from src.api.compat.filters import apply_filters, f, i, mart, ratio, s, years_available
from src.core.settings import get_settings
from src.dashboard import unit_forecast
from src.dashboard.vehicles import AGE_BANDS_BUYER, PRICE_BANDS, UNKNOWN_AGE

router = APIRouter(prefix="/bikes", tags=["bikes"])

MC_MEASURES = ["units_sold", "returned", "revenue_lkr", "vins", "dealers"]


def _store(name: str) -> Path:
    """A writable file for planner inputs, kept out of the fact layer."""
    directory = get_settings().marts_dir.parent / "ui_state"
    return directory / name


def _read_store(name: str, default: Any) -> Any:
    path = _store(name)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write_store(name: str, payload: Any) -> None:
    _store(name).parent.mkdir(parents=True, exist_ok=True)
    _store(name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def model_names() -> dict[str, str]:
    """Model code to MCSI model name, from the published ``mart_ui_mc_model_names``."""
    frame = mart("mart_ui_mc_model_names")
    if frame.empty or "model_description" not in frame.columns:
        return {}
    return {
        str(code): str(name).strip()
        for code, name in zip(frame["model_name"], frame["model_description"], strict=False)
        if isinstance(name, str) and name.strip()
    }


#: Name cells that carry no name.
_NO_NAME = {"", "(blank)", "nan", "none"}
#: A model separator in the "model – colour" matrix columns.
_COMBO_SEP = " – "


def parc_model_names() -> dict[str, str]:
    """Model code to Sales Summery model name, for the parc models MCSI never sold."""
    frame = mart("mart_ui_parc_by_model")
    if frame.empty or "model_code" not in frame.columns:
        return {}
    pairs = frame[["model_code", "model_name"]].drop_duplicates("model_code")
    return {
        str(code): str(name).strip()
        for code, name in zip(pairs["model_code"], pairs["model_name"], strict=False)
        if str(name).strip().lower() not in _NO_NAME
    }


def all_model_names() -> dict[str, str]:
    """Every known model code's name — MCSI's where it has one, else Sales Summery's.

    Business meaning: one code reads the same on every motorcycle page, so the MCSI
    name wins wherever MCSI sold the model.
    """
    return {**parc_model_names(), **model_names()}


def model_label(code: str, names: dict[str, str]) -> str:
    """ "FZ FI V2 (B1N2)" — the model name with its code, or the code alone if unnamed."""
    name = names.get(code, "")
    if name.strip().lower() in _NO_NAME:
        return code
    if code.strip().lower() in ("", "unknown"):
        return f"{name} (no code)"  # MCSI names the model but gives no type code
    return f"{name} ({code})" if name.upper() != code.upper() else code


def combo_label(combo: str, names: dict[str, str]) -> str:
    """ "B626 – CYAN METALLIC 6" → "Ray ZR Disc (B626) – CYAN METALLIC 6"."""
    code, sep, colour = combo.partition(_COMBO_SEP)
    return f"{model_label(code, names)}{sep}{colour}"


def model_code_for(value: str, names: dict[str, str]) -> str:
    """The model code behind a filter value, which may be a code or a "Name (Code)" label."""
    if value in names:
        return value
    for code in names:
        if model_label(code, names) == value:
            return code
    return value


def _parc_labelled(frame: pd.DataFrame) -> pd.DataFrame:
    """Add ``model_key`` (the code) and ``model_label`` ("Name (Code)") to a parc mart.

    A mart published before the parc kept its code carries the name only; it is then
    labelled by name, never guessed back to a code.
    """
    if frame.empty:
        return frame.assign(model_key=pd.Series(dtype=str), model_label=pd.Series(dtype=str))
    names = all_model_names()
    if "model_code" in frame.columns:
        keys = frame["model_code"].astype(str)
        labels = keys.map({k: model_label(k, names) for k in keys.unique()})
    else:
        keys = frame["model_name"].astype(str)
        labels = keys
    return frame.assign(model_key=keys, model_label=labels)


def _year_filter(frame: pd.DataFrame, year: int | None) -> pd.DataFrame:
    if frame.empty or not year or "year" not in frame.columns:
        return frame
    return frame[pd.to_numeric(frame["year"], errors="coerce") == int(year)]


def _collapse(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[*keys, *MC_MEASURES])
    present = [k for k in keys if k in frame.columns]
    measures = [m for m in MC_MEASURES if m in frame.columns]
    return frame.groupby(present, as_index=False, dropna=False)[measures].sum()


@router.get("/mcsi-eda")
def mcsi_eda(year: int = Query(0)) -> dict[str, Any]:
    """Unit sales by month, model and geography."""
    kpi_frame = mart("mart_ui_mc_kpis")
    kpis = kpi_frame.iloc[0].to_dict() if not kpi_frame.empty else {}

    monthly_all = mart("mart_ui_mc_monthly")
    monthly = _collapse(_year_filter(monthly_all, year), ["month"]).sort_values("month")
    by_model = _collapse(_year_filter(mart("mart_ui_mc_by_model"), year), ["model_name"])
    names = all_model_names()
    by_colour = _collapse(
        _year_filter(mart("mart_ui_mc_by_model_colour"), year), ["model_name", "colour"]
    )
    by_province = _collapse(_year_filter(mart("mart_ui_mc_by_province"), year), ["province"])
    by_district = _collapse(
        _year_filter(mart("mart_ui_mc_by_district"), year), ["province", "district"]
    )
    by_rm = _collapse(_year_filter(mart("mart_ui_mc_by_rm"), year), ["rm"])
    by_ase = _collapse(_year_filter(mart("mart_ui_mc_by_ase"), year), ["ase", "rm"])
    by_year = _collapse(monthly_all, ["year"]).sort_values("year")
    dealers = _year_filter(mart("mart_ui_mc_by_dealer"), year)

    total_units = float(by_model["units_sold"].sum()) if not by_model.empty else 0.0
    months = int(monthly["month"].nunique()) if not monthly.empty else 0

    def dealer_count(column: str, value: str) -> int:
        if dealers.empty or column not in dealers.columns:
            return 0
        return int(dealers.loc[dealers[column] == value, "dealer_name"].nunique())

    def ase_count(rm: str) -> int:
        if by_ase.empty or "rm" not in by_ase.columns:
            return 0
        return int(by_ase.loc[by_ase["rm"] == rm, "ase"].nunique())

    sold = float(kpis.get("sold", total_units))
    returned = float(kpis.get("returned", 0.0))
    revenue = float(kpis.get("total_revenue_lkr", 0.0))

    return {
        "kpis": {
            "total_vins": i(kpis.get("total_vins")),
            "sold": sold,
            "returned": returned,
            # Per VIN: returned VINs (SlsVolQty sums to 0) over VINs sold or returned.
            "return_rate_pct": ratio(returned, sold + returned, scale=100),
            "billing_reversals": i(kpis.get("billing_reversals")),
            "rebilled_vins": i(kpis.get("rebilled_vins")),
            "total_revenue_lkr": revenue,
            "avg_monthly_units": ratio(sold, max(i(kpis.get("months_of_data")), 1)),
            "avg_revenue_per_unit": ratio(revenue, sold),
            "active_provinces": i(kpis.get("active_provinces")),
            "active_dealers": i(kpis.get("active_dealers")),
            "models_sold": i(kpis.get("models_sold")),
            "date_from": s(kpis.get("date_from")),
            "date_to": s(kpis.get("date_to")),
            "months_of_data": i(kpis.get("months_of_data")),
        },
        "monthly_trend": [
            {
                "period": s(row["month"]),
                "sold": f(row["units_sold"]),
                "revenue_lkr": f(row["revenue_lkr"]),
            }
            for _, row in monthly.iterrows()
        ],
        "by_year": [
            {
                "year": i(row["year"]),
                "units_sold": f(row["units_sold"]),
                "revenue_lkr": f(row["revenue_lkr"]),
                "avg_monthly": ratio(row["units_sold"], max(months, 1)),
            }
            for _, row in by_year.iterrows()
        ],
        "by_model": [
            {
                "model": s(row["model_name"]),
                # MCSI's model name, and "Name (Code)" for labels.
                "model_description": names.get(s(row["model_name"]), ""),
                "model_label": model_label(s(row["model_name"]), names),
                "units_sold": f(row["units_sold"]),
                "revenue_lkr": f(row["revenue_lkr"]),
                "share_pct": ratio(row["units_sold"], total_units, scale=100),
                "avg_revenue_per_unit": ratio(row["revenue_lkr"], row["units_sold"]),
            }
            for _, row in by_model.sort_values("units_sold", ascending=False).iterrows()
        ],
        "by_province": [
            {
                "province": s(row["province"]),
                "units_sold": f(row["units_sold"]),
                "revenue_lkr": f(row["revenue_lkr"]),
                "share_pct": ratio(row["units_sold"], total_units, scale=100),
                "dealer_count": dealer_count("province", s(row["province"])),
            }
            for _, row in by_province.sort_values("units_sold", ascending=False).iterrows()
        ],
        # Sold VINs per model and colour (MCSI "Color"), largest first.
        "by_color": [
            {
                "model": model_label(s(row["model_name"]), names),
                "color": s(row["colour"]),
                "units_sold": f(row["units_sold"]),
            }
            for _, row in by_colour.sort_values(
                ["model_name", "units_sold"], ascending=[True, False]
            ).iterrows()
            if f(row["units_sold"]) > 0
        ],
        "by_rm": [
            {
                "rm": s(row["rm"]),
                "units_sold": f(row["units_sold"]),
                "revenue_lkr": f(row["revenue_lkr"]),
                "dealer_count": dealer_count("rm", s(row["rm"])),
                "ase_count": ase_count(s(row["rm"])),
                "share_pct": ratio(row["units_sold"], total_units, scale=100),
                "avg_revenue_per_unit": ratio(row["revenue_lkr"], row["units_sold"]),
            }
            for _, row in by_rm.sort_values("units_sold", ascending=False).iterrows()
        ],
        "by_ase": [
            {
                "ase": s(row["ase"]),
                "rm": s(row.get("rm", "")),
                "units_sold": f(row["units_sold"]),
                "revenue_lkr": f(row["revenue_lkr"]),
                "dealer_count": dealer_count("ase", s(row["ase"])),
                "share_pct": ratio(row["units_sold"], total_units, scale=100),
            }
            for _, row in by_ase.sort_values("units_sold", ascending=False).iterrows()
        ],
        "by_district": [
            {
                "province": s(row["province"]),
                "district": s(row["district"]),
                "units_sold": f(row["units_sold"]),
                "revenue_lkr": f(row["revenue_lkr"]),
                "share_pct": ratio(row["units_sold"], total_units, scale=100),
            }
            for _, row in by_district.sort_values("units_sold", ascending=False).iterrows()
        ],
    }


def _forecast_rows(model: str | None = None) -> pd.DataFrame:
    """Registration forecast rows; ``model`` may be a code or a "Name (Code)" label."""
    frame = mart("mart_ui_mc_sales_forecast")
    if frame.empty:
        return frame
    return frame[frame["model"] == model_code_for(model, all_model_names())] if model else frame


def _forecast_method() -> str:
    """The method behind the published forecast, as the dashboard stage recorded it."""
    frame = mart("mart_ui_mc_sales_forecast_total")
    if frame.empty or "method" not in frame.columns:
        return ""
    return s(frame["method"].iloc[0])


def _sales_forecast_series() -> list[dict[str, Any]]:
    """The monthly total the page charts: active models summed, with the total band.

    Read from ``mart_ui_mc_sales_forecast_total`` so the total, the model forecasts and
    the band all come from one published method; older marts fall back to summing.
    """
    grouped = mart("mart_ui_mc_sales_forecast_total")
    if grouped.empty:
        frame = _forecast_rows()
        if frame.empty:
            return []
        grouped = frame.groupby(["period", "is_forecast"], as_index=False)[
            ["forecast_units", "lower_80", "upper_80", "actual_units"]
        ].sum(min_count=1)
    targets = _read_store("targets.json", {"yearly_target": 0, "monthly_overrides": {}})
    overrides = targets.get("monthly_overrides", {})
    yearly = float(targets.get("yearly_target") or 0)
    monthly_target = yearly / 12.0 if yearly else 0.0

    out = []
    for _, row in grouped.sort_values("period").iterrows():
        period = s(row["period"])
        is_forecast = bool(row["is_forecast"])
        target = float(overrides.get(period, monthly_target)) or None
        point = f(row["forecast_units"])
        out.append(
            {
                "period": period,
                "forecast": point,
                "lower_80": f(row["lower_80"]),
                "upper_80": f(row["upper_80"]),
                "actual": None if is_forecast else f(row["actual_units"]),
                "is_forecast": is_forecast,
                "target": target,
                "target_gap": (point - target) if target else None,
            }
        )
    return out


def _uio_series() -> list[dict[str, Any]]:
    frame = mart("mart_ui_parc_series")
    if frame.empty:
        return []
    return [
        {
            "period": s(row["period"]),
            "new_sales": f(row["new_sales"]),
            "uio_total": f(row["uio_total"]),
            "attrition": f(row["attrition"]),
            "is_forecast": bool(row["is_forecast"]),
            "lower_80": f(row["lower_80"]),
            "upper_80": f(row["upper_80"]),
        }
        for _, row in frame.sort_values("year").iterrows()
    ]


@router.get("")
def bikes() -> dict[str, Any]:
    """The motorcycle summary the landing page shows."""
    by_model = _collapse(mart("mart_ui_mc_by_model"), ["model_name"])
    by_province = _collapse(mart("mart_ui_mc_by_province"), ["province"])
    monthly = _collapse(mart("mart_ui_mc_monthly"), ["month"]).sort_values("month")
    kpi_frame = mart("mart_ui_mc_kpis")
    kpis = kpi_frame.iloc[0].to_dict() if not kpi_frame.empty else {}
    total = float(by_model["units_sold"].sum()) if not by_model.empty else 0.0
    names = all_model_names()

    return {
        "mcsi": {
            "total_sold": total,
            "date_from": s(kpis.get("date_from")),
            "date_to": s(kpis.get("date_to")),
            "by_model": [
                {
                    "model": model_label(s(row["model_name"]), names),
                    "count": f(row["units_sold"]),
                    "pct": ratio(row["units_sold"], total, scale=100),
                }
                for _, row in by_model.sort_values("units_sold", ascending=False).iterrows()
            ],
            "by_province": [
                {"province": s(row["province"]), "count": f(row["units_sold"])}
                for _, row in by_province.sort_values("units_sold", ascending=False).iterrows()
            ],
            "monthly_trend": [
                {
                    "period": s(row["month"]),
                    "sold": f(row["units_sold"]),
                    "revenue_lkr": f(row["revenue_lkr"]),
                }
                for _, row in monthly.iterrows()
            ],
        },
        "sales_forecast": _sales_forecast_series(),
        "forecast_method": _forecast_method(),
        "uio_forecast": _uio_series(),
    }


@router.get("/forecast/by-model")
def forecast_by_model() -> dict[str, Any]:
    """Monthly registrations per model, actual and forecast."""
    frame = _forecast_rows()
    if frame.empty:
        return {"models": [], "rows": []}
    names = all_model_names()
    rows = [
        {
            "period": s(row["period"]),
            "model": model_label(s(row["model"]), names),
            "actual": None if bool(row["is_forecast"]) else f(row["actual_units"]),
            "forecast": f(row["forecast_units"]),
            "is_forecast": bool(row["is_forecast"]),
        }
        for _, row in frame.sort_values(["model", "period"]).iterrows()
    ]
    models = sorted({model_label(s(m), names) for m in frame["model"].unique()})
    # Per model: Active in Sales Summery's Model Classification, and months of history.
    info = frame.drop_duplicates("model")
    model_info = [
        {
            "model": model_label(s(row["model"]), names),
            "code": s(row["model"]),
            "is_active": bool(row.get("is_active", True)),
            "history_months": i(row.get("history_months")),
        }
        for _, row in info.iterrows()
    ]
    return {
        "models": models,
        "active_models": sorted(m["model"] for m in model_info if m["is_active"]),
        "model_info": model_info,
        "rows": rows,
    }


def _error_stats(forecast: pd.Series, actual: pd.Series) -> dict[str, float | None]:
    """Total error and WAPE over the months that have an actual."""
    actual_sum = float(actual.sum())
    forecast_sum = float(forecast.sum())
    return {
        "forecast": forecast_sum,
        "actual": actual_sum,
        "error_pct": ratio(forecast_sum - actual_sum, actual_sum, scale=100)
        if actual_sum
        else None,
        # Weighted absolute % error: monthly misses, not netted against each other.
        "wape_pct": ratio(float((forecast - actual).abs().sum()), actual_sum, scale=100)
        if actual_sum
        else None,
    }


@router.get("/forecast/backtest")
def forecast_backtest(
    train_start: str = Query("2025-04", pattern=r"^\d{4}-\d{2}$"),
    train_end: str = Query("2025-12", pattern=r"^\d{4}-\d{2}$"),
    horizon: int = Query(12, ge=1, le=24),
) -> dict[str, Any]:
    """Fit on a past window, forecast the months after it, and score against actuals.

    Active models only. A model with no sales in the training window (a later launch)
    cannot be forecast from it; its actuals are reported apart so they neither inflate
    nor excuse the score.
    """
    frame = _forecast_rows()
    empty = {
        "train_start": train_start,
        "train_end": train_end,
        "methods": [],
        "monthly": [],
        "models": [],
        "summary": [],
        "new_models": [],
        "scored_periods": [],
        "model_monthly": [],
    }
    if frame.empty or train_end < train_start:
        return empty
    if "is_active" in frame.columns:
        frame = frame[frame["is_active"].astype(bool)]
    actual = frame.loc[~frame["is_forecast"].astype(bool), ["period", "model", "actual_units"]]
    families = (
        {
            s(m): s(fam)
            for m, fam in frame[["model", "family"]]
            .drop_duplicates("model")
            .itertuples(index=False)
            if s(fam)
        }
        if "family" in frame.columns
        else {}
    )
    result = unit_forecast.backtest(actual, train_start, train_end, horizon, families)
    if result.empty:
        return empty

    names = all_model_names()
    methods = unit_forecast.all_methods()
    keys = [key for key, _ in methods]
    scored = result[result["actual_units"].notna()]
    trained = scored[scored["train_months"] > 0]
    new = scored[scored["train_months"] == 0]

    monthly = []
    for period, group in result.groupby("period"):
        fit = group[group["train_months"] > 0]
        has_actual = bool(group["actual_units"].notna().any())
        monthly.append(
            {
                "period": s(period),
                "actual": f(fit["actual_units"].sum()) if has_actual else None,
                "actual_new_models": f(group.loc[group["train_months"] == 0, "actual_units"].sum())
                if has_actual
                else None,
                **{k: f(fit[k].sum()) for k in keys},
            }
        )
    # The training months themselves, so the chart shows what the fit was built on.
    train_actual = (
        actual[(actual["period"] >= train_start) & (actual["period"] <= train_end)]
        .groupby("period")["actual_units"]
        .sum()
    )
    history = [{"period": s(p), "train_actual": f(v)} for p, v in train_actual.items()]

    models = []
    for model, group in trained.groupby("model"):
        models.append(
            {
                "model": model_label(s(model), names),
                "train_months": i(group["train_months"].iloc[0]),
                **{k: _error_stats(group[k], group["actual_units"]) for k in keys},
            }
        )
    models.sort(key=lambda r: r[keys[0]]["actual"], reverse=True)

    # Every model's forecast and actual month by month — the model-wise monthly view.
    # A model with no training sales is forecast at zero; ``is_new`` says why.
    model_monthly = [
        {
            "model": model_label(s(row["model"]), names),
            "period": s(row["period"]),
            "is_new": int(row["train_months"]) == 0,
            "actual": None if pd.isna(row["actual_units"]) else f(row["actual_units"]),
            **{k: f(row[k]) for k in keys},
        }
        for _, row in result.sort_values(["model", "period"]).iterrows()
    ]

    return {
        "model_monthly": model_monthly,
        "train_start": train_start,
        "train_end": train_end,
        "horizon": horizon,
        "scored_periods": sorted(scored["period"].unique().tolist()),
        "methods": [{"key": k, "label": label} for k, label in methods],
        "recommended": unit_forecast.RECOMMENDED,
        # The method the page's forward forecast is published with.
        "published": unit_forecast.RECOMMENDED if _forecast_method() else "seasonal_run_rate",
        "summary": [{"key": k, **_error_stats(trained[k], trained["actual_units"])} for k in keys],
        "history": history,
        "monthly": monthly,
        "models": models,
        "new_models": [
            {"model": model_label(s(m), names), "actual": f(g["actual_units"].sum())}
            for m, g in new.groupby("model")
            if g["actual_units"].sum() > 0
        ],
    }


@router.get("/sales-forecast")
def m1_sales_forecast(
    model: str | None = None, limit: int = Query(5000, le=50000)
) -> dict[str, Any]:
    """The forecast horizon only, per model."""
    frame = _forecast_rows(model)
    if frame.empty:
        return {"total": 0, "rows": [], "models": []}
    forward = frame[frame["is_forecast"]]
    names = all_model_names()
    rows = [
        {
            "month": s(row["period"]),
            "model": model_label(s(row["model"]), names),
            "forecast_units": f(row["forecast_units"]),
            "lower_ci": f(row["lower_80"]),
            "upper_ci": f(row["upper_80"]),
        }
        for _, row in forward.head(limit).iterrows()
    ]
    models = sorted({model_label(s(m), names) for m in frame["model"].unique()})
    return {"total": len(forward), "rows": rows, "models": models}


@router.get("/uio-forecast-m1")
def uio_forecast(model: str | None = None, limit: int = Query(5000, le=50000)) -> dict[str, Any]:
    """Units in operation per model and year."""
    frame = _parc_labelled(mart("mart_ui_parc_by_model"))
    if frame.empty:
        return {"total": 0, "rows": [], "models": []}
    if model:
        code = model_code_for(model, all_model_names())
        frame = frame[(frame["model_key"] == code) | (frame["model_label"] == model)]
    rows = [
        {
            "month": s(i(row["year"])),
            "model": s(row["model_label"]),
            "uio_forecast": f(row["uio_forecast"]),
        }
        for _, row in frame.sort_values(["model_label", "year"]).head(limit).iterrows()
    ]
    return {
        "total": int(len(frame)),
        "rows": rows,
        "models": sorted(frame["model_label"].unique().tolist()),
    }


@router.get("/uio")
def uio_comparison() -> dict[str, Any]:
    """The fleet as the cohort model sees it, against the models still being sold."""
    parc = _parc_labelled(mart("mart_ui_parc_by_model"))
    mcsi = _collapse(mart("mart_ui_mc_by_model"), ["model_name"])
    names = all_model_names()
    if parc.empty:
        return {"external": [], "mcsi": []}
    latest = int(parc.loc[~parc["is_forecast"], "year"].max())
    current = parc[(parc["year"] == latest) & (~parc["is_forecast"])]
    total = float(mcsi["units_sold"].sum()) or 1.0

    sold = (
        dict(zip(mcsi["model_name"].astype(str), mcsi["units_sold"], strict=False))
        if not mcsi.empty
        else {}
    )
    # MCSI and Sales Summery share the type code (B1N2 …), so sales join on it.
    external = [
        {
            "model": s(row["model_label"]),
            "total_sales_units": f(sold.get(s(row["model_key"]), 0.0)),
            "uio": f(row["uio_forecast"]),
        }
        for _, row in current.sort_values("uio_forecast", ascending=False).iterrows()
    ]
    return {
        "external": external,
        "mcsi": [
            {
                "model": model_label(s(row["model_name"]), names),
                "uio": f(row["units_sold"]),
                "uio_pct": ratio(row["units_sold"], total, scale=100),
            }
            for _, row in mcsi.sort_values("units_sold", ascending=False).iterrows()
        ],
    }


@router.get("/age-distribution")
def age_distribution() -> dict[str, Any]:
    """The fleet's age profile — the import-ban hole is real and is not smoothed."""
    frame = mart("mart_ui_parc_age")
    if frame.empty:
        return {"total": 0, "rows": []}
    frame = _parc_labelled(frame.rename(columns={"model": "model_name"}))
    rows = [
        {
            "model": s(row["model_label"]),
            "age_cohort": s(row["age_cohort"]),
            "vehicle_count": f(row["vehicle_count"]),
            "pct_of_fleet": f(row["pct_of_fleet"]),
        }
        for _, row in frame.sort_values("vehicle_count", ascending=False).iterrows()
    ]
    return {"total": len(rows), "rows": rows}


@router.get("/dealers")
def dealers(limit: int = Query(500, le=20000), year: int | None = None) -> dict[str, Any]:
    """Registrations by dealer."""
    frame = _year_filter(mart("mart_ui_mc_by_dealer"), year)
    grouped = _collapse(frame, ["dealer_code", "dealer_name", "province", "district", "rm", "ase"])
    return {
        "total_dealers": int(grouped["dealer_name"].nunique()) if not grouped.empty else 0,
        "total_units": float(grouped["units_sold"].sum()) if not grouped.empty else 0.0,
        "total_revenue_lkr": float(grouped["revenue_lkr"].sum()) if not grouped.empty else 0.0,
        "available_years": years_available(mart("mart_ui_mc_by_dealer")),
        "rows": [
            {
                "province": s(row["province"]),
                "rm": s(row["rm"]),
                "ase": s(row["ase"]),
                "dealer": s(row["dealer_name"]),
                "dealer_code": s(row["dealer_code"]),
                "units_sold": f(row["units_sold"]),
                "revenue_lkr": f(row["revenue_lkr"]),
            }
            for _, row in grouped.sort_values("units_sold", ascending=False).head(limit).iterrows()
        ],
    }


def _matrix(
    level: str, entity_keys: list[str], label: str, year: int | None = None
) -> dict[str, Any]:
    frame = _year_filter(mart(f"mart_ui_mc_matrix_{level}"), year)
    if frame.empty:
        return {"models": [], "rows": []}
    # Columns are model codes, "code – colour" combos, or (color_* levels) plain colours.
    if not level.startswith("color_"):
        names = all_model_names()
        relabel = combo_label if level.startswith("model_color_") else model_label
        frame = frame.assign(
            model_name=frame["model_name"]
            .astype(str)
            .map({v: relabel(v, names) for v in frame["model_name"].astype(str).unique()})
        )
    models = sorted(frame["model_name"].unique().tolist())
    grouped = frame.groupby([*entity_keys, "model_name"], as_index=False)["units_sold"].sum()
    rows = []
    for entity, group in grouped.groupby(entity_keys[0] if len(entity_keys) == 1 else entity_keys):
        key = entity if isinstance(entity, str) else entity[0]
        totals = {s(r["model_name"]): f(r["units_sold"]) for _, r in group.iterrows()}
        row: dict[str, Any] = {
            label: s(key),
            "total": float(sum(totals.values())),
            "totals": totals,
        }
        if len(entity_keys) > 1 and not isinstance(entity, str):
            for name, value in zip(entity_keys, entity, strict=False):
                row.setdefault(name, s(value))
        rows.append(row)
    rows.sort(key=lambda r: r["total"], reverse=True)
    return {"models": models, "rows": rows}


@router.get("/dealer-model-matrix")
def dealer_model_matrix(year: int | None = None) -> dict[str, Any]:
    """Dealers by model, as a crosstab."""
    out = _matrix("dealer", ["dealer_name", "dealer_code", "province", "rm", "ase"], "dealer", year)
    for row in out["rows"]:
        row.setdefault("dealer_code", "")
        row.setdefault("province", "")
        row.setdefault("rm", "")
        row.setdefault("ase", "")
    return out


@router.get("/geo-model")
def geo_model(year: int | None = None) -> dict[str, Any]:
    """Model mix at each level of the sales hierarchy."""
    return {
        "rm": _matrix("rm", ["rm"], "entity", year),
        "ase": _matrix("ase", ["ase"], "entity", year),
        "province": _matrix("province", ["province"], "entity", year),
        "district": _matrix("district", ["district"], "entity", year),
    }


@router.get("/geo-color")
def geo_color(year: int | None = None) -> dict[str, Any]:
    """Colour mix at each level of the sales hierarchy (columns are colours)."""
    return {
        level: _matrix(f"color_{level}", [level], "entity", year)
        for level in ("rm", "ase", "province", "district")
    }


@router.get("/geo-model-color")
def geo_model_color(year: int | None = None) -> dict[str, Any]:
    """Model and colour mix at each level (columns are "model – colour")."""
    return {
        level: _matrix(f"model_color_{level}", [level], "entity", year)
        for level in ("rm", "ase", "province", "district")
    }


@router.get("/crosstab")
def crosstab(year: int | None = None) -> dict[str, Any]:
    """Provinces by model."""
    out = _matrix("province", ["province"], "province", year)
    return {"models": out["models"], "rows": out["rows"]}


@router.get("/targets")
def get_targets() -> dict[str, Any]:
    """The planner's unit target. An input, not a pipeline output."""
    return _read_store("targets.json", {"yearly_target": 0, "monthly_overrides": {}})


@router.post("/targets")
def set_targets(body: Annotated[dict[str, Any], Body()]) -> dict[str, bool]:
    """Save the planner's unit target."""
    _write_store(
        "targets.json",
        {
            "yearly_target": float(body.get("yearly_target") or 0),
            "monthly_overrides": {
                str(k): float(v) for k, v in (body.get("monthly_overrides") or {}).items()
            },
        },
    )
    return {"ok": True}


@router.get("/uplift-inputs")
def get_uplift() -> list[dict[str, Any]]:
    """Per-month uplift assumptions the planner enters by hand."""
    return _read_store("uplift_inputs.json", [])


@router.post("/uplift-inputs")
def set_uplift(rows: Annotated[list[dict[str, Any]], Body()]) -> dict[str, bool]:
    """Save the uplift assumptions."""
    _write_store("uplift_inputs.json", rows)
    return {"ok": True}


@router.get("/dealer-uplift-baseline")
def dealer_uplift_baseline() -> dict[str, float]:
    """Each dealer's share of recent registrations, as the baseline an uplift applies to."""
    grouped = _collapse(mart("mart_ui_mc_by_dealer"), ["dealer_name"])
    if grouped.empty:
        return {}
    total = float(grouped["units_sold"].sum()) or 1.0
    return {
        s(row["dealer_name"]): ratio(row["units_sold"], total, scale=100)
        for _, row in grouped.sort_values("units_sold", ascending=False).iterrows()
    }


def _active_mix() -> pd.DataFrame:
    """The last-12-month model × colour mix, active models only."""
    mix = mart("mart_ui_mc_mix_12m")
    if mix.empty:
        return mix
    forecast = _forecast_rows()
    if not forecast.empty and "is_active" in forecast.columns:
        active = set(forecast.loc[forecast["is_active"].astype(bool), "model"].astype(str))
        mix = mix[mix["model_name"].astype(str).isin(active)]
    return mix


def _allocate(mix: pd.DataFrame, target: float) -> list[dict[str, Any]]:
    """Whole-unit split of one target to models, then colours (largest remainder)."""
    if mix.empty:
        return []
    names = all_model_names()
    by_model = mix.groupby("model_name")["units"].sum().sort_values(ascending=False)
    total_units = float(by_model.sum())
    model_units = unit_forecast.whole_unit_split(
        int(round(float(target))), by_model.astype(float).tolist()
    )
    rows: list[dict[str, Any]] = []
    for model, allocated in zip(by_model.index, model_units, strict=True):
        colours = mix[mix["model_name"] == model].sort_values("units", ascending=False)
        colour_units = unit_forecast.whole_unit_split(
            allocated, colours["units"].astype(float).tolist()
        )
        for (_, row), colour_alloc in zip(colours.iterrows(), colour_units, strict=True):
            rows.append(
                {
                    "model": model_label(s(model), names),
                    "color": s(row["colour"]),
                    "historical_units": f(row["units"]),
                    "share_pct": ratio(row["units"], total_units, scale=100),
                    "allocated_units": colour_alloc,
                    "window_start": s(row["window_start"]),
                    "window_end": s(row["window_end"]),
                }
            )
    return rows


@router.get("/target-breakdown")
def target_breakdown(month_key: str, target: float) -> list[dict[str, Any]]:
    """Split a unit target to active models, then to colours, on the last 12 months' mix.

    Whole units at both levels (largest remainder), so the colours add up to their model
    and the models add up to the target exactly. Inactive models get none of it.
    """
    return _allocate(_active_mix(), target)


@router.post("/target-breakdown/monthly")
def target_breakdown_monthly(
    targets: Annotated[dict[str, float], Body(embed=True)],
) -> list[dict[str, Any]]:
    """Each month's target split to models and colours — the monthly allocation plan.

    ``targets`` maps YYYY-MM to that month's unit target. Every month is allocated on
    its own in whole units, so each month's rows add up to exactly its target.
    """
    mix = _active_mix()
    rows: list[dict[str, Any]] = []
    for period in sorted(targets):
        for row in _allocate(mix, targets[period]):
            rows.append({"period": period, **row})
    return rows


#: A search needs this many characters of a chassis or batch number, so a stray keystroke
#: does not list half the fleet.
VEHICLE_SEARCH_MIN_CHARS = 4
VEHICLE_SEARCH_LIMIT = 25


def _clean_id(value: str) -> str:
    return "".join(ch for ch in str(value).upper() if ch.isalnum())


@router.get("/vehicle-search")
def vehicle_search(q: str = "") -> dict[str, Any]:
    """Bikes whose chassis (VIN) or batch number contains ``q`` (letters and digits only)."""
    needle = _clean_id(q)
    if len(needle) < VEHICLE_SEARCH_MIN_CHARS:
        return {"query": q, "total": 0, "rows": [], "min_chars": VEHICLE_SEARCH_MIN_CHARS}
    frame = mart("mart_ui_vehicle")
    if frame.empty:
        return {"query": q, "total": 0, "rows": [], "min_chars": VEHICLE_SEARCH_MIN_CHARS}
    vin = frame["vin"].astype(str).str.upper()
    batch = frame["batch"].astype(str).str.upper()
    hits = frame[vin.str.contains(needle, regex=False) | batch.str.contains(needle, regex=False)]
    # Exact matches first, then by chassis number.
    exact = (hits["vin"].astype(str).str.upper() == needle) | (hits["batch"].astype(str) == needle)
    hits = hits.assign(_exact=exact).sort_values(["_exact", "vin"], ascending=[False, True])
    names = all_model_names()
    return {
        "query": q,
        "total": int(len(hits)),
        "min_chars": VEHICLE_SEARCH_MIN_CHARS,
        "rows": [
            {
                "vin": s(r["vin"]),
                "batch": s(r["batch"]),
                "model": model_label(s(r["model_code"]), names),
                "colour": s(r["colour"]),
                "first_billed": s(r["first_billed"]),
                "dealer_name": s(r["dealer_name"]),
                "status": s(r["status"]),
            }
            for _, r in hits.head(VEHICLE_SEARCH_LIMIT).iterrows()
        ],
    }


@router.get("/vehicle/{vin}")
def vehicle_detail(vin: str) -> dict[str, Any]:
    """Everything recorded about one bike: identity, sale, billing history and its model
    in context."""
    from fastapi import HTTPException  # noqa: PLC0415

    key = _clean_id(vin)
    frame = mart("mart_ui_vehicle")
    row = frame[frame["vin"].astype(str).str.upper() == key]
    if row.empty:
        raise HTTPException(404, f"no bike with chassis number {vin}")
    v = row.iloc[0]
    names = all_model_names()
    code = s(v["model_code"])
    num = lambda x: f(x) if pd.notna(x) else None  # noqa: E731 - nullable float

    lines = mart("mart_ui_vehicle_billing")
    lines = lines[lines["vin"].astype(str).str.upper() == key].sort_values("billing_date")

    price = mart("mart_ui_mc_model_price")
    price_row = price[price["model_name"].astype(str) == code]
    list_price = f(price_row["list_price"].iloc[0]) if not price_row.empty else None
    uio = mart("mart_ui_uio_models")
    uio_row = uio[uio["model_code"].astype(str) == code] if not uio.empty else uio
    same_model = frame[frame["model_code"].astype(str) == code]
    first = pd.to_datetime(v["first_billed"], errors="coerce")
    age_months = (
        int((pd.Timestamp.now().normalize() - first).days // 30.44) if pd.notna(first) else None
    )

    return {
        "vin": s(v["vin"]),
        "identity": {
            "batch": s(v["batch"]),
            "model_code": code,
            "model": model_label(code, names),
            "colour": s(v["colour"]),
            "motorcycle_type": s(v["motorcycle_type"]),
            "cc": num(price_row["cc"].iloc[0]) if not price_row.empty else None,
            "segment": s(price_row["segment"].iloc[0]) if not price_row.empty else None,
            "status": s(v["status"]),
            "age_months": age_months,
        },
        "sale": {
            "first_billed": s(v["first_billed"]),
            "last_billed": s(v["last_billed"]),
            "net_sales": f(v["net_sales"]),
            "list_price": list_price,
            "discount_vs_list": (list_price - f(v["net_sales"])) if list_price else None,
            "dealer_code": s(v["dealer_code"]),
            "dealer_name": s(v["dealer_name"]),
            "province": s(v["province"]),
            "district": s(v["district"]),
            "rm": s(v["rm"]),
            "ase": s(v["ase"]),
            "customer_id": s(v["customer_id"]),
            "age_at_purchase": num(v["age_at_purchase"]),
            "age_today": num(v["age_today"]),
        },
        "billing": [
            {
                "date": s(r["billing_date"]),
                "document": s(r["billing_document"]),
                "bill_type": s(r["bill_type"]),
                "quantity": f(r["quantity"]),
                "sales_price": f(r["sales_price"]),
                "discount": f(r["discount"]),
                "net_sales": f(r["net_sales"]),
                "dealer_name": s(r["dealer_name"]),
            }
            for _, r in lines.iterrows()
        ],
        "model_context": {
            "bikes_sold": int((same_model["status"] == "sold").sum()),
            "same_colour_sold": int(
                ((same_model["status"] == "sold") & (same_model["colour"] == v["colour"])).sum()
            ),
            "dealer_bikes_of_model": int(
                (same_model["dealer_code"].astype(str) == s(v["dealer_code"])).sum()
            ),
            "fleet_in_operation": num(uio_row["uio_base"].iloc[0]) if len(uio_row) else None,
            "fleet_registered": num(uio_row["registered"].iloc[0]) if len(uio_row) else None,
            "fleet_surviving_pct": num(uio_row["surviving_pct"].iloc[0]) if len(uio_row) else None,
        },
    }


@router.get("/buyer-age")
def buyer_age() -> dict[str, Any]:
    """Bikes sold by buyer age band, model and colour (counts only, no customer data)."""
    cube = mart("mart_ui_mc_age_model_colour")
    per_model = mart("mart_ui_mc_age_model")
    if cube.empty:
        return {"bands": [], "models": [], "cube": [], "totals": {}}
    names = all_model_names()
    label = lambda code: model_label(s(code), names)  # noqa: E731 - "Name (Code)"
    num = lambda v: f(v) if pd.notna(v) else None  # noqa: E731 - nullable float
    bands = [b[1] for b in AGE_BANDS_BUYER] + [UNKNOWN_AGE]
    by_band = cube.groupby("age_band")["units"].sum()
    known = float(by_band.drop(labels=[UNKNOWN_AGE], errors="ignore").sum())
    return {
        "bands": [
            {
                "band": band,
                "units": f(by_band.get(band, 0.0)),
                "share_pct": ratio(float(by_band.get(band, 0.0)), known, scale=100)
                if band != UNKNOWN_AGE
                else None,
            }
            for band in bands
        ],
        "totals": {
            "units": f(cube["units"].sum()),
            "units_with_age": known,
            "median_age": num(per_model["overall_median_age"].iloc[0]),
            "under_26_pct": ratio(
                float(by_band.get("16–20", 0.0) + by_band.get("21–25", 0.0)), known, scale=100
            ),
        },
        "models": [
            {
                "model": s(r["model_name"]),
                "label": label(r["model_name"]),
                "units": f(r["units"]),
                "units_with_age": num(r["units_with_age"]),
                "median_age": num(r["median_age"]),
                "mean_age": num(r["mean_age"]),
                "under_26_pct": num(r["under_26_pct"]),
            }
            for _, r in per_model.iterrows()
        ],
        "cube": [
            {
                "band": s(r["age_band"]),
                "model": s(r["model_name"]),
                "colour": s(r["colour"]),
                "units": f(r["units"]),
            }
            for _, r in cube.iterrows()
        ],
    }


@router.get("/model-price")
def model_price() -> dict[str, Any]:
    """Price against sales per model: list price, realised price, discounts, units, revenue."""
    summary = mart("mart_ui_mc_model_price")
    monthly = mart("mart_ui_mc_model_price_monthly")
    if summary.empty:
        return {"models": [], "monthly": [], "bands": [], "totals": {}}
    names = all_model_names()
    label = {
        s(r["model_name"]): model_label(s(r["model_name"]), names) for _, r in summary.iterrows()
    }
    num = lambda v: f(v) if pd.notna(v) else None  # noqa: E731 - nullable float
    bands = summary.groupby("price_band", as_index=False).agg(
        models=("model_name", "size"), units=("units", "sum"), revenue_lkr=("revenue_lkr", "sum")
    )
    band_order = [b[1] for b in PRICE_BANDS]
    bands["order"] = bands["price_band"].map({b: i for i, b in enumerate(band_order)})
    total_units = float(summary["units"].sum())
    return {
        "totals": {
            "units": total_units,
            "revenue_lkr": f(summary["revenue_lkr"].sum()),
            "discounted_units": f(summary["discounted_units"].sum()),
            "avg_price": ratio(float(summary["revenue_lkr"].sum()), total_units),
            "date_from": s(summary["first_month"].min()),
            "date_to": s(summary["last_month"].max()),
        },
        "models": [
            {
                "model": s(r["model_name"]),
                "label": label[s(r["model_name"])],
                "motorcycle_type": s(r.get("motorcycle_type")) or None,
                "segment": s(r.get("segment")) or None,
                "cc": num(r.get("cc")),
                "list_price": f(r["list_price"]),
                "avg_price": f(r["avg_price"]),
                "min_price": f(r["min_price"]),
                "units": f(r["units"]),
                "unit_share_pct": f(r["unit_share_pct"]),
                "revenue_lkr": f(r["revenue_lkr"]),
                "revenue_share_pct": f(r["revenue_share_pct"]),
                "discounted_units": f(r["discounted_units"]),
                "discounted_pct": f(r["discounted_pct"]),
                "avg_discount": f(r["avg_discount"]),
                "units_per_month": f(r["units_per_month"]),
                "months_sold": i(r["months_sold"]),
                "price_band": s(r["price_band"]),
            }
            for _, r in summary.iterrows()
        ],
        "monthly": [
            {
                "model": s(r["model_name"]),
                "period": s(r["period"]),
                "units": f(r["units"]),
                "avg_price": f(r["avg_price"]),
                "discounted_units": f(r["discounted_units"]),
            }
            for _, r in monthly.sort_values(["model_name", "period"]).iterrows()
        ],
        "bands": [
            {
                "band": s(r["price_band"]),
                "models": i(r["models"]),
                "units": f(r["units"]),
                "unit_share_pct": ratio(float(r["units"]), total_units, scale=100),
                "revenue_lkr": f(r["revenue_lkr"]),
            }
            for _, r in bands.sort_values("order").iterrows()
        ],
    }


@router.get("/actual-model-colour")
def actual_model_colour(year: int) -> list[dict[str, Any]]:
    """Sold units per model, colour and month for one year — every sold unit.

    The closed months of the target allocation table show these actuals. Every model is
    returned, flagged ``is_active``, so the table's monthly total equals the units MC
    Analysis and MC Sales Forecast report; only active models get their own rows.
    """
    frame = _year_filter(mart("mart_ui_mc_model_colour_monthly"), year)
    if frame.empty:
        return []
    forecast = _forecast_rows()
    active: set[str] | None = None
    if not forecast.empty and "is_active" in forecast.columns:
        active = set(forecast.loc[forecast["is_active"].astype(bool), "model"].astype(str))
    names = all_model_names()
    return [
        {
            "period": s(row["month"]),
            "model": model_label(s(row["model_name"]), names),
            "color": s(row["colour"]),
            "units": i(row["units_sold"]),
            "is_active": active is None or s(row["model_name"]) in active,
        }
        for _, row in frame.iterrows()
        if f(row["units_sold"]) > 0
    ]


def _uio_group(models: pd.DataFrame, key: str) -> list[dict[str, Any]]:
    """Registered and estimated-in-operation units summed by one attribute."""
    frame = models.assign(**{key: models[key].fillna("Unknown").astype(str)})
    grouped = frame.groupby(key, as_index=False)[
        ["registered", "uio_base", "uio_low", "uio_high"]
    ].sum()
    total = float(grouped["uio_base"].sum()) or 1.0
    return [
        {
            "name": s(row[key]),
            "registered": f(row["registered"]),
            "uio": f(row["uio_base"]),
            "uio_low": f(row["uio_low"]),
            "uio_high": f(row["uio_high"]),
            "share_pct": ratio(row["uio_base"], total, scale=100),
        }
        for _, row in grouped.sort_values("uio_base", ascending=False).iterrows()
    ]


@router.get("/uio-snapshot")
def uio_snapshot() -> dict[str, Any]:
    """The fleet from Sales Summery: registrations since 2014 and the estimated parc today.

    Units in operation are Step 10's survival estimate for the latest year (base curve;
    the short- and long-life curves give the range). Only observed years are served —
    forward years depend on the registration forecast and are not part of a snapshot.
    """
    models = mart("mart_ui_uio_models")
    if models.empty:
        return {
            "as_of_year": None,
            "kpis": {},
            "series": [],
            "registrations": [],
            "by_family": [],
            "by_segment": [],
            "by_type": [],
            "by_status": [],
            "age": [],
            "colour": [],
            "models": [],
        }
    mcsi_names = model_names()
    as_of = i(models["as_of_year"].iloc[0])
    series = mart("mart_ui_parc_series")
    series = series[~series["is_forecast"].astype(bool)] if not series.empty else series
    registered = float(models["registered"].sum())
    uio = float(models["uio_base"].sum())
    active = models[models["status"].astype(str).str.lower() == "active"]
    weighted_age = (models["avg_age"].fillna(0) * models["uio_base"]).sum()
    first_year = int(mart("mart_ui_uio_registrations")["year"].min())
    return {
        "as_of_year": as_of,
        "first_year": first_year,
        "kpis": {
            "registered": registered,
            "uio": uio,
            "uio_low": f(models["uio_low"].sum()),
            "uio_high": f(models["uio_high"].sum()),
            "surviving_pct": ratio(uio, registered, scale=100),
            "active_uio_pct": ratio(float(active["uio_base"].sum()), uio, scale=100),
            "avg_age": ratio(float(weighted_age), uio),
            "models_total": int(len(models)),
            "models_active": int(len(active)),
            "models_in_parc": int((models["uio_base"] >= 1).sum()),
        },
        "series": [
            {
                "year": i(row["year"]),
                "new_sales": f(row["new_sales"]),
                "uio": f(row["uio_total"]),
                "uio_low": f(row["lower_80"]),
                "uio_high": f(row["upper_80"]),
                "attrition": f(row["attrition"]),
            }
            for _, row in series.sort_values("year").iterrows()
        ],
        "registrations": [
            {"year": i(r["year"]), "type": s(r["motorcycle_type"]), "units": f(r["units"])}
            for _, r in mart("mart_ui_uio_registrations").iterrows()
        ],
        "by_family": _uio_group(models, "family"),
        "by_segment": _uio_group(models, "segment"),
        "by_type": _uio_group(models, "motorcycle_type"),
        "by_status": _uio_group(models, "status"),
        "age": [
            {
                "bucket": s(r["age_bucket"]),
                "age_start": i(r["age_start"]),
                "type": s(r["motorcycle_type"]),
                "units": f(r["units"]),
            }
            for _, r in mart("mart_ui_uio_age").iterrows()
        ],
        "colour": [
            {"name": s(r["colour_family"]), "units": f(r["units"])}
            for _, r in mart("mart_ui_uio_colour").iterrows()
        ],
        "models": [
            {
                # MCSI's name where the model is still sold, else its dominant Sales Summery name.
                "model": model_label(
                    s(r["model_code"]),
                    {s(r["model_code"]): mcsi_names.get(s(r["model_code"])) or s(r["model_name"])},
                ),
                "family": s(r["family"]),
                "type": s(r["motorcycle_type"]),
                "segment": s(r["segment"]),
                "cc": f(r["cc"]) if pd.notna(r["cc"]) else None,
                "status": s(r["status"]),
                "first_year": i(r["first_year"]) if pd.notna(r["first_year"]) else None,
                "last_year": i(r["last_year"]) if pd.notna(r["last_year"]) else None,
                "registered": f(r["registered"]),
                "uio": f(r["uio_base"]),
                "uio_low": f(r["uio_low"]),
                "uio_high": f(r["uio_high"]),
                "surviving_pct": f(r["surviving_pct"]) if pd.notna(r["surviving_pct"]) else None,
                "avg_age": f(r["avg_age"]) if pd.notna(r["avg_age"]) else None,
            }
            for _, r in models.iterrows()
        ],
    }


@router.get("/uio-demand")
def uio_demand(min_demand: float = Query(0.0)) -> dict[str, Any]:
    """Parts demand attributable to the fleet, per part."""
    sku = mart("mart_ui_sku")
    parc = mart("mart_ui_parc_series")
    if sku.empty:
        return {
            "total_parts": 0,
            "parts_with_demand": 0,
            "projected_uio": 0.0,
            "supply_pct": 100.0,
            "lead_time_months": get_settings().lead_time_months,
            "sum_uio_demand_monthly": 0.0,
            "sum_uio_demand_leadtime": 0.0,
            "rows": [],
        }
    projected = (
        float(parc.loc[parc["is_forecast"], "uio_total"].iloc[0])
        if not parc.empty and not parc[parc["is_forecast"]].empty
        else 0.0
    )
    rows = sku[
        sku["mu_month_parc"].notna() & (sku["mu_month_parc"] > float(min_demand))
    ].sort_values("avg_monthly_demand", ascending=False)
    lead = (
        int(sku["lead_time_months"].max())
        if "lead_time_months" in sku.columns
        else get_settings().lead_time_months
    )
    return {
        "total_parts": int(len(sku)),
        "parts_with_demand": int(len(rows)),
        "projected_uio": projected,
        "supply_pct": 100.0,
        "lead_time_months": lead,
        "sum_uio_demand_monthly": float(rows["mu_month_parc"].sum()),
        "sum_uio_demand_leadtime": float(rows["mu_month_parc"].sum()) * lead,
        "rows": [
            {
                "material_9": s(row["material_9"]),
                "description": s(row["description"]),
                "compatible_models": s(row["compatible_models"]) or None,
                "model_count": len([m for m in s(row["compatible_models"]).split(",") if m]),
                "avg_monthly": f(row["avg_monthly_demand"]),
                "hist_months": i(row["total_months"]),
                "model_uio_total": projected,
                "replacement_freq_per_uio": ratio(row["mu_month_parc"], projected),
                "projected_uio": projected,
                "uio_demand_monthly": f(row["mu_month_parc"]),
                "uio_demand_leadtime": f(row["mu_month_parc"]) * lead,
                "supply_pct_applied": 100.0,
            }
            for _, row in rows.head(1000).iterrows()
        ],
    }


__all__ = ["router", "apply_filters"]
