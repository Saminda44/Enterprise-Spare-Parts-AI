"""Rebuild billing-derived Sales Summery tabs from the accepted MCSI source."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.core.errors import SourceDataError

BILLING_BASIS = "Billing (net of cancellations)"
MODEL_FIELDS = ("Status", "Model Family", "Motorcycle Type", "Segment", "cc")
COLOR_FIELDS = ("Color", "Abbreviation", "Color Code", "Color Family")


@dataclass
class SummaryResult:
    """Updated sheets and counts needing classification review."""

    sheets: dict[str, pd.DataFrame]
    unknown_models: int
    unknown_colors: int


def _text(value: object) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _pivot(rows: pd.DataFrame, indexes: list[str], years: list[str], columns: list[str]) -> pd.DataFrame:
    result = rows.pivot_table(
        index=indexes, columns="Year", values="Vehicle Units (ZVOR)",
        aggfunc="sum", fill_value=0, dropna=False,
    ).reset_index()
    result.columns = [str(column) for column in result.columns]
    for year in years:
        if year not in result:
            result[year] = 0
    result["Total"] = result[years].sum(axis=1)
    return result.reindex(columns=columns)


def rebuild_sales_summary(
    current: dict[str, pd.DataFrame], mcsi: pd.DataFrame,
) -> SummaryResult:
    """Replace 2025+ billing views, retaining historical years and curated mappings.

    Business meaning: MCSI's signed SlsVolQty is the source of vehicle units in
    billing years. Pre-2025 order-export history and human model/color metadata stay
    untouched. Unmapped models and colors are visible as blanks for review.
    """
    required = {"All Years", "Summary", "Model Classification", "Color Master"}
    missing = required - current.keys()
    if missing:
        raise SourceDataError(f"Sales_Summery missing sheets: {', '.join(sorted(missing))}")
    fields = {"Year", "Model", "Model Name", "Color", "SlsVolQty", "Net Sales"}
    missing_fields = fields - set(mcsi)
    if missing_fields:
        raise SourceDataError(f"MCSI missing summary columns: {', '.join(sorted(missing_fields))}")
    source = mcsi.copy()
    source["Year"] = pd.to_numeric(source["Year"], errors="coerce")
    source = source[source["Year"].ge(2025)].copy()
    if source.empty:
        raise SourceDataError("MCSI has no billing rows from 2025 onward")
    source["SlsVolQty"] = pd.to_numeric(source["SlsVolQty"], errors="coerce")
    if source["SlsVolQty"].isna().any():
        raise SourceDataError("MCSI contains nonnumeric SlsVolQty in billing years")
    source["Net Sales"] = pd.to_numeric(source["Net Sales"], errors="coerce")
    for field in ("Model", "Model Name", "Color"):
        source[field] = source[field].map(_text)
    grouped = source.groupby(["Year", "Model", "Model Name", "Color"], dropna=False).agg(
        Units=("SlsVolQty", "sum"), Net_Value=("Net Sales", "sum")
    ).reset_index()

    classification = current["Model Classification"].copy()
    classification["_model"] = classification["Model"].map(_text)
    classification["_name"] = classification["Model Name"].map(_text)
    by_pair = classification.drop_duplicates(["_model", "_name"]).set_index(["_model", "_name"])
    by_code = classification.drop_duplicates("_model").set_index("_model")
    colors = current["Color Master"].copy()
    colors["_color"] = colors["Color (as in data)"].map(_text)
    by_color = colors.drop_duplicates("_color").set_index("_color")
    records: list[dict[str, object]] = []
    unknown_models: set[tuple[str, str]] = set()
    unknown_colors: set[str] = set()
    for year, model, name, color, units, _net_value in grouped.itertuples(index=False, name=None):
        key = (model, name)
        if key in by_pair.index:
            meta = by_pair.loc[key]
        elif model and model in by_code.index:
            meta = by_code.loc[model]
        else:
            meta = None
            unknown_models.add(key)
        color_meta = by_color.loc[color] if color in by_color.index else None
        if color_meta is None:
            unknown_colors.add(color)
        record: dict[str, object] = {
            "Year": str(int(year)), "Model": model or None, "Model Name": name or None,
            "Color (SAP)": color or None,
            "Color (Correct)": color_meta["Color"] if color_meta is not None else None,
            "Vehicle Units (ZVOR)": units, "Basis": BILLING_BASIS,
        }
        for field in MODEL_FIELDS:
            record[field] = meta[field] if meta is not None else None
        for field in COLOR_FIELDS[1:]:
            record[field] = color_meta[field] if color_meta is not None else None
        record["Last Year Sold"] = int(year)
        records.append(record)

    all_years = current["All Years"]
    historical = all_years[
        ~all_years["Year"].astype(str).str.fullmatch(r"20(?:2[5-9]|[3-9]\d)")
        & all_years["Year"].astype(str).ne("TOTAL")
    ].copy()
    billing = pd.DataFrame.from_records(records).reindex(columns=all_years.columns)
    joined = pd.concat([historical, billing], ignore_index=True)
    total = {column: None for column in all_years.columns}
    total["Year"] = "TOTAL"
    for column in ("Vehicle Units (ZVOR)", "Net Value (ZVOR)", "Gross Sell.Pr (ZVOR)",
                   "Discount (ZVOR)", "All Order Lines"):
        total[column] = pd.to_numeric(joined[column], errors="coerce").sum()
    joined = pd.concat([joined, pd.DataFrame([total])], ignore_index=True)
    output = dict(current)
    output["All Years"] = joined
    years = sorted(billing["Year"].unique())
    for year in years:
        rows = billing[billing["Year"].eq(year)].copy()
        frame = pd.DataFrame({
            "Model": rows["Model"], "Model Name": rows["Model Name"],
            **{field: rows[field] for field in MODEL_FIELDS},
            "Color": rows["Color (Correct)"],
            "Abbreviation": rows["Abbreviation"], "Color Code": rows["Color Code"],
            "Color Family": rows["Color Family"], "Units": rows["Vehicle Units (ZVOR)"],
        })
        frame = frame.reindex(columns=current[year].columns if year in current else frame.columns)
        total_row = {column: None for column in frame}
        total_row["Units"] = frame["Units"].sum()
        output[year] = pd.concat([frame, pd.DataFrame([total_row])], ignore_index=True)

    summary = current["Summary"]
    summary_old = summary[
        ~summary["Year sheet"].astype(str).isin([*years, "TOTAL"])
    ].copy()
    summary_rows = []
    for year in years:
        subset = source[source["Year"].eq(int(year))]
        groups = grouped[grouped["Year"].eq(int(year))]
        summary_rows.append({
            "Year sheet": int(year), "Basis": BILLING_BASIS,
            "Source rows": len(subset), "Vehicle Units": subset["SlsVolQty"].sum(),
            "Net Value": subset["Net Sales"].sum(),
            "Model x Name x Color rows": len(groups),
            "Distinct Models (4-char)": subset["Model"].replace("", pd.NA).nunique(),
            "Distinct Model Names": subset["Model Name"].replace("", pd.NA).nunique(),
            "Distinct Colors": subset["Color"].replace("", pd.NA).nunique(),
        })
    summary_data = pd.concat([summary_old, pd.DataFrame(summary_rows)], ignore_index=True)
    summary_total = {column: None for column in summary.columns}
    summary_total["Year sheet"] = "TOTAL"
    for column in ("Source rows", "Vehicle Units", "Net Value", "Other order lines",
                   "Model x Name x Color rows"):
        summary_total[column] = pd.to_numeric(summary_data[column], errors="coerce").sum()
    output["Summary"] = pd.concat([
        summary_data.reindex(columns=summary.columns),
        pd.DataFrame([summary_total]).reindex(columns=summary.columns),
    ], ignore_index=True)

    classification_out = current["Model Classification"].copy()
    classified_rows = joined[joined["Year"].ne("TOTAL")].copy()
    classified_rows["_model"] = classified_rows["Model"].map(_text)
    classified_rows["_name"] = classified_rows["Model Name"].map(_text)
    classified_rows["_year"] = pd.to_numeric(classified_rows["Year"], errors="coerce")
    totals = classified_rows.groupby(["_model", "_name"], dropna=False).agg(
        total=("Vehicle Units (ZVOR)", "sum"), first=("_year", "min"), last=("_year", "max")
    )
    known_pairs = set(zip(classification_out["Model"].map(_text),
                          classification_out["Model Name"].map(_text), strict=True))
    new_classifications = []
    for (model, model_name), values in totals.iterrows():
        match = classification_out["Model"].map(_text).eq(model) & (
            classification_out["Model Name"].map(_text).eq(model_name)
        )
        if match.any():
            classification_out.loc[match, "Total Units"] = values["total"]
            classification_out.loc[match, "First Year Sold"] = values["first"]
            classification_out.loc[match, "Last Year Sold"] = values["last"]
        elif (model, model_name) not in known_pairs and (model, model_name) in unknown_models:
            new_classifications.append({
                "Model": model or None, "Model Name": model_name or None,
                "Status": "Review", "First Year Sold": values["first"],
                "Last Year Sold": values["last"], "Total Units": values["total"],
                "Source": "MCSI upload; classification required",
            })
    if new_classifications:
        classification_out = pd.concat([
            classification_out,
            pd.DataFrame(new_classifications).reindex(columns=classification_out.columns),
        ], ignore_index=True)
    output["Model Classification"] = classification_out

    pivot_rows = joined[joined["Year"].ne("TOTAL")]
    all_year_labels = sorted({
        *(str(column) for column in current["Type x Year"].columns if str(column).isdigit()),
        *years,
    })
    for sheet, indexes in (
        ("Type x Year", ["Motorcycle Type"]),
        ("Segment x Year", ["Motorcycle Type", "Segment"]),
        ("Model Family x Year", ["Model Family"]),
        ("Status x Year", ["Status", "Model Family"]),
    ):
        columns = [column for column in current[sheet].columns if column != "Total"]
        columns += [year for year in years if year not in columns]
        columns += ["Total"]
        output[sheet] = _pivot(pivot_rows, indexes, all_year_labels, columns)
    return SummaryResult(output, len(unknown_models), len(unknown_colors))
