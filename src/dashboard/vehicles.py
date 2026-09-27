"""Motorcycle marts: unit-sales EDA, the parc series and the registration forecast.

Two things are genuinely computed here rather than merely reshaped, and both are
computed here precisely so they are not computed in a request handler:

* **A monthly registration forecast.** Step 11 forecasts units per model for the next
  period as an annual figure. The dashboard plots a monthly series, so the annual figure
  is distributed across the next twelve months on each model's observed month-of-year
  profile, falling back to a flat split where there is not a full year of history.
* **The parc band.** The three survival scenarios become the low/high band on the
  units-in-operation series, which is the honest reading of them: the spread is the
  assumption's uncertainty, not a confidence interval from a fitted model.
"""

from __future__ import annotations

import pandas as pd

from src.core.errors import SourceDataError
from src.core.result import StageResult
from src.dashboard import unit_forecast
from src.dashboard.unit_forecast import horizon_after
from src.io.excel import read_source
from src.io.parquet import read_table, table_exists

#: Months of monthly registration forecast the dashboard plots.
FORECAST_HORIZON_MONTHS = 12

#: z for an 80% two-sided band, which is what the UI labels its ribbon.
Z80 = 1.2816

#: Years of parc projection the dashboard plots beyond the last observed year.
PARC_HORIZON_YEARS = 5


def _unit_sales() -> pd.DataFrame:
    """One row per VIN, from Step 09's ``unit_sales_vin``.

    Business meaning: a VIN whose SlsVolQty sums to 1 is one motorcycle sold; one that
    sums to 0 is one returned. A re-invoiced billing reversal therefore counts once, as
    sold — not as a return plus a second sale. Exceptions and placeholder VINs ("0")
    count as neither. Revenue is the VIN's net over all its rows.
    """
    frame = read_table("facts", "unit_sales_vin").copy()
    frame["month"] = frame["month"].astype(str)
    frame["year"] = pd.to_numeric(frame["year"], errors="coerce").fillna(0).astype(int)
    frame["net_sales"] = pd.to_numeric(frame["net_sales"], errors="coerce").fillna(0.0)
    frame["billing_reversals"] = (
        pd.to_numeric(frame["billing_reversals"], errors="coerce").fillna(0).astype(int)
    )
    if "colour" not in frame.columns:
        frame["colour"] = None
    for column in (
        "model_name",
        "colour",
        "province",
        "district",
        "rm",
        "ase",
        "dealer_name",
        "dealer_code",
    ):
        frame[column] = frame[column].fillna("Unknown").astype(str)
    frame["units"] = (frame["status"] == "sold").astype(float)
    frame["returned"] = (frame["status"] == "returned").astype(float)
    return frame


def model_names(frame: pd.DataFrame) -> pd.DataFrame:
    """Model code to MCSI model name: the name each code is most often recorded with.

    Business meaning: charts show "FZ FI V2 (B1N2)" instead of a bare type code. MCSI
    writes one code's name in more than one way now and then; the commonest wins.
    """
    if "model_description" not in frame.columns:
        return pd.DataFrame(columns=["model_name", "model_description"])
    names = frame[["model_name", "model_description"]].dropna()
    names = names[names["model_description"].astype(str).str.strip() != ""]
    if names.empty:
        return pd.DataFrame(columns=["model_name", "model_description"])
    counts = names.groupby(["model_name", "model_description"]).size().reset_index(name="n")
    counts = counts.sort_values(
        ["model_name", "n", "model_description"], ascending=[True, False, True]
    )
    return counts.drop_duplicates("model_name")[["model_name", "model_description"]]


#: Months of sales mix a unit target is split on.
MIX_WINDOW_MONTHS = 12


