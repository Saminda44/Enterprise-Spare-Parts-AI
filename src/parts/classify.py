"""Step 06 — behaviour, demand pattern, value and movement classification.

These are routing keys, not reports: the quadrant decides which forecast family Step 07
may use and which safety-stock strategy Step 13 applies.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
from loguru import logger

from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.result import StageResult
from src.demand import sales_link
from src.io.parquet import append_columns, read_table, table_exists, write_table
from src.parts import behaviour as part_behaviour

#: Syntetos-Boylan cutoffs.
ADI_CUT = 1.32
CV2_CUT = 0.49

#: A part with fewer than this many non-zero months is routed to the conservative path
#: rather than having a quadrant forced onto four data points.
MIN_NONZERO_MONTHS = 12

ABC_THRESHOLDS = (0.80, 0.95)

#: Rules-only behaviour classifier. Ordered — the first pattern that matches wins, so
#: the more specific classes are tested before the general ones.
BEHAVIOUR_RULES: tuple[tuple[str, str], ...] = (
    (
        "engine part",
        r"\b(PISTON|CRANK|CAMSHAFT|CYLINDER|VALVE|CARBURET|INJECT|GASKET,? *HEAD|"
        r"CONNECTING ROD|CRANKCASE|TAPPET|ROCKER|TIMING|OIL PUMP|CLUTCH|"
        r"TRANSMISSION|GEAR|MAGNETO|STARTER|IGNIT)",
    ),
    (
        "wear part",
        r"\b(BRAKE|PAD|SHOE|DISC|CHAIN|SPROCKET|TYRE|TIRE|TUBE|FILTER|"
        r"SPARK ?PLUG|S\. ?PLUG|BELT|BEARING|OIL SEAL|SEAL,? *VALVE|BULB|"
        r"BATTERY|CABLE|LINING|ELEMENT|YAMALUBE|LUBRICANT|GREASE)",
    ),
    (
        "crash part",
        r"\b(FENDER|MUDGUARD|GUARD|COWLING|CRASH|BUMPER|PROTECTOR|SHIELD|"
        r"MIRROR|LEVER|HANDLE ?BAR|FOOTREST|STAND)",
    ),
    (
        "cosmetic part",
        r"\b(GRAPHIC|EMBLEM|DECAL|STICKER|STRIPE|COVER,? *SIDE|MARK|BADGE|"
        r"ORNAMENT|PANEL|CASING|LENS|TRIM)",
    ),
    (
        "service part",
        r"\b(BOLT|NUT|SCREW|WASHER|CLIP|CLAMP|COLLAR|SPRING|PIN|CIRCLIP|"
        r"O-RING|ORING|RING|PLATE|BRACKET|BRKT|HOSE|PIPE|JOINT|BAND|DAMPER)",
    ),
)
_COMPILED = tuple((label, re.compile(pattern, re.I)) for label, pattern in BEHAVIOUR_RULES)


def behaviour_class(description: object) -> str:
    """First matching rule wins; unmatched parts are labelled, never guessed."""
    text = str(description or "")
    for label, pattern in _COMPILED:
        if pattern.search(text):
            return label
    return "unclassified"


def demand_pattern(monthly: pd.Series) -> tuple[float, float, str]:
    """ADI and CV² over a part's monthly series, then the Syntetos-Boylan quadrant.

    ADI is the mean interval between non-zero periods; CV² is the squared coefficient of
    variation of the **non-zero demand sizes**.
    """
    values = monthly.to_numpy(dtype=float)
    nonzero = values[values > 0]
    periods = len(values)
    if periods == 0 or nonzero.size == 0:
        return float("nan"), float("nan"), "no demand"

    adi = periods / nonzero.size
    mean = nonzero.mean()
    cv2 = float((nonzero.std(ddof=0) / mean) ** 2) if mean else float("nan")

    if np.isnan(cv2):
        return adi, cv2, "no demand"
    if adi <= ADI_CUT:
        quadrant = "smooth" if cv2 <= CV2_CUT else "erratic"
    else:
        quadrant = "intermittent" if cv2 <= CV2_CUT else "lumpy"
    return float(adi), cv2, quadrant


def abc_classes(values: pd.Series) -> pd.Series:
    """Pareto on annual consumption value: A = top 80%, B = next 15%, C = the rest."""
    ordered = values.sort_values(ascending=False)
    total = ordered.sum()
    if total <= 0:
        return pd.Series("C", index=values.index)
    share = (ordered.cumsum() / total).to_numpy()
    labels = np.where(
        share <= ABC_THRESHOLDS[0], "A", np.where(share <= ABC_THRESHOLDS[1], "B", "C")
    )
    return pd.Series(labels, index=ordered.index).reindex(values.index)


def _catalogue_sections(master: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(SKU -> most-listed catalogue section, catalogue description -> most-listed section).

    A catalogue row joins on its part number against every number in a SKU's supersession
    chain, so a part catalogued under an old number still gets its section.
    """
    import psycopg  # noqa: PLC0415 - the store is optional; imported only when used

    from src.core.settings import get_settings  # noqa: PLC0415
    from src.parts.supersession import normalise  # noqa: PLC0415

    with psycopg.connect(**get_settings().postgres_params()) as con, con.cursor() as cur:
        cur.execute(
            "select part_no, section, description from catalogue_parts where row_kind = 'part'"
        )
        rows = cur.fetchall()
    catalogue = pd.DataFrame(rows, columns=["part_no", "section", "description"])
    catalogue["section"] = catalogue["section"].astype(str).str.strip(" .")
    catalogue["key"] = catalogue["part_no"].map(normalise)
    aliases = master.assign(key=master["material"].map(normalise))[["key", "active_sku_id"]]
    linked = catalogue.merge(aliases.drop_duplicates(), on="key")
    most = lambda s: s.value_counts().index[0]  # noqa: E731 - modal section
    by_sku = linked.groupby("active_sku_id")["section"].agg(most)
    catalogue["dkey"] = part_behaviour.description_key(catalogue["description"])
    by_description = catalogue[catalogue["dkey"].ne("")].groupby("dkey")["section"].agg(most)
    return by_sku, by_description


