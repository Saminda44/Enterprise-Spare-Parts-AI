"""Step 02 — part master, supersession identity and model compatibility."""

from __future__ import annotations

from typing import Any

import pandas as pd
from loguru import logger

from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.result import StageResult, StageStatus
from src.io.excel import read_source
from src.io.parquet import read_table, table_exists, write_table
from src.parts.supersession import normalise, resolve_chains, supersede_columns


def _model_lookup() -> pd.DataFrame:
    """Model code -> family, name, years, from the Model Classification sheet."""
    frame = read_source("sales_summery__model_classification")
    frame.columns = [str(c).strip() for c in frame.columns]
    return frame


def _format_model(row: pd.Series, code: str) -> str:
    """``RAY - B2UG (2025)`` — family, code and year, as Step 02 specifies."""
    family = str(row.get("Model Family") or row.get("Model Name") or "").strip()
    year = row.get("First Year Sold")
    year_text = ""
    try:
        if year is not None and str(year) not in {"nan", "None", ""}:
            year_text = f" ({int(float(year))})"
    except (TypeError, ValueError):
        year_text = ""
    return f"{family} - {code}{year_text}" if family else f"{code}{year_text}"


def build_compatibility(models: pd.DataFrame) -> tuple[dict[str, list[str]], set[str]]:
    """part_no -> the models it fits, from the Step 01 catalogue output."""
    if not table_exists("facts", "catalogue_parts"):
        return {}, set()
    catalogue = read_table("facts", "catalogue_parts")
    if catalogue.empty or "model_code" not in catalogue.columns:
        return {}, set()

    code_col = next((c for c in ("Model", "Model Code", "model") if c in models.columns), None)
    by_code: dict[str, pd.Series] = {}
    if code_col:
        for _, row in models.iterrows():
            key = str(row[code_col]).strip().upper()
            if key and key != "NAN":
                by_code[key] = row

    compat: dict[str, set[str]] = {}
    unmatched: set[str] = set()
    pairs = catalogue[["part_no", "model_code"]].dropna().drop_duplicates()
    for part_no, model_code in pairs.itertuples(index=False):
        code = str(model_code).strip().upper()
        row = by_code.get(code)
        if row is None:
            unmatched.add(code)
            label = code
        else:
            label = _format_model(row, code)
        compat.setdefault(normalise(part_no), set()).add(label)
    return {k: sorted(v) for k, v in compat.items()}, unmatched


@REGISTRY.register(
    "02_part_master",
    depends_on=["01_catalogue"],
    description="supersession identity, model compatibility, part master",
)
def run(ctx: PlanningContext) -> StageResult:  # noqa: ARG001 — contract requires ctx
    result = StageResult(stage="02_part_master")
    pn = read_source("pn_yamaha")
    pn.columns = [str(c).strip() for c in pn.columns]
    result.rows_in = len(pn)

    if "Material" not in pn.columns or "Latest SS" not in pn.columns:
        result.status = StageStatus.FAILED
        result.error = "PN_Yamaha is missing Material or Latest SS"
        return result

    resolutions, cycles = resolve_chains(pn)
    if cycles:
        for message in cycles[:5]:
            result.warn(f"supersession cycle: {message[:160]}")
        result.warn(f"{len(cycles)} supersession cycle(s) total — chains left at Latest SS")

    master = pn.copy()
    master["active_sku_id"] = [r.active_sku_id for r in resolutions]
    master["chain_depth"] = [r.depth for r in resolutions]
    master["is_chain_head"] = [
        normalise(r.material) == normalise(r.active_sku_id) for r in resolutions
    ]

    # Verification, not recomputation: where the chain actually carries an edge, does it
    # agree with the pre-resolved Latest SS?
    derived_disagreements = [r for r in resolutions if r.depth >= 1 and not r.agrees_with_latest_ss]
    known = {normalise(m) for m in master["Material"]}
    dangling = [
        r for r in resolutions if normalise(r.latest_ss) and normalise(r.latest_ss) not in known
    ]
    result.warn(
        f"Latest SS verified against the chain: {len(derived_disagreements)} disagreement(s) "
        f"where a chain edge exists; {len(dangling)} Latest SS value(s) absent from Material"
    )

    models = _model_lookup()
    compat, unmatched_codes = build_compatibility(models)
    master["compatible_models"] = [
        ", ".join(compat.get(normalise(m), [])) for m in master["Material"]
    ]
    matched = int((master["compatible_models"] != "").sum())
    result.warn(
        f"model compatibility: {matched:,}/{len(master):,} parts matched "
        f"({matched / len(master):.1%}); {len(unmatched_codes)} catalogue model code(s) "
        f"absent from Model Classification"
    )

    # part_kind carried through from the catalogue
    if table_exists("facts", "catalogue_parts"):
        catalogue = read_table("facts", "catalogue_parts")
        if not catalogue.empty and "part_kind" in catalogue.columns:
            kinds = (
                catalogue.assign(_k=catalogue["part_no"].map(normalise))
                .groupby("_k")["part_kind"]
                .agg(lambda s: "coloured" if (s == "coloured").any() else "shared")
            )
            master["part_kind"] = master["Material"].map(normalise).map(kinds)

    rename = {
        "Material": "material",
        "Latest SS": "latest_ss",
        "Material description": "description",
        "Material Type": "material_type",
        "Material Group": "material_group",
        "Brand": "brand",
    }
    master = master.rename(columns=rename)
    keep = [
        "material",
        "active_sku_id",
        "latest_ss",
        "description",
        "material_type",
        "material_group",
        "brand",
        "compatible_models",
        "chain_depth",
        "is_chain_head",
    ]
    if "part_kind" in master.columns:
        keep.append("part_kind")
    keep.extend(supersede_columns(master.columns))
    part_master = master[keep]

    result.rows_out = len(part_master)
    result.artifact("part_master", write_table(part_master, "facts", "part_master"))
    # A separate copy: steps 06, 08, 12 and 13 append to this, never to the base.
    result.artifact(
        "part_master_enriched", write_table(part_master.copy(), "facts", "part_master_enriched")
    )

    chains = pd.DataFrame(
        {
            "material": [r.material for r in resolutions],
            "active_sku_id": [r.active_sku_id for r in resolutions],
            "latest_ss": [r.latest_ss for r in resolutions],
            "depth": [r.depth for r in resolutions],
            "agrees_with_latest_ss": [r.agrees_with_latest_ss for r in resolutions],
            "chain": [" -> ".join(r.chain) for r in resolutions],
        }
    )
    result.artifact("supersession_chains", write_table(chains, "facts", "supersession_chains"))

    logger.info(f"part master: {len(part_master):,} rows, {matched:,} with compatibility")
    return result


def summarise(part_master: pd.DataFrame) -> dict[str, Any]:
    """Coverage figures for the validation report."""
    return {
        "rows": len(part_master),
        "distinct_active_sku_id": part_master["active_sku_id"].nunique(),
        "with_compatibility": int((part_master["compatible_models"] != "").sum()),
        "chain_heads": int(part_master["is_chain_head"].sum()),
    }