def recent_mix(frame: pd.DataFrame, months: int = MIX_WINDOW_MONTHS) -> pd.DataFrame:
    """Sold units per model and colour over the last ``months`` months with sales.

    Business meaning: a unit target is split to models and colours in the proportions
    they have actually sold in lately — the last twelve months, not the whole history,
    so a model launched this year or one being phased out carries today's weight.

    Args:
        frame: one row per VIN with ``month``, ``model_name``, ``colour``, ``units``.
        months: window length.

    Returns:
        ``model_name``, ``colour``, ``units``, ``window_start``, ``window_end``.
    """
    sold = frame[frame["units"] > 0]
    if sold.empty:
        return pd.DataFrame(columns=["model_name", "colour", "units", "window_start", "window_end"])
    window = sorted(sold["month"].unique())[-months:]
    mix = (
        sold[sold["month"].isin(window)]
        .groupby(["model_name", "colour"], as_index=False)["units"]
        .sum()
    )
    return mix.assign(window_start=window[0], window_end=window[-1])


def build_mcsi(result: StageResult) -> dict[str, pd.DataFrame]:
    """Unit-sales cuts, all filterable by year."""
    frame = _unit_sales()
    tables: dict[str, pd.DataFrame] = {}
    tables["mart_ui_mc_mix_12m"] = recent_mix(frame)

    def cut(keys: list[str], name: str) -> None:
        out = frame.groupby(["year", *keys], as_index=False, dropna=False).agg(
            units_sold=("units", "sum"),
            returned=("returned", "sum"),
            revenue_lkr=("net_sales", "sum"),
            vins=("vin", "nunique"),
            dealers=("dealer_name", "nunique"),
        )
        tables[name] = out

    cut(["month"], "mart_ui_mc_monthly")
    # Sold units per model, colour and month: the actuals beside a monthly target allocation.
    cut(["month", "model_name", "colour"], "mart_ui_mc_model_colour_monthly")
    cut(["model_name"], "mart_ui_mc_by_model")
    cut(["province"], "mart_ui_mc_by_province")
    cut(["province", "district"], "mart_ui_mc_by_district")
    cut(["rm"], "mart_ui_mc_by_rm")
    cut(["ase", "rm"], "mart_ui_mc_by_ase")
    cut(["dealer_code", "dealer_name", "province", "district", "rm", "ase"], "mart_ui_mc_by_dealer")
    cut(["model_name", "colour"], "mart_ui_mc_by_model_colour")

    # Colour at each level of the sales hierarchy: by colour, and by "model – colour",
    # in the entity x column shape the geography crosstabs already read.
    combo = frame["model_name"] + " – " + frame["colour"]
    for level in ("rm", "ase", "province", "district"):
        for name, column in (("color", frame["colour"]), ("model_color", combo)):
            tables[f"mart_ui_mc_matrix_{name}_{level}"] = (
                frame.assign(model_name=column)
                .groupby(["year", level, "model_name"], as_index=False, dropna=False)
                .agg(units_sold=("units", "sum"))
            )

    # Entity x model matrices, so the UI's crosstabs need no pivoting server-side.
    for level, keys in (
        ("dealer", ["dealer_code", "dealer_name", "province", "rm", "ase"]),
        ("rm", ["rm"]),
        ("ase", ["ase"]),
        ("province", ["province"]),
        ("district", ["district"]),
    ):
        tables[f"mart_ui_mc_matrix_{level}"] = frame.groupby(
            ["year", *keys, "model_name"], as_index=False, dropna=False
        ).agg(units_sold=("units", "sum"))

    kpis = pd.DataFrame(
        [
            {
                "total_vins": int((frame["status"] != "no_vin").sum()),
                "sold": float(frame["units"].sum()),
                "returned": float(frame["returned"].sum()),
                # Reversal rows (SlsVolQty -1) and the VINs re-invoiced after one: shown
                # beside the returns, never counted as returns.
                "billing_reversals": int(frame["billing_reversals"].sum()),
                "rebilled_vins": int(
                    ((frame["billing_reversals"] > 0) & (frame["status"] == "sold")).sum()
                ),
                "no_vin_rows": int((frame["status"] == "no_vin").sum()),
                "total_revenue_lkr": float(frame["net_sales"].sum()),
                "active_provinces": int(
                    frame.loc[frame["province"] != "Unknown", "province"].nunique()
                ),
                "active_dealers": int(frame["dealer_name"].nunique()),
                "models_sold": int(frame["model_name"].nunique()),
                "date_from": str(frame["month"].min()),
                "date_to": str(frame["month"].max()),
                "months_of_data": int(frame["month"].nunique()),
                "office_leak_rows": int(
                    frame["geography_is_office_leak"].fillna(False).astype(bool).sum()
                ),
            }
        ]
    )
    tables["mart_ui_mc_kpis"] = kpis
    tables["mart_ui_mc_model_names"] = model_names(frame)

    result.warn(
        f"motorcycle cuts: {kpis.at[0, 'total_vins']:,} VINs, {kpis.at[0, 'sold']:,.0f} units, "
        f"{kpis.at[0, 'total_revenue_lkr']:,.0f} LKR over {kpis.at[0, 'months_of_data']} month(s); "
        f"{int((frame['colour'] != 'Unknown').sum()):,} VIN(s) carry a colour "
        f"({frame.loc[frame['colour'] != 'Unknown', 'colour'].nunique()} distinct)"
    )
    return tables