def _part_behaviour(master: pd.DataFrame, result: StageResult) -> pd.DataFrame:
    """Behaviour class, system and deciding source for every Part Master SKU.

    Writes ``part_behaviour`` (all SKUs, ordered or not). Without the catalogue store the
    catalogue layers are skipped and said so — classes then rest on descriptions alone.
    """
    # The current number's own description leads; the chain's other descriptions are
    # searched too, since superseded numbers often carry typos ("DICS,BRAKE", "TAB TRIB").
    current = master[master["material"] == master["active_sku_id"]]
    heads = pd.concat([current, master.sort_values("chain_depth")], ignore_index=True)
    heads = heads.drop_duplicates("active_sku_id", keep="first")
    described = master.dropna(subset=["description"]).assign(
        description=lambda d: d["description"].astype(str).str.strip()
    )
    texts = (
        described[described["description"].ne("")]
        .groupby("active_sku_id")["description"]
        .agg(lambda s: " | ".join(dict.fromkeys(s)))
    )
    skus = heads[["active_sku_id", "description", "brand"]].copy()
    skus["match_text"] = skus["active_sku_id"].map(texts).fillna(skus["description"])
    try:
        by_sku, by_description = _catalogue_sections(master)
    except Exception as exc:  # noqa: BLE001 - optional store; degrade loudly, never silently
        by_sku, by_description = pd.Series(dtype=object), pd.Series(dtype=object)
        result.warn(
            f"CATALOGUE STORE UNREACHABLE ({type(exc).__name__}) — behaviour classes use "
            f"descriptions only; check the POSTGRES_* settings in .env"
        )
    behaviour = part_behaviour.classify_all(skus, by_sku, by_description)
    write_table(behaviour, "facts", "part_behaviour")
    result.warn(
        f"behaviour for all {len(behaviour):,} Part Master SKUs: "
        f"{behaviour['behaviour_class'].value_counts().to_dict()}; decided by "
        f"{behaviour['behaviour_source'].value_counts().to_dict()}; "
        f"{len(by_sku):,} SKUs carry a catalogue section by part number"
    )
    return behaviour


