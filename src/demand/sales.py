"""Step 04 — billed sales, revenue and margin.

Divergence from the step specification, found by reading the file: in this vintage
``Payer`` holds a dealer *name* only and ``Material`` a *description* only — neither is
glued code+label, and there is no part number anywhere in the file. So sales cannot be
joined to the part master by number; it is keyed on description text and reported as
such. The Step 00 parser is still applied, and degrades correctly to (None, text).
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.result import StageResult, StageStatus
from src.demand.orders import drop_empty, material_category
from src.io.excel import read_source
from src.io.parquet import write_table
from src.io.sap import split_code_label

#: Bill. Type codes that represent a return rather than a sale.
RETURN_BILL_TYPES = {"RE", "ZRE", "ZRVT", "ZRSV"}

#: Candidate revenue columns. This export ships two headers that both read "Net Sales":
#: one net of ``Surcharge`` (which goes negative on VAT-surcharge lines and is therefore
#: not the revenue line) and one that satisfies the declared identity. The right column
#: is chosen by testing the business rule, never by position — a newer export may order
#: or name them differently.
NET_SALES_CANDIDATES = ("Net Sales", "Net Sales_1", "Net Sales_2")


def resolve_net_sales(frame: pd.DataFrame, result: StageResult) -> str | None:
    """Return the column that satisfies ``Net Sales = Sales Pric + Discount``.

    Business meaning: revenue on a billed line, after discount and before tax. The
    identity is verified against every candidate and the best match wins; picking the
    wrong one silently turns 9.1B LKR of revenue into a 1.7B loss, because the rejected
    column is net of ``Surcharge``.
    """
    present = [c for c in NET_SALES_CANDIDATES if c in frame.columns]
    if not present:
        return None
    if not {"Sales Pric", "Discount"}.issubset(frame.columns):
        result.warn(
            f"Sales Pric/Discount absent — cannot verify the revenue identity; "
            f"using {present[0]!r} as recorded"
        )
        return present[0]

    expected = pd.to_numeric(frame["Sales Pric"], errors="coerce") + pd.to_numeric(
        frame["Discount"], errors="coerce"
    )
    scores: dict[str, int] = {}
    for column in present:
        difference = (pd.to_numeric(frame[column], errors="coerce") - expected).abs()
        scores[column] = int((difference < 0.01).sum())

    chosen = max(scores, key=lambda c: scores[c])
    total = len(frame)
    detail = ", ".join(f"{c}={scores[c] / total:.1%}" for c in present)
    result.warn(
        f"revenue column resolved to {chosen!r} by the identity "
        f"Net Sales == Sales Pric + Discount ({detail} of {total:,} rows)"
    )
    if len(present) > 1:
        rejected = [c for c in present if c != chosen]
        result.warn(
            f"rejected revenue column(s) {rejected} — they carry a different measure "
            f"(net of Surcharge in this vintage), not billed revenue"
        )
    if scores[chosen] / total < 0.95:
        result.warn(
            f"WARNING: the best revenue column {chosen!r} still fails the identity on "
            f"{total - scores[chosen]:,} row(s) — revenue figures are suspect"
        )
    return chosen


def parse_billing_date(series: pd.Series) -> pd.Series:
    """Billing Date arrives as ``DD.MM.YYYY`` text in this export."""
    parsed = pd.to_datetime(series, format="%d.%m.%Y", errors="coerce")
    fallback = pd.to_datetime(series, errors="coerce", dayfirst=True)
    return parsed.fillna(fallback)


@REGISTRY.register(
    "04_sales",
    depends_on=["02_part_master"],
    description="billed sales, revenue, margin and performance cuts",
)
def run(ctx: PlanningContext) -> StageResult:  # noqa: ARG001 — contract requires ctx
    result = StageResult(stage="04_sales")
    raw = read_source("sales")
    raw.columns = [str(c).strip() for c in raw.columns]
    result.rows_in = len(raw)

    frame, dropped_cols, dropped_rows = drop_empty(raw)
    if dropped_cols:
        result.warn(f"dropped {dropped_cols} fully-null column(s)")
    if dropped_rows:
        result.reject("fully null row", dropped_rows)

    required = {"SlsVolQty", "Payer", "Material"}
    if not required.issubset(frame.columns):
        result.status = StageStatus.FAILED
        result.error = f"sales is missing {sorted(required - set(frame.columns))}"
        return result
    if not any(c in frame.columns for c in NET_SALES_CANDIDATES):
        result.status = StageStatus.FAILED
        result.error = f"sales carries no revenue column; expected one of {NET_SALES_CANDIDATES}"
        return result

    # Apply the declared parser; in this vintage it correctly yields no codes.
    payer_parsed = frame["Payer"].map(split_code_label)
    frame["payer_code"] = [p[0] for p in payer_parsed]
    frame["payer_name"] = [p[1] or p[0] for p in payer_parsed]
    material_parsed = frame["Material"].map(split_code_label)
    frame["material_code"] = [m[0] for m in material_parsed]
    frame["material_description"] = [m[1] or m[0] for m in material_parsed]

    coded = int(frame["material_code"].notna().sum())
    result.warn(
        f"Material carries a part number on {coded:,}/{len(frame):,} rows — this vintage is "
        f"description-only, so sales cannot be keyed to the part master by number"
    )

    dealers = read_source("dealers")
    dealers.columns = [str(c).strip() for c in dealers.columns]
    dealers["_name"] = dealers["Dealer Name"].astype(str).str.strip().str.upper()
    by_name = dealers.drop_duplicates("_name").set_index("_name")
    name_key = frame["payer_name"].astype(str).str.strip().str.upper()
    for column in ("Type", "Province", "District", "ASE", "RM"):
        if column in dealers.columns:
            frame[column if column != "Type" else "Dealer Type"] = name_key.map(by_name[column])
    frame["Dealer Type"] = frame.get("Dealer Type", pd.Series(index=frame.index)).fillna(
        "Not Found"
    )
    matched = int((frame["Dealer Type"] != "Not Found").sum())
    result.warn(
        f"dealer join by name: {matched:,}/{len(frame):,} matched; "
        f"{frame['payer_name'].nunique():,} distinct payers against {len(dealers):,} dealers"
    )

    frame["material_category"] = [
        material_category(d, t)
        for d, t in zip(frame["material_description"], frame["Dealer Type"], strict=True)
    ]

    # Money. The revenue column is chosen by the identity, then used as recorded.
    numeric = ("Sales Pric", "Discount", "Cost", "SlsVolQty", "Tax Amount", "Surcharge")
    for column in (*numeric, *NET_SALES_CANDIDATES):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    net_sales_column = resolve_net_sales(frame, result)
    if net_sales_column is None:  # pragma: no cover — guarded above
        result.status = StageStatus.FAILED
        result.error = "no revenue column survived resolution"
        return result
    frame["net_sales_column"] = net_sales_column
    frame["Net Sales"] = frame[net_sales_column]

    if "Sales Pric" in frame.columns and "Bill. Type" in frame.columns:
        difference = (frame["Net Sales"] - (frame["Sales Pric"] + frame["Discount"])).abs()
        offenders = frame.loc[difference >= 0.01, "Bill. Type"].value_counts().head(3).to_dict()
        if offenders:
            result.warn(f"rows still failing the identity, by Bill. Type: {offenders}")
    frame["margin"] = frame["Net Sales"] - frame.get("Cost", 0)

    bill_type = frame.get("Bill. Type", pd.Series("", index=frame.index)).astype(str).str.upper()
    frame["is_return"] = bill_type.isin(RETURN_BILL_TYPES) | (frame["SlsVolQty"] < 0)
    result.warn(
        f"returns: {int(frame['is_return'].sum()):,} row(s) by Bill. Type "
        f"{sorted(RETURN_BILL_TYPES)} or negative SlsVolQty — netted, not dropped"
    )

    dates = parse_billing_date(frame["Billing Date"]) if "Billing Date" in frame else pd.Series()
    if dates.notna().any():
        frame["month"] = dates.dt.to_period("M").astype(str)
        months = sorted(frame["month"].dropna().unique())
        expected = pd.period_range(months[0], months[-1], freq="M").astype(str)
        gaps = [m for m in expected if m not in set(months)]
        result.warn(
            f"observed billing window: {months[0]} to {months[-1]}; "
            + (f"MISSING month(s): {gaps}" if gaps else "no missing months")
        )
    else:
        frame["month"] = None
        result.warn("Billing Date could not be parsed — monthly trend unavailable")

    parts_sales = frame
    result.rows_out = len(parts_sales)
    result.artifact("parts_sales", write_table(parts_sales, "facts", "parts_sales"))

    # Performance cuts, mirroring Step 05 so ordered and billed compare side by side.
    def cut(by: str, name: str) -> None:
        if by not in parts_sales.columns:
            return
        agg = (
            parts_sales.groupby(by, as_index=False)
            .agg(
                net_sales=("Net Sales", "sum"),
                margin=("margin", "sum"),
                quantity=("SlsVolQty", "sum"),
                lines=("Net Sales", "count"),
            )
            .sort_values("net_sales", ascending=False)
        )
        result.artifact(name, write_table(agg, "facts", name))

    cut("material_description", "sales_by_material")
    cut("payer_name", "sales_by_dealer")
    for column, name in (
        ("RM", "sales_by_rm"),
        ("ASE", "sales_by_ase"),
        ("Province", "sales_by_province"),
        ("District", "sales_by_district"),
        ("month", "sales_monthly"),
    ):
        cut(column, name)

    kpis = pd.DataFrame(
        [
            {
                "total_invoices": parts_sales.get(
                    "Billing Document", pd.Series(dtype=object)
                ).nunique(),
                "total_lines": len(parts_sales),
                "total_quantity": float(parts_sales["SlsVolQty"].sum()),
                "total_cost": float(parts_sales.get("Cost", pd.Series(dtype=float)).sum()),
                "total_net_sales": float(parts_sales["Net Sales"].sum()),
                "total_margin": float(parts_sales["margin"].sum()),
                "unique_materials": parts_sales["material_description"].nunique(),
                "returns": int(parts_sales["is_return"].sum()),
                # Provenance: which of the export's two "Net Sales" headers was used.
                "net_sales_column": net_sales_column,
            }
        ]
    )
    result.artifact("sales_kpis", write_table(kpis, "facts", "sales_kpis"))

    logger.info(f"sales: {len(parts_sales):,} lines, net {kpis.at[0, 'total_net_sales']:,.0f} LKR")
    return result