#: Sales Summery Model Classification status that marks a model still on sale.
ACTIVE_STATUS = "active"


def active_model_codes(classification: pd.DataFrame) -> set[str]:
    """Model codes Sales Summery's Model Classification sheet marks Active.

    Business meaning: an active model is one AMW still sells; the model-level sales
    forecast is shown for these, not for models that have left the range.
    """
    frame = classification.rename(columns=lambda c: str(c).strip())
    if not {"Model", "Status"} <= set(frame.columns):
        return set()
    status = frame["Status"].astype(str).str.strip().str.lower()
    codes = frame.loc[status == ACTIVE_STATUS, "Model"].astype(str).str.strip()
    return {c for c in codes if c.lower() not in ("", "nan", BLANK_MODEL_NAME)}


def model_families(classification: pd.DataFrame) -> dict[str, str]:
    """Model code -> model family (RAY, FZ, MT, …) from the Model Classification sheet."""
    frame = classification.rename(columns=lambda c: str(c).strip())
    if not {"Model", "Model Family"} <= set(frame.columns):
        return {}
    pairs = frame.assign(
        Model=frame["Model"].astype(str).str.strip(),
        family=frame["Model Family"].astype(str).str.strip(),
    ).drop_duplicates("Model")
    return {
        code: family
        for code, family in zip(pairs["Model"], pairs["family"], strict=False)
        if code.lower() not in ("", "nan", BLANK_MODEL_NAME) and family.lower() not in ("", "nan")
    }