def _sales_classification(
    ctx: PlanningContext, master: pd.DataFrame, history: pd.DataFrame, result: StageResult
) -> pd.DataFrame:
    """Link sales.xlsx to the Part Master and classify every linked SKU on billed value.

    Writes ``sales_classification`` (every linked SKU, including parts dealers never
    ordered) and ``sales_link_audit`` (lines and value by outcome), and returns the
    columns Step 06 merges onto its own SKUs.
    """
    if not table_exists("facts", "parts_sales"):
        result.warn("no parts_sales fact — ABC falls back to order value for every part")
        return pd.DataFrame(columns=["active_sku_id", "sales_abc"])
    sales = read_table("facts", "parts_sales")
    # Step 04 decided which of the two "Net Sales" columns is Sales Pric + Discount.
    chosen = str(sales["net_sales_column"].iloc[0]) if "net_sales_column" in sales else "Net Sales"
    sales["Net Sales"] = pd.to_numeric(sales[chosen], errors="coerce").fillna(0.0)

    start, end = sales_link.sales_window(sales["month"], ctx.as_of)
    in_window = history["month"].astype(str).between(str(start), str(end))
    demand = history[in_window].groupby("active_sku_id")["ordered_quantity"].sum()
    columns = ["material", "active_sku_id", "description", "material_group"]
    alloc, audit = sales_link.link_lines(
        master[[c for c in columns if c in master.columns]], sales, demand, ctx.as_of
    )
    weights = alloc.groupby("line_id")["weight"].sum()
    if len(weights) and not bool(((weights - 1.0).abs() < 1e-9).all()):
        raise ValueError("sales allocation weights do not sum to 1 per line")
    classes = sales_link.classify(alloc, str(audit["window_end"]))
    audit["linked_skus"] = int(alloc["active_sku_id"].nunique()) if len(alloc) else 0
    audit["return_only_skus"] = audit["linked_skus"] - len(classes)

    write_table(classes, "facts", "sales_classification")
    write_table(pd.DataFrame([audit]), "facts", "sales_link_audit")
    in_scope = float(audit["in_scope_value"]) or 1.0
    result.warn(
        f"sales link {audit['window_start']}..{audit['window_end']}: "
        f"{audit['sales_lines']:,} billed lines; {audit['out_of_scope_lines']:,} out of scope "
        f"(material groups not in the Part Master, {audit['out_of_scope_value']:,.0f} LKR — "
        f"mostly non-Yamaha lubricants); of the rest, "
        f"{float(audit['linked_value']) / in_scope:.1%} of value linked "
        f"(description {audit['description_lines']:,}, resolved by order demand "
        f"{audit['demand_resolved_lines']:,}, split by order share {audit['demand_split_lines']:,} "
        f"lines); {audit['ambiguous_lines']:,} ambiguous with no order evidence and "
        f"{audit['no_match_lines']:,} with no Part Master description left unattributed"
    )
    result.warn(
        f"sales classes on {len(classes):,} SKUs: "
        f"ABC {classes['sales_abc'].value_counts().to_dict()}"
    )
    return classes[
        ["active_sku_id", "sales_abc", "sales_xyz", "sales_fsn", "sales_net_lkr", "sales_link"]
    ]


