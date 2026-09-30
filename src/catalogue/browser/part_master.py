"""Build the cross-catalogue part master from ALL PDF catalogue extractions.

Strategy — mirrors the "All" colour tab in the catalogue viewer:
  For every agent-cached PDF, walk every build and record each unique part_no
  once per (model, variant), collapsing across colour variants.  This gives the
  same complete parts list that the "All" tab shows: every part the model uses,
  regardless of colour.

  For PDFs that have no agent cache JSON, fall back to the basic
  YamahaCatalogueExtractor so no PDF is silently skipped.

Outputs:
  data/catalogue_browser/catalogue_part_master.parquet   ← served by /parts/from-catalog
  data/catalogue_browser/catalogue_part_master.xlsx      ← Part Master + By Section sheets

Compatible-models column format:
  "AEROX B65J, AEROX B65L, AEROX B65M, AEROX B65N, ALFA 2XB3"
  (model folder name + variant code, no colour suffix)
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger
from src.catalogue.browser.overrides import model_folders

# ── Description quality helpers ───────────────────────────────────────────────
# Matches hyphenated Yamaha part numbers AND 12-char alphanumeric part numbers
# when they appear embedded inside a description string.
_EMBEDDED_PN_RE = re.compile(
    r"\b(?:[A-Z0-9]{2,5}-[A-Z0-9]{3,8}-[A-Z0-9]{2}(?:-[A-Z0-9]{2})?" r"|[A-Z0-9]{12})\b"
)
# Any Yamaha part number pattern (for raw-text description recovery)
_ANY_PN_RE = re.compile(
    r"\b([A-Z0-9]{2,5}-[A-Z0-9]{3,8}-[A-Z0-9]{2}(?:-[A-Z0-9]{2})?"
    r"|[A-Z0-9]{5}-[A-Z0-9]{3,8}"
    r"|[A-Z0-9]{12})\b"
)


def _is_garbled_description(desc: str) -> bool:
    """Return True if *desc* is a garbled PDF extraction artefact.

    Two conditions:
    1. Two or more embedded Yamaha part numbers — the description cell
       picked up content from ref_no + part_no columns of multiple rows
       (e.g. "2- 8 B97-E5111-00 8- 1 20P-E8113-00 …").
    2. One embedded part number where almost nothing meaningful remains
       after stripping the PN and all digit/ref-number tokens
       (e.g. "7-21 36LH2151V000 34-4" → nothing left).
    """
    if not desc:
        return False
    upper = desc.upper()
    # Case 1: multiple embedded part numbers
    if len(_EMBEDDED_PN_RE.findall(upper)) >= 2:
        return True
    # Case 2: single PN + noise only
    cleaned = _EMBEDDED_PN_RE.sub(" ", upper)
    cleaned = re.sub(r"\b[0-9][0-9\-]*\b", " ", cleaned)  # strip number/ref tokens
    real_chars = re.sub(r"[\s,./\-]", "", cleaned)
    return len(real_chars) < 3


def _best_description(counter: Counter[str]) -> str:
    """Return the best description from a frequency counter.

    Preference order:
      1. Most frequent non-empty, non-garbled description
      2. Most frequent non-empty (even if it might be garbled)
      3. Empty string
    """
    # Pass 1: non-empty, non-garbled
    for desc, _ in counter.most_common():
        if desc and not _is_garbled_description(desc):
            return desc.lstrip("., ")  # strip leading punctuation artefacts
    # Pass 2: non-empty (garbled but at least has text)
    for desc, _ in counter.most_common():
        if desc:
            return desc.lstrip("., ")
    return ""


def _browser_dir() -> Path:
    """Where the catalogue browser keeps its own artefacts, beside the marts.

    The legacy build wrote these into ``data/interim`` and ``data/outputs``, which no
    longer exist. They are the browser's own cache, not pipeline facts, so they live in
    their own directory rather than alongside published marts.
    """
    from src.core.settings import get_settings  # noqa: PLC0415 — avoids an import cycle

    directory = get_settings().marts_dir.parent / "catalogue_browser"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _pdf_root() -> Path:
    from src.core.settings import get_settings  # noqa: PLC0415 — avoids an import cycle

    return get_settings().raw_dir / "pdf_catalogues"


_AGENT_BUILDS_DIR = _browser_dir() / "agent_builds"
_PDF_ROOT = _pdf_root()
_PARQUET_OUT = _browser_dir() / "catalogue_part_master.parquet"
_XLSX_OUT = _browser_dir() / "catalogue_part_master.xlsx"
_CATALOG_PARTS_PARQUET = _browser_dir() / "catalog_parts.parquet"
_MODEL_COMPAT_PARQUET = _browser_dir() / "model_compatibility.parquet"
_PDF_EXTS = {".pdf", ".PDF"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _model_from_cache_file(cache_file: Path) -> str:
    """Extract model-folder name from a cache filename.

    Cache files are ``{folder}_{pdf_name}.pdf.json``, e.g.
    ``AEROX_1UB65460EV-AEROX.pdf.json`` → "AEROX".

    NOTE: this splits only on the *first* underscore, so it is only correct
    for single-word model folders.  Prefer ``_build_cache_stem_map`` when the
    PDF root is available, which handles multi-word folders correctly.
    """
    stem = cache_file.stem  # remove .json
    if stem.endswith(".pdf"):
        stem = stem[:-4]  # remove .pdf
    return stem.split("_", 1)[0]


def _build_cache_stem_map(pdf_root: Path) -> dict[str, str]:
    """Return a mapping of cache-stem → model folder name for every PDF under pdf_root.

    This is the authoritative way to recover the model folder for an agent
    JSON cache file: it scans the real PDF paths on disk, so multi-word folder
    names like "FZ & FZS", "MT 15", and "R 15" are preserved correctly.
    """
    mapping: dict[str, str] = {}
    for _product, folder in model_folders(pdf_root):
        for pdf in folder.rglob("*"):
            if pdf.suffix not in _PDF_EXTS or not pdf.is_file():
                continue
            rel = pdf.relative_to(pdf_root).as_posix()
            stem = _cache_key(rel)
            mapping[stem] = folder.name
    return mapping


def _cache_key(rel_path: str) -> str:
    """Reproduce the cache filename stem used by catalog.py _cache_path()."""
    return rel_path.replace("/", "_").replace("\\", "_").replace(" ", "_")


# ---------------------------------------------------------------------------
# Per-source extraction helpers
# ---------------------------------------------------------------------------

_PartRow = tuple[str, str, str, str, str]  # part_no, desc, section, variant, model


def _parts_from_agent_json(
    json_data: dict[str, Any],
    model_display: str,
    source_pdf: str,
) -> list[_PartRow]:
    """Extract one row per (part_no, variant) from an agent build JSON.

    Mirrors the "All" colour tab: include every part the variant uses,
    collapsing across all colour builds.  Each (part_no, variant) pair
    appears at most once.
    """
    builds: list[dict[str, Any]] = json_data.get("builds", [])
    seen: set[tuple[str, str]] = set()  # (part_no, variant)
    rows: list[_PartRow] = []

    for build in builds:
        variant = (build.get("variant") or "").strip()
        for part in build.get("parts", []):
            part_no = (part.get("part_no") or "").strip()
            if not part_no:
                continue
            key = (part_no, variant)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                (
                    part_no,
                    (part.get("description") or "").strip(),
                    (part.get("figure") or "").strip(),
                    variant,
                    model_display,
                )
            )

    return rows


def _text_scan_descriptions(pdf_path: Path, missing_pns: set[str]) -> dict[str, str]:
    """Recover descriptions for *missing_pns* from raw PDF text lines.

    The word-level extractor occasionally misses descriptions when the PDF
    renderer places the description text at a slightly different Y coordinate
    than the part number (e.g. R15.pdf CYLINDER section).
    pdfplumber.extract_text() re-joins the line correctly, so we parse that
    to fill the gap.

    Format expected on each line:
        [ref_no]  PART-NO  DESCRIPTION  [qty]  [remarks]
    """
    try:
        import pdfplumber
    except ImportError:
        return {}

    recovered: dict[str, str] = {}
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                if not missing_pns - recovered.keys():
                    break  # all found
                text = (page.extract_text() or "").upper()
                for line in text.split("\n"):
                    m = _ANY_PN_RE.search(line)
                    if not m:
                        continue
                    pn = m.group(1).replace("–", "-")
                    if pn not in missing_pns or pn in recovered:
                        continue
                    # Everything after the part number on this line
                    after = line[m.end() :].strip()
                    if not after:
                        continue
                    tokens = after.split()
                    # Strip trailing qty (pure digits or digit/slash)
                    while tokens and re.match(r"^\d[\d/]*$", tokens[-1]):
                        tokens.pop()
                    # Strip trailing non-alpha remarks (e.g. colour codes)
                    while tokens and not re.search(r"[A-Z]", tokens[-1]):
                        tokens.pop()
                    desc = " ".join(tokens).lstrip("., ").strip()
                    if desc and not _is_garbled_description(desc):
                        recovered[pn] = desc
    except Exception as exc:  # noqa: BLE001
        logger.debug("Text-scan fallback failed for {}: {}", pdf_path.name, exc)
    return recovered


def _parts_from_extractor(pdf_path: Path, model_folder: str) -> list[_PartRow]:
    """Extract raw rows from a PDF using YamahaCatalogueExtractor.

    Used as a fallback when no agent build JSON is available.
    Returns one row per unique part_no (no variant detail).

    A part can appear in multiple FIG sections of the same PDF; the first
    occurrence may have an empty description while a later occurrence has
    the real text.  We collect ALL rows for each part_no and keep the best
    description (non-garbled, non-empty, longest wins on ties).
    """
    try:
        from src.catalogue.browser.pdf_extractor import YamahaCatalogueExtractor

        extractor = YamahaCatalogueExtractor(max_pages=500)
        result = extractor.extract(pdf_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Extractor fallback failed for {}: {}", pdf_path.name, exc)
        return []

    if result.error:
        logger.warning("Extractor error for {}: {}", pdf_path.name, result.error)
        return []

    # Accumulate all candidate descriptions per part_no
    # (same part can appear in multiple FIG sections)
    from collections import defaultdict as _dd

    candidates: dict[str, list[tuple[str, str]]] = _dd(list)  # pn → [(desc, section), …]
    for row in result.rows or []:
        part_no = (row.get("part_no") or "").strip()
        if not part_no:
            continue
        desc = (row.get("description") or "").strip()
        section = (row.get("section") or "").strip()
        candidates[part_no].append((desc, section))

    rows: list[_PartRow] = []
    missing_desc: set[str] = set()
    for part_no, occurrences in candidates.items():
        # Pick the best description: non-garbled > non-empty > longest
        best_desc = ""
        best_section = occurrences[0][1] if occurrences else ""
        for desc, section in occurrences:
            if not desc or _is_garbled_description(desc):
                continue
            if not best_desc or len(desc) > len(best_desc):
                best_desc = desc.lstrip("., ")
                best_section = section
        if not best_desc:
            missing_desc.add(part_no)
        rows.append(
            (
                part_no,
                best_desc,
                best_section,
                "",  # no variant info from basic extractor
                model_folder,
            )
        )

    # ── Text-scan recovery for parts the word-level extractor missed ──────────
    if missing_desc:
        recovered = _text_scan_descriptions(pdf_path, missing_desc)
        if recovered:
            rows = [
                (pn, desc if desc else recovered.get(pn, desc), sec, var, mdl)
                for pn, desc, sec, var, mdl in rows
            ]
            logger.debug(
                "Text-scan recovered {} descriptions from {}",
                len(recovered),
                pdf_path.name,
            )

    return rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_part_master(
    agent_builds_dir: Path = _AGENT_BUILDS_DIR,
    pdf_root: Path = _PDF_ROOT,
    parquet_out: Path = _PARQUET_OUT,
    xlsx_out: Path = _XLSX_OUT,
    model_compat_parquet: Path = _MODEL_COMPAT_PARQUET,
) -> pd.DataFrame:
    """Aggregate all PDF catalogue extractions into a unified part master.

    Source priority per PDF:
      1. Agent build JSON (if cached) — full variant+colour detail, "All tab" view
      2. Basic YamahaCatalogueExtractor (fallback) — part_no + description only

    For each unique part_no the master records:
    - ``description``        : majority-vote across all occurrences
    - ``section``            : majority-vote section name
    - ``compatible_models``  : sorted "MODEL VARIANT, …" string
    - ``variant_count``      : distinct (model, variant) pairs
    - ``source_count``       : distinct source PDFs
    - ``source_pdfs``        : semicolon-joined PDF filenames
    - ``kind``               : "shared" if ever shared, else "colour_specific"
    - ``model_years``        : JSON string mapping model → manufacture year
                               (e.g. ``'{"AEROX": "2019"}'``), empty ``'{}'``
                               when the compatibility parquet is absent.

    Returns:
        DataFrame sorted by part_no.  Empty when no sources found.
    """
    # ── Discover all agent-cached JSONs that actually have parts ─────────────
    # A JSON with 0 parts (agent ran but extracted nothing) is NOT considered
    # cached — those PDFs fall through to the YamahaCatalogueExtractor fallback.
    json_files = sorted(agent_builds_dir.glob("*.json"))

    # Build stem→folder map from the real PDF paths so multi-word folder names
    # (e.g. "FZ & FZS", "MT 15", "R 15") are preserved correctly.
    stem_to_folder = _build_cache_stem_map(pdf_root)

    cached_stems: set[str] = set()
    for jf in json_files:
        try:
            _jdata = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        total_parts = sum(len(b.get("parts", [])) for b in _jdata.get("builds", []))
        if total_parts > 0:
            cached_stems.add(jf.stem)
        else:
            logger.debug("JSON has 0 parts — will fall back to extractor: {}", jf.name)

    # ── Discover all PDFs, compute which ones are NOT cached ─────────────────
    uncached_pdfs: list[tuple[Path, str]] = []  # (pdf_path, model_folder)
    if pdf_root.exists():
        for _product, folder in model_folders(pdf_root):
            model_folder = folder.name
            for pdf_path in sorted(folder.rglob("*")):
                if pdf_path.suffix not in _PDF_EXTS or not pdf_path.is_file():
                    continue
                rel = pdf_path.relative_to(pdf_root).as_posix()
                stem = _cache_key(rel)  # matches catalog.py naming
                if stem not in cached_stems:
                    uncached_pdfs.append((pdf_path, model_folder))

    logger.info(
        "Part master build: {} agent JSONs with parts + {} PDFs for extractor fallback",
        len(cached_stems),
        len(uncached_pdfs),
    )

    # Accumulators keyed by part_no
    desc_ctr: dict[str, Counter[str]] = defaultdict(Counter)
    sec_ctr: dict[str, Counter[str]] = defaultdict(Counter)
    compat: dict[str, set[tuple[str, str]]] = defaultdict(set)  # (model, variant)
    kind_set: dict[str, set[str]] = defaultdict(set)
    src_set: dict[str, set[str]] = defaultdict(set)

    def _ingest(rows: list[_PartRow], source_pdf: str, kind: str = "shared") -> None:
        for part_no, desc, section, variant, model in rows:
            desc_ctr[part_no][desc] += 1
            sec_ctr[part_no][section] += 1
            compat[part_no].add((model, variant))
            kind_set[part_no].add(kind)
            src_set[part_no].add(source_pdf)

    # ── Process agent JSONs ───────────────────────────────────────────────────
    for json_file in json_files:
        try:
            data: dict[str, Any] = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping %s: %s", json_file.name, exc)
            continue

        model_folder = stem_to_folder.get(json_file.stem) or _model_from_cache_file(json_file)
        model_display = (data.get("model") or "").strip() or model_folder
        source_pdf = data.get("source_pdf", json_file.stem)

        rows = _parts_from_agent_json(data, model_display, source_pdf)

        # Determine kind per part_no from the builds
        colour_specific_pns: set[str] = set()
        shared_pns: set[str] = set()
        for build in data.get("builds", []):
            for part in build.get("parts", []):
                pn = (part.get("part_no") or "").strip()
                k = part.get("kind", "shared")
                if k == "colour_specific":
                    colour_specific_pns.add(pn)
                else:
                    shared_pns.add(pn)

        for part_no, desc, section, variant, model in rows:
            desc_ctr[part_no][desc] += 1
            sec_ctr[part_no][section] += 1
            compat[part_no].add((model, variant))
            # shared wins: if a part is shared in ANY build, mark it shared
            if part_no in shared_pns:
                kind_set[part_no].add("shared")
            elif part_no in colour_specific_pns:
                kind_set[part_no].add("colour_specific")
            else:
                kind_set[part_no].add("shared")
            src_set[part_no].add(source_pdf)

        logger.info(
            "Agent JSON {} → {} parts ({})",
            json_file.name,
            len(rows),
            model_display,
        )

    # ── Load catalog_parts.parquet for reuse as extraction fallback ──────────
    # Prefer already-extracted data over re-running the extractor on every PDF.
    # The parquet column for part number is "part_number" (from batch extractor);
    # description and section are absent — use empty strings where missing.
    catalog_by_file: dict[str, list[_PartRow]] = defaultdict(list)
    if _CATALOG_PARTS_PARQUET.exists():
        try:
            _cp = pd.read_parquet(str(_CATALOG_PARTS_PARQUET))
            _pn_col = "part_number" if "part_number" in _cp.columns else "part_no"
            for _, _row in _cp.iterrows():
                _pn = str(_row.get(_pn_col, "") or "").strip()
                if not _pn:
                    continue
                _fname = str(_row.get("source_file", "") or "")
                catalog_by_file[_fname].append(
                    (
                        _pn,
                        str(_row.get("description", "") or "").strip(),
                        str(_row.get("section", "") or "").strip(),
                        "",  # no variant detail from basic extraction
                        str(_row.get("model", "") or "").strip(),
                    )
                )
            logger.info(
                "Loaded catalog_parts.parquet — {} filenames indexed",
                len(catalog_by_file),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load catalog_parts.parquet: {}", exc)

    # ── Process uncached PDFs: catalog parquet → extractor live fallback ──────
    for pdf_path, model_folder in uncached_pdfs:
        fname = pdf_path.name
        if catalog_by_file.get(fname):
            rows = catalog_by_file[fname]
            logger.info("Catalog parquet {} → {} parts ({})", fname, len(rows), model_folder)
        else:
            logger.info("Extracting (live fallback) {} …", fname)
            rows = _parts_from_extractor(pdf_path, model_folder)
            logger.info("Extractor fallback {} → {} parts ({})", fname, len(rows), model_folder)
        _ingest(rows, fname, kind="shared")

    if not desc_ctr:
        logger.warning("No parts collected — returning empty DataFrame")
        return pd.DataFrame()

    logger.info("Aggregating {} unique part_nos", len(desc_ctr))

    # ── Build output rows ─────────────────────────────────────────────────────
    output_rows: list[dict[str, Any]] = []
    for part_no in sorted(desc_ctr.keys()):
        description = _best_description(desc_ctr[part_no])
        section = sec_ctr[part_no].most_common(1)[0][0]

        # Sort compatible models: by model then variant
        sorted_compat = sorted(compat[part_no], key=lambda t: (t[0], t[1]))
        compat_parts: list[str] = []
        seen_entries: set[str] = set()
        for model, variant in sorted_compat:
            entry = f"{model} {variant}".strip() if variant else model
            if entry not in seen_entries:
                seen_entries.add(entry)
                compat_parts.append(entry)
        compatible_models = ", ".join(compat_parts)

        variant_count = len(compat[part_no])
        kind = "shared" if "shared" in kind_set[part_no] else "colour_specific"
        source_list = sorted(src_set[part_no])

        output_rows.append(
            {
                "part_no": part_no,
                "description": description,
                "section": section,
                "compatible_models": compatible_models,
                "variant_count": variant_count,
                "source_count": len(source_list),
                "source_pdfs": "; ".join(source_list),
                "kind": kind,
            }
        )

    df = pd.DataFrame(output_rows)

    # ── Enrich with model_years from cross-model compatibility parquet ────────
    if model_compat_parquet.exists():
        try:
            compat_df = pd.read_parquet(
                str(model_compat_parquet), columns=["part_no", "model_years"]
            )
            df = df.merge(compat_df, on="part_no", how="left")
            df["model_years"] = df["model_years"].fillna("{}")
            logger.info(
                "Joined model_years from {} — {} / {} parts enriched",
                model_compat_parquet.name,
                (df["model_years"] != "{}").sum(),
                len(df),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not join model_compat_parquet: {}", exc)
            df["model_years"] = "{}"
    else:
        logger.debug("model_compatibility.parquet not found — model_years will be empty")
        df["model_years"] = "{}"

    # ── Write parquet ─────────────────────────────────────────────────────────
    parquet_out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(str(parquet_out), index=False)
    logger.info("Wrote {} rows → {}", len(df), parquet_out)

    # ── Write Excel ───────────────────────────────────────────────────────────
    xlsx_out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(str(xlsx_out), engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Part Master", index=False)
        if not df.empty and "section" in df.columns:
            by_section = (
                df.groupby("section")
                .agg(unique_parts=("part_no", "nunique"))
                .reset_index()
                .sort_values("unique_parts", ascending=False)
            )
            by_section.to_excel(writer, sheet_name="By Section", index=False)
    logger.info("Wrote Excel → {}", xlsx_out)

    # The legacy build also mirrored this into PostgreSQL. There is no database in
    # this design — parquet under data/ is the store — so that write is not carried over.

    return df


def load_part_master(parquet_out: Path = _PARQUET_OUT) -> pd.DataFrame:
    """Load the saved part master parquet; returns empty DataFrame if absent."""
    if not parquet_out.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(str(parquet_out))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load catalogue_part_master.parquet: %s", exc)
        return pd.DataFrame()