def build_sales_forecast(result: StageResult) -> dict[str, pd.DataFrame]:
    """Monthly registration forecast per active model, and the total it adds up to.

    Business meaning: how many motorcycles are expected to sell each month. One method —
    the one the rolling backtest selected (``unit_forecast.RECOMMENDED``) — produces every
    forecast number the MC Sales Forecast page shows, so the page cannot contradict
    itself: the total is the sum of the model forecasts, and the 80% band is what this
    method has actually missed by in the backtest, at total and at model level.

    Only models Sales Summery's Model Classification marks Active get a forecast; an
    inactive model keeps its history but contributes no new units (Step 11).

    Returns:
        ``mart_ui_mc_sales_forecast`` (per model and month) and
        ``mart_ui_mc_sales_forecast_total`` (active models summed, with a total band).
    """
    frame = _unit_sales()
    actual = frame.groupby(["month", "model_name"], as_index=False)["units"].sum()
    actual = actual.rename(
        columns={"month": "period", "model_name": "model", "units": "actual_units"}
    )
    actual["period"] = actual["period"].astype(str)
    actual["model"] = actual["model"].astype(str)

    try:
        classification = read_source("sales_summery__model_classification")
    except SourceDataError as exc:
        classification = pd.DataFrame()
        result.warn(f"Model Classification sheet unreadable, no model marked active: {exc}")
    active = active_model_codes(classification)
    families = model_families(classification)

    horizon = horizon_after(str(actual["period"].max()), FORECAST_HORIZON_MONTHS)
    train = actual[actual["model"].isin(active)]
    points = unit_forecast.family_growth(train, families, horizon)
    bands = unit_forecast.band_ratios(train, families)

    rows: list[dict[str, object]] = [
        {
            "period": row.period,
            "model": row.model,
            "actual_units": float(row.actual_units),
            "forecast_units": float(row.actual_units),
            "lower_80": float(row.actual_units),
            "upper_80": float(row.actual_units),
            "is_forecast": False,
        }
        for row in actual.itertuples(index=False)
    ]
    for model, values in points.items():
        for step, (period, point) in enumerate(zip(horizon, values, strict=True), start=1):
            low, high = unit_forecast.band_at(bands["model"], step)
            rows.append(
                {
                    "period": period,
                    "model": model,
                    "actual_units": None,
                    "forecast_units": point,
                    "lower_80": point * min(low, 1.0),
                    "upper_80": point * max(high, 1.0),
                    "is_forecast": True,
                }
            )

    out = pd.DataFrame(rows).sort_values(["model", "period"]).reset_index(drop=True)
    out["is_active"] = out["model"].isin(active)
    out["family"] = out["model"].map(families)
    # Months with a registration, so a model launched last month is visibly thin.
    history = actual[actual["actual_units"] > 0].groupby("model")["period"].nunique()
    out["history_months"] = out["model"].map(history).fillna(0).astype(int)
    out["method"] = unit_forecast.GROWTH_METHOD[1]

    # The total: active models summed; its band comes from total-level backtest misses,
    # which are narrower than adding up every model's band would suggest.
    live = out[out["is_active"]]
    total = live.groupby(["period", "is_forecast"], as_index=False).agg(
        actual_units=("actual_units", "sum"), forecast_units=("forecast_units", "sum")
    )
    total.loc[total["is_forecast"], "actual_units"] = None
    step_of = {period: i for i, period in enumerate(horizon, start=1)}
    low_high = [
        unit_forecast.band_at(bands["total"], step_of[p]) if f else (1.0, 1.0)
        for p, f in zip(total["period"], total["is_forecast"], strict=True)
    ]
    total["lower_80"] = [
        v * min(lo, 1.0) for v, (lo, _) in zip(total["forecast_units"], low_high, strict=True)
    ]
    total["upper_80"] = [
        v * max(hi, 1.0) for v, (_, hi) in zip(total["forecast_units"], low_high, strict=True)
    ]
    total["method"] = unit_forecast.GROWTH_METHOD[1]
    total = total.sort_values("period").reset_index(drop=True)

    inactive = sorted(set(out.loc[~out["is_active"], "model"]))
    if inactive:
        result.warn(f"sales forecast: not Active in Model Classification, history only: {inactive}")
    scored = sorted(bands["total"])
    scored_range = f"{scored[0]}–{scored[-1]}" if scored else "none"
    result.warn(
        f"monthly registration forecast ({unit_forecast.GROWTH_METHOD[1]}): "
        f"{len(points)} active model(s), {FORECAST_HORIZON_MONTHS} months from {horizon[0]}, "
        f"{total.loc[total['is_forecast'], 'forecast_units'].sum():,.0f} units; 80% band from "
        f"backtest misses at horizons {scored_range}, "
        f"widened by assumption beyond"
    )
    return {"mart_ui_mc_sales_forecast": out, "mart_ui_mc_sales_forecast_total": total}


#: Sales Summery "All Years" sheet: the registration units column.
REGISTRATION_UNITS = "Vehicle Units (ZVOR)"


def _age_start(bucket: str) -> int:
    """Sort key for "0-1", "1-2", … "15+"."""
    return int(str(bucket).split("-")[0].rstrip("+") or 0)