@REGISTRY.register(
    "06_classification",
    depends_on=["03_orders", "04_sales"],
    description="behaviour, ADI/CV2 quadrant, ABC (billed sales value), XYZ, FSN",
)
def run(ctx: PlanningContext) -> StageResult:
    result = StageResult(stage="06_classification")
    history = read_table("facts", "demand_history")
    master = read_table("facts", "part_master_enriched")
    result.rows_in = len(master)

    months = sorted(history["month"].dropna().unique())
    if not months:
        result.warn("demand history carries no months — classification cannot run")
        return result
    horizon = pd.period_range(months[0], months[-1], freq="M").astype(str)

    panel = (
        history.pivot_table(
            index="active_sku_id", columns="month", values="ordered_quantity", aggfunc="sum"
        )
        .reindex(columns=horizon)
        .fillna(0.0)
    )

    rows: list[dict[str, object]] = []
    for sku, series in panel.iterrows():
        adi, cv2, quadrant = demand_pattern(series)
        nonzero = int((series > 0).sum())
        rows.append(
            {
                "active_sku_id": sku,
                "months_observed": int(len(series)),
                "nonzero_months": nonzero,
                "adi": adi,
                "cv2": cv2,
                "quadrant": quadrant,
                "insufficient_history": nonzero < MIN_NONZERO_MONTHS,
                "mean_monthly_demand": float(series.mean()),
                "cv_monthly": float(series.std(ddof=0) / series.mean())
                if series.mean()
                else np.nan,
            }
        )
    classification = pd.DataFrame(rows)

    value = history.groupby("active_sku_id")["order_value"].sum().rename("annual_consumption_value")
    classification = classification.merge(
        value, left_on="active_sku_id", right_index=True, how="left"
    )
    classification["annual_consumption_value"] = classification["annual_consumption_value"].fillna(
        0.0
    )
    classification["abc_orders"] = abc_classes(classification["annual_consumption_value"]).values
    sales_classes = _sales_classification(ctx, master, history, result)
    classification = classification.merge(sales_classes, on="active_sku_id", how="left")
    # ABC is the billed-sales value class (owner decision 2026-09-28). A part with no linked
    # sale in the window — typically a model launched after sales.xlsx ends — keeps its
    # order-value class, and says so.
    has_sales = classification["sales_abc"].notna()
    classification["abc"] = classification["sales_abc"].where(
        has_sales, classification["abc_orders"]
    )
    classification["abc_source"] = np.where(has_sales, "sales", "orders")

    cv = classification["cv_monthly"]
    classification["xyz"] = np.where(cv <= 0.5, "X", np.where(cv <= 1.0, "Y", "Z"))

    last_month = history[history["ordered_quantity"] > 0].groupby("active_sku_id")["month"].max()
    classification["last_demand_month"] = classification["active_sku_id"].map(last_month)
    recency = (
        pd.PeriodIndex(classification["last_demand_month"].fillna(months[0]), freq="M")
        .to_timestamp()
        .to_series(index=classification.index)
    )
    months_since = ((pd.Timestamp(ctx.as_of) - recency).dt.days / 30.44).where(
        classification["last_demand_month"].notna(), np.inf
    )
    classification["fsn"] = np.where(
        classification["nonzero_months"] == 0,
        "N",
        np.where(months_since <= 3, "F", np.where(months_since <= 12, "S", "N")),
    )

    descriptions = master.set_index("active_sku_id")["description"].to_dict()
    classification["description"] = classification["active_sku_id"].map(descriptions)
    behaviour = _part_behaviour(master, result)
    classification = classification.merge(
        behaviour[
            ["active_sku_id", "behaviour_class", "behaviour_source", "system", "catalogue_section"]
        ],
        on="active_sku_id",
        how="left",
    )
    classification["behaviour_class"] = classification["behaviour_class"].fillna(
        classification["description"].map(behaviour_class)
    )

    #: No criticality source exists in any supplied file. Step 13 treats
    #: criticality = high specially and must not be fed a guess.
    classification["criticality"] = None

    result.warn(
        "BEHAVIOUR CLASSIFIER IS RULE-BASED, catalogue-assisted: no hand-labelled sample "
        "exists, so no supervised model was trained and no held-out macro-F1 can be reported. "
        "Labels come from the description's part nature, then the PDF catalogue section, "
        "then description keywords."
    )
    result.warn(
        "CRITICALITY (VED) IS UNSET: no source in any supplied file marks a part as "
        "immobilising. Step 13's criticality=high branch will not fire."
    )

    counts = classification["quadrant"].value_counts().to_dict()
    result.warn(f"demand quadrants: {counts}")
    dominant = max(counts.values()) / len(classification) if len(classification) else 0
    if dominant > 0.95:
        result.warn(
            f"one quadrant holds {dominant:.0%} of parts — check the cutoffs or the history window"
        )
    result.warn(f"behaviour classes: {classification['behaviour_class'].value_counts().to_dict()}")
    result.warn(
        f"ABC source: {classification['abc_source'].value_counts().to_dict()} "
        f"(sales = billed-sales value class, orders = fallback for parts with no linked sale)"
    )
    result.warn(
        f"ABC: {classification['abc'].value_counts().to_dict()}; "
        f"XYZ: {classification['xyz'].value_counts().to_dict()}; "
        f"FSN: {classification['fsn'].value_counts().to_dict()}"
    )
    result.warn(
        f"{int(classification['insufficient_history'].sum()):,} part(s) with fewer than "
        f"{MIN_NONZERO_MONTHS} non-zero months routed to the conservative path"
    )

    result.rows_out = len(classification)
    result.artifact(
        "sku_classification", write_table(classification, "facts", "sku_classification")
    )

    enriched = append_columns(master, classification.drop(columns=["description"]), "active_sku_id")
    result.artifact("part_master_enriched", write_table(enriched, "facts", "part_master_enriched"))

    logger.info(f"classified {len(classification):,} SKUs")
    return result
