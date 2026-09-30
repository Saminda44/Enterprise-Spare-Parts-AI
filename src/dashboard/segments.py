"""MC and OBM spare parts: the one rule that splits every spare-parts view.

The dashboard has two spare-parts sections. A part belongs to one by its PN_Yamaha brand:
``OB`` (Yamaha outboard) is OBM; everything else — Yamaha motorcycle ``YM`` and the few
Katana tyres (``KT``), which motorcycle dealers buy — is MC. The same rule applies to
analysis, forecast, order plan, stock and the part master, so the two sections add up to
the whole book on every page.
"""

from __future__ import annotations

import pandas as pd

SEGMENT_MC = "MC"
SEGMENT_OBM = "OBM"
SEGMENTS = (SEGMENT_MC, SEGMENT_OBM)
#: PN_Yamaha brand of Yamaha outboard parts.
OBM_BRAND = "OB"
#: sales.xlsx carries no part number; its material-group family names the brand
#: ("AWPOB0014" -> "AWPOB" -> outboard).
OBM_MATERIAL_GROUP_FAMILY = "AWPOB"


def segment_of_brand(brand: pd.Series) -> pd.Series:
    """MC / OBM from a PN_Yamaha brand column.

    Business meaning: outboard parts (brand OB) are OBM spare parts; every other brand is
    an MC spare part, including a part with no brand recorded.
    """
    is_obm = brand.astype(str).str.strip().str.upper() == OBM_BRAND
    return pd.Series(is_obm.map({True: SEGMENT_OBM, False: SEGMENT_MC}), index=brand.index)


def sku_segments(master: pd.DataFrame) -> pd.Series:
    """``active_sku_id`` -> MC / OBM, from the brand of the part's current number.

    Business meaning: a few supersession chains cross brands (an old motorcycle number
    replaced by an outboard one, or the reverse). The part is what its current number is,
    so its section follows the current number's brand — the same rule on every page.
    """
    current = master[master["material"].astype(str) == master["active_sku_id"].astype(str)]
    ordered = master.sort_values("chain_depth") if "chain_depth" in master else master
    heads = (
        pd.concat([current, ordered]).drop_duplicates("active_sku_id").set_index("active_sku_id")
    )
    return segment_of_brand(heads["brand"])


#: MC spare parts split four ways by the part's description (CLAUDE.md material-category
#: rule); OBM parts are one category.
CATEGORY_LUBRICANT = "Lubricant"
CATEGORY_BATTERY = "Battery"
CATEGORY_TYRE = "Tyre"
CATEGORY_SPARE_PARTS = "Spare Parts"
CATEGORY_OBM = "OBM Spare Parts"
#: Request values (``?category=``) -> the published label.
CATEGORY_KEYS = {
    "spare_parts": CATEGORY_SPARE_PARTS,
    "lubricant": CATEGORY_LUBRICANT,
    "battery": CATEGORY_BATTERY,
    "tyre": CATEGORY_TYRE,
}


def part_category(description: pd.Series, segment: pd.Series) -> pd.Series:
    """Lubricant / Battery / Tyre / Spare Parts for MC parts; OBM Spare Parts for OBM.

    Business meaning: the CLAUDE.md material-category rule, applied to the part itself so
    every page splits MC the same way — description contains YAMALUBE → Lubricant,
    KARATE BATTERY → Battery, KATANA TYRE → Tyre, otherwise Spare Parts.
    """
    text = description.fillna("").astype(str).str.upper()
    out = pd.Series(CATEGORY_SPARE_PARTS, index=description.index, dtype=object)
    out[text.str.contains("YAMALUBE", regex=False)] = CATEGORY_LUBRICANT
    out[text.str.contains("KARATE BATTERY", regex=False)] = CATEGORY_BATTERY
    out[text.str.contains("KATANA TYRE", regex=False)] = CATEGORY_TYRE
    out[segment.astype(str).str.upper() == SEGMENT_OBM] = CATEGORY_OBM
    return out


def sales_category(description: pd.Series, group: pd.Series, segment: pd.Series) -> pd.Series:
    """The same split for billed sales lines, which also carry other brands' lubricants.

    Business meaning: the description rule first; then the lubricant material groups
    (``AWL…``, e.g. Castrol) are Lubricant and the Katana group (``AWPKT``) is Tyre, so a
    non-Yamaha oil is not counted as a spare part.
    """
    out = part_category(description, segment)
    family = group.fillna("").astype(str).str.strip().str.upper()
    mc_spare = out == CATEGORY_SPARE_PARTS
    out[mc_spare & family.str.startswith("AWL")] = CATEGORY_LUBRICANT
    out[mc_spare & family.str.startswith("AWPKT")] = CATEGORY_TYRE
    return out


def segment_of_material_group(group: pd.Series) -> pd.Series:
    """MC / OBM for billed sales lines, from the material group (they carry no part number)."""
    is_obm = group.astype(str).str.strip().str.upper().str.startswith(OBM_MATERIAL_GROUP_FAMILY)
    return pd.Series(is_obm.map({True: SEGMENT_OBM, False: SEGMENT_MC}), index=group.index)