def build_uio_snapshot(result: StageResult) -> dict[str, pd.DataFrame]:
    """The fleet as Sales Summery records it: registrations, and how many are still running.

    Business meaning: every motorcycle Sales Summery registered from 2014 on, and Step
    10's estimate of how many are still on the road in the latest year — the base
    survival curve, with the short- and long-life curves as the range, since no
    de-registration records exist. The import-ban years (2022–2024) are genuinely zero
    and are published as zeros, never interpolated.

    Returns:
        ``mart_ui_uio_models`` (one row per model code), ``mart_ui_uio_registrations``
        (year × motorcycle type, zeros included), ``mart_ui_uio_age`` (latest-year fleet
        by age bucket and type) and ``mart_ui_uio_colour`` (registrations by colour family).
    """
    classification = read_source("sales_summery__model_classification").rename(
        columns=lambda c: str(c).strip()
    )
    registrations = read_source("sales_summery__all_years").rename(columns=lambda c: str(c).strip())
    registrations = registrations[
        pd.to_numeric(registrations["Year"], errors="coerce").notna()
    ].copy()
    registrations["year"] = pd.to_numeric(registrations["Year"]).astype(int)
    registrations["units"] = pd.to_numeric(
        registrations[REGISTRATION_UNITS], errors="coerce"
    ).fillna(0.0)
    # A row with no model code (FASINO S 125) is the "(blank)" code in Model Classification.
    registrations["model_code"] = (
        registrations["Model"].fillna(BLANK_MODEL_NAME).astype(str).str.strip()
    )

    # A code can carry several names in Sales Summery (27 of 83 do — B622 is 41k RAY-ZR
    # units and one "ALPHA (Disk)"), so each code takes the name, family, type, segment
    # and cc it was mostly registered under, never simply the first row.
    labels = ["Model Name", "Model Family", "Motorcycle Type", "Segment", "cc"]
    weighted = (
        registrations.assign(**{c: registrations[c].astype(str).str.strip() for c in labels[:-1]})
        .groupby(["model_code", *labels], as_index=False, dropna=False)["units"]
        .sum()
        .sort_values(["model_code", "units"], ascending=[True, False])
        .drop_duplicates("model_code")
    )
    sold = registrations[registrations["units"] > 0].groupby("model_code")["year"]
    attributes = weighted.rename(
        columns={
            "Model Name": "model_name",
            "Model Family": "family",
            "Motorcycle Type": "motorcycle_type",
            "Segment": "segment",
        }
    )[["model_code", "model_name", "family", "motorcycle_type", "segment", "cc"]]
    attributes["cc"] = pd.to_numeric(attributes["cc"], errors="coerce")
    # Active per Model Classification — the same rule as the MC pages; the code-less
    # FASINO S 125 row ("(blank)") is included as the sheet records it.
    status = classification["Status"].astype(str).str.strip().str.lower()
    active_codes = set(classification.loc[status == ACTIVE_STATUS, "Model"].astype(str).str.strip())
    attributes["status"] = [
        "Active" if code in active_codes else "Inactive" for code in attributes["model_code"]
    ]
    attributes["first_year"] = attributes["model_code"].map(sold.min())
    attributes["last_year"] = attributes["model_code"].map(sold.max())
    renamed = sorted(
        set(registrations.groupby("model_code")["Model Name"].nunique().loc[lambda x: x > 1].index)
    )
    if renamed:
        result.warn(
            f"UIO snapshot: {len(renamed)} model code(s) carry several names in Sales Summery; "
            f"each is labelled by the name most of its units were registered under"
        )

    stacked = read_table("facts", "uio_age_matrix")
    latest = int(stacked["year"].max())
    now = stacked[stacked["year"] == latest].rename(columns={"enterprise_model_id": "model_code"})
    uio = now.pivot_table(
        index="model_code", columns="scenario", values="units", aggfunc="sum", fill_value=0.0
    ).rename(columns={"base": "uio_base", "short_life": "uio_low", "long_life": "uio_high"})
    base = now[now["scenario"] == "base"]
    age = (base["age"] * base["units"]).groupby(base["model_code"]).sum() / base.groupby(
        "model_code"
    )["units"].sum()

    models = attributes.merge(
        registrations.groupby("model_code", as_index=False)["units"]
        .sum()
        .rename(columns={"units": "registered"}),
        on="model_code",
        how="outer",
    )
    models = models.merge(uio.reset_index(), on="model_code", how="left")
    models["avg_age"] = models["model_code"].map(age)
    for column in ("registered", "uio_base", "uio_low", "uio_high"):
        if column not in models.columns:
            models[column] = 0.0
        models[column] = models[column].fillna(0.0)
    models["surviving_pct"] = (
        models["uio_base"] / models["registered"].where(models["registered"] > 0)
    ) * 100.0
    models["as_of_year"] = latest
    models = models.sort_values("uio_base", ascending=False).reset_index(drop=True)

    # All Years carries each row's own Motorcycle Type; use it as recorded.
    typed = registrations.assign(
        motorcycle_type=registrations["Motorcycle Type"].fillna("Unknown").astype(str).str.strip()
    )
    by_year = typed.groupby(["year", "motorcycle_type"], as_index=False)["units"].sum()
    # The import ban: years with no registrations are published as explicit zeros.
    years = range(int(by_year["year"].min()), latest + 1)
    grid = pd.MultiIndex.from_product(
        [years, sorted(by_year["motorcycle_type"].dropna().unique())],
        names=["year", "motorcycle_type"],
    )
    by_year = (
        by_year.set_index(["year", "motorcycle_type"]).reindex(grid, fill_value=0.0).reset_index()
    )

    age_table = (
        base.merge(attributes[["model_code", "motorcycle_type"]], on="model_code", how="left")
        .groupby(["age_bucket", "motorcycle_type"], as_index=False, dropna=False)["units"]
        .sum()
    )
    age_table["age_start"] = age_table["age_bucket"].map(_age_start)
    age_table = age_table.sort_values(["age_start", "motorcycle_type"]).reset_index(drop=True)

    colour = (
        registrations.assign(colour_family=registrations["Color Family"].fillna("Unknown"))
        .groupby("colour_family", as_index=False)["units"]
        .sum()
        .query("units > 0")
        .sort_values("units", ascending=False)
    )

    missing = sorted(set(models.loc[models["family"].isna(), "model_code"]))
    if missing:
        result.warn(f"UIO snapshot: codes registered but not in Model Classification: {missing}")
    result.warn(
        f"UIO snapshot {latest}: {models['registered'].sum():,.0f} registered since "
        f"{min(years)}, {models['uio_base'].sum():,.0f} estimated in operation "
        f"({models['uio_low'].sum():,.0f}–{models['uio_high'].sum():,.0f} across survival curves)"
    )
    return {
        "mart_ui_uio_models": models,
        "mart_ui_uio_registrations": by_year,
        "mart_ui_uio_age": age_table,
        "mart_ui_uio_colour": colour,
    }


