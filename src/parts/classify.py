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
from src.io.parquet import append_columns, read_table, write_table

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


@REGISTRY.register(
    "06_classification",
    depends_on=["03_orders"],
    description="behaviour, ADI/CV2 quadrant, ABC, XYZ, FSN",
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
    classification["abc"] = abc_classes(classification["annual_consumption_value"]).values

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
    classification["behaviour_class"] = classification["description"].map(behaviour_class)

    #: No criticality source exists in any supplied file. Step 13 treats
    #: criticality = high specially and must not be fed a guess.
    classification["criticality"] = None

    result.warn(
        "BEHAVIOUR CLASSIFIER IS RULES-ONLY: no hand-labelled sample exists, so no "
        "supervised model was trained and no held-out macro-F1 or confusion matrix can be "
        "reported. Labels come from keyword rules over the description."
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