def _age_forward(
    by_age: dict[int, float], survival: pd.Series, additions: float, years: int
) -> list[float]:
    """Roll a fleet forward, retiring each cohort at its own conditional survival rate.

    ``survival[a]`` is the probability a vehicle alive at age ``a`` is still on the road
    at ``a + 1``. Each step ages every cohort, then admits one year of new registrations
    at age zero.
    """
    fleet = dict(by_age)
    totals: list[float] = []
    for _ in range(years):
        aged: dict[int, float] = {}
        for age, units in fleet.items():
            rate = float(survival.get(age, survival.iloc[-1] if len(survival) else 0.0))
            aged[age + 1] = aged.get(age + 1, 0.0) + units * rate
        aged[0] = additions
        fleet = aged
        totals.append(float(sum(fleet.values())))
    return totals


#: Sales Summery writes this where a model has no name on the "All Years" sheet.
BLANK_MODEL_NAME = "(blank)"


def fill_blank_model_names(
    matrix: pd.DataFrame, classification: pd.DataFrame, result: StageResult
) -> pd.DataFrame:
    """Name the parc models the "All Years" sheet leaves as ``(blank)``.

    Business meaning: Sales Summery's "All Years" sheet blanks the name of some codes
    (2GS2, 2NC1) that its "Model Classification" sheet does name (FZ-S VER 2.0, RAY Z).
    The code is the identity either way; this only puts a readable name beside it.

    Args:
        matrix: parc rows with ``model_code`` and ``model_name``.
        classification: the Model Classification sheet (``Model``, ``Model Name``).
        result: collects a warning for every code still unnamed.

    Returns:
        A copy of ``matrix`` with blank names filled where the classification has one.
    """
    names = classification.rename(columns=lambda c: str(c).strip())
    if not {"Model", "Model Name"} <= set(names.columns):
        return matrix
    names = names.assign(
        Model=names["Model"].astype(str).str.strip(),
        name=names["Model Name"].astype(str).str.strip(),
    )
    names = names[~names["name"].isin(["", "nan", BLANK_MODEL_NAME])]
    lookup = names.drop_duplicates("Model", keep="last").set_index("Model")["name"]
    out = matrix.copy()
    blank = out["model_name"].astype(str).str.strip().isin(["", "nan", BLANK_MODEL_NAME])
    out.loc[blank, "model_name"] = out.loc[blank, "model_code"].astype(str).map(lookup)
    still = out["model_name"].isna()
    out.loc[still, "model_name"] = BLANK_MODEL_NAME
    filled = sorted(set(out.loc[blank & ~still, "model_code"].astype(str)))
    if filled:
        result.warn(f"parc model names filled from Model Classification for {filled}")
    if still.any():
        result.warn(
            f"parc model code(s) with no name anywhere in Sales Summery: "
            f"{sorted(set(out.loc[still, 'model_code'].astype(str)))} — shown by code"
        )
    return out


def build_parc(result: StageResult) -> dict[str, pd.DataFrame]:
    """The units-in-operation series, its scenario band, and the age distribution.

    Observed years come straight from Step 10. Forward years are the observed age profile
    rolled on with the published conditional-survival curve, admitting Step 11's unit
    forecast as each new cohort. The band is the short-life and long-life survival runs —
    an assumption's spread, not a fitted confidence interval.

    Step 11's ``scenario_uio`` is deliberately *not* used for the total: it projects only
    the incremental cohort under a unit-target shift, so summing it would report a parc
    of one year's registrations and wipe a decade of fleet off the chart.
    """
    tables: dict[str, pd.DataFrame] = {}

    totals = read_table("facts", "uio_totals_by_scenario").sort_values("year")
    # The age matrix stacks every survival scenario, so a plain sum counts the fleet
    # three times over. The centre case is the base arm; the band comes from `totals`.
    stacked = read_table("facts", "uio_age_matrix")
    matrix = stacked[stacked["scenario"] == "base"] if "scenario" in stacked.columns else stacked
    curves = (
        read_table("facts", "survival_curves")
        if table_exists("facts", "survival_curves")
        else pd.DataFrame(columns=["scenario", "age", "conditional_survival"])
    )

    new_units = (
        matrix[matrix["age"] == 0]
        .groupby("year", as_index=False)["units"]
        .sum()
        .rename(columns={"units": "new_sales"})
    )

    history = totals.merge(new_units, on="year", how="left")
    history["new_sales"] = history["new_sales"].fillna(0.0)
    history["uio_total"] = history["base"]
    history["lower_80"] = history["short_life"]
    history["upper_80"] = history["long_life"]
    history["is_forecast"] = False

    columns = ["year", "new_sales", "uio_total", "lower_80", "upper_80", "is_forecast"]
    latest_year = int(matrix["year"].max())
    profile = (
        matrix[matrix["year"] == latest_year]
        .groupby("age", as_index=False)["units"]
        .sum()
        .set_index("age")["units"]
        .to_dict()
    )
    registrations = (
        read_table("facts", "registration_forecast")
        if table_exists("facts", "registration_forecast")
        else pd.DataFrame(columns=["forecast_units"])
    )
    additions = float(
        pd.to_numeric(registrations.get("forecast_units", pd.Series(dtype=float)), errors="coerce")
        .fillna(0.0)
        .sum()
    )

    projected: dict[str, list[float]] = {}
    for arm in ("base", "short_life", "long_life"):
        arm_curve = curves[curves["scenario"] == arm].sort_values("age")
        rates = (
            arm_curve.set_index("age")["conditional_survival"]
            if not arm_curve.empty
            else pd.Series(dtype=float)
        )
        projected[arm] = _age_forward(profile, rates, additions, PARC_HORIZON_YEARS)

    forward_rows = pd.DataFrame(
        {
            "year": [latest_year + i + 1 for i in range(PARC_HORIZON_YEARS)],
            "new_sales": [additions] * PARC_HORIZON_YEARS,
            "uio_total": projected["base"],
            "lower_80": projected["short_life"],
            "upper_80": projected["long_life"],
            "is_forecast": True,
        }
    )

    series = pd.concat([history[columns], forward_rows[columns]], ignore_index=True).sort_values(
        "year"
    )
    # Attrition is what the fleet lost: last year's parc plus this year's additions, less
    # what is actually still on the road.
    series["attrition"] = (
        series["uio_total"].shift(1).fillna(0.0) + series["new_sales"] - series["uio_total"]
    ).clip(lower=0.0)
    series["period"] = series["year"].astype(int).astype(str)
    tables["mart_ui_parc_series"] = series[["period", *columns, "attrition"]]

    # Per model, the observed parc plus each model's share of the projected total. The
    # share is held at its latest observed value: nothing in the sources says the mix
    # shifts, and inventing a drift would put a trend on the chart that no data supports.
    # Keyed on the model code (Sales Summery "Model"), with its name beside it: several codes
    # share a name (FASCINO has four), and the pages label every model "Name (Code)".
    matrix = matrix.rename(columns={"enterprise_model_id": "model_code"})
    try:
        classification = read_source("sales_summery__model_classification")
    except SourceDataError as exc:
        result.warn(f"Model Classification sheet unreadable, blank names stay blank: {exc}")
    else:
        matrix = fill_blank_model_names(matrix, classification, result)
    by_model = matrix.groupby(["year", "model_code", "model_name"], as_index=False)["units"].sum()
    by_model["is_forecast"] = False
    latest_mix = by_model[by_model["year"] == latest_year].copy()
    mix_total = float(latest_mix["units"].sum()) or 1.0
    latest_mix["share"] = latest_mix["units"] / mix_total
    forward_model = pd.concat(
        [
            latest_mix.assign(
                year=int(row.year),
                units=lambda d, t=float(row.uio_total): d["share"] * t,
                is_forecast=True,
            )[["year", "model_code", "model_name", "units", "is_forecast"]]
            for row in forward_rows.itertuples()
        ],
        ignore_index=True,
    )
    tables["mart_ui_parc_by_model"] = pd.concat(
        [by_model, forward_model], ignore_index=True
    ).rename(columns={"units": "uio_forecast"})

    latest = int(matrix["year"].max())
    current = matrix[matrix["year"] == latest]
    fleet = float(current["units"].sum()) or 1.0
    age = (
        current.groupby(["model_code", "model_name", "age_bucket"], as_index=False)["units"]
        .sum()
        .rename(
            columns={"model_name": "model", "age_bucket": "age_cohort", "units": "vehicle_count"}
        )
    )
    age["pct_of_fleet"] = age["vehicle_count"] / fleet * 100.0
    tables["mart_ui_parc_age"] = age

    result.warn(
        f"parc series: {len(series)} year(s), {int(series['is_forecast'].sum())} forecast "
        f"(forward years come from the unit-target scenarios; base is their midpoint); "
        f"age distribution taken at {latest} across {age['model'].nunique()} model(s)"
    )
    return tables
