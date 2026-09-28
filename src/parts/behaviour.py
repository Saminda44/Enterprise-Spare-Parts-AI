"""Behaviour class and assembly system for every Part Master SKU, helped by the catalogues.

The behaviour class names what drives a part's replacement — wear, a crash, a failure, a
service — because Step 07 and the parc λ fit pool parts on it. The description alone is
terse ("WEIGHT", "COVER 2", "BOOT 2"), so the PDF catalogues supply what the part *is*:
every catalogue row sits in an assembly section (CRANKSHAFT & PISTON, HEADLIGHT, FENDER…).

Decided in layers, first match wins, and each SKU records which layer decided it:

1. the part's nature in its description — hardware is a service part and consumables are
   wear parts wherever they are fitted;
2. the catalogue section of the part number (or of any number in its supersession chain);
3. the catalogue section most often listed for the same description;
4. broader description keywords (including outboard parts, which the catalogues lack);
5. otherwise ``unclassified`` — never guessed.
"""

from __future__ import annotations

import re

import pandas as pd

UNCLASSIFIED = "unclassified"

#: Layer 1 — the part's physical nature decides regardless of where it is fitted.
NATURE_RULES: tuple[tuple[str, str], ...] = (
    ("cosmetic part", r"\b(EMBLEM|DECAL|STICKER|GRAPHIC|STRIPE|MARK|BADGE|ORNAMENT)"),
    (
        "wear part",
        r"\b(BRAKE ?PAD|PAD,? *BRAKE|BRAKE KIT|PAD SET|BRAKE SHOE|SHOE|DIS[CK],? *BRAKE|"
        r"BRAKE DIS[CK]|CHAIN|SPROCKET|"
        r"TYRE|TIRE|TUBE,? *(INNER|TIRE|TYRE)|INNER TUBE|FILTER|ELEMENT|SPARK ?PLUG|"
        r"PLUG,? *SPARK|S\. ?PLUG|V-?BELT|BELT|BEARING|OIL SEAL|SEAL|GASKET|O-?RING|"
        r"BULB|LAMP,? *(BULB|HEAD)|BATTERY|CABLE|LINING|PLATE,? *FRICTION|FRICTION PLATE|"
        r"CLUTCH PLATE|PLATE,? *CLUTCH|WEIGHT|ROLLER|SLIDER|GRIP|YAMALUBE|LUBRICANT|"
        r"GREASE|ANODE|IMPELLER|PISTON RING|RING SET|BRUSH)",
    ),
    (
        "service part",
        r"\b(BOLT|NUT|SCREW|WASHER|CLIP|CLAMP|COLLAR|SPRING|PIN|CIRCLIP|RIVET|GROMMET|"
        r"DAMPER|BUSH|BUSHING|SPACER|SHIM|STAY|BRACKET|BRKT|HOLDER|GUIDE|CAP|PLUG,? *(DRAIN|"
        r"BLIND)|HOSE|PIPE|JOINT|BAND|KEY|STOPPER|SEAT,? *SPRING|RETAINER|CUSHION|DOWEL)\b",
    ),
)

#: Layer 2/3 — catalogue section -> (system, behaviour class). Tested in order.
SECTION_RULES: tuple[tuple[str, str, str], ...] = (
    (r"MASTER CYLIN|CALIPER|BRAKE|WHEEL|HUB", "Wheels & Brakes", "chassis part"),
    (
        r"ELECTRICAL|FLASHER|HEADLIGHT|HEAD LIGHT|TAILLIGHT|TAIL LIGHT|METER|SWITCH|"
        r"STARTING MOTOR|HORN|BATTERY|WIRE|IGNITION",
        "Electrical",
        "electrical part",
    ),
    (
        r"CRANK|PISTON|CYLINDER|VALVE|CAMSHAFT|CLUTCH|TRANSMISSION|SHIFT|OIL PUMP|OIL COOLER|"
        r"STARTER|G?ENERATOR|WATER PUMP|RADIATOR|BALANCER|KICK|ENGINE|INTAKE|CARBURET|"
        r"THROTTLE|FUEL INJECT|AIR CLEANER|EXHAUST|MUFFLER|AIR SHROUD|FAN",
        "Engine",
        "engine part",
    ),
    (
        r"FENDER|LEG SHIELD|COWL|WINDSHIELD|FUEL TANK|STAND|FOOTREST|GUARD|PROTECTOR|"
        r"UNDER COVER|FRONT PANEL|MIRROR",
        "Body",
        "crash part",
    ),
    (r"SIDE COVER|SEAT|EMBLEM|GRAPHIC|MARK|COVER", "Body", "cosmetic part"),
    (
        r"FRONT FORK|FORK|STEERING|HANDLE|REAR ARM|SUSPENSION|FRAME|SWING",
        "Chassis",
        "chassis part",
    ),
)

#: Layer 4 — broader description keywords for what neither layer above placed.
DESCRIPTION_RULES: tuple[tuple[str, str, str], ...] = (
    (
        r"\b(SWITCH|WIRE|HARNESS|METER|TACHOMETER|SPEEDOMETER|CLOCK|(HEAD|TAIL)?LIGHT|LAMP|"
        r"FLASHER|WINKER|HORN|RELAY|RECTIFIER|REGULATOR|C\.? ?D\.? ?I\b|COIL|"
        r"IMMOBILI[SZ]ER|SENSOR|SOCKET|CORD|LEAD|SW\b|CONDENSER|CONTROL UNIT|"
        r"STARTER MOTOR|STARTING MOTOR|MAGNETO|STATOR|ROTOR|FUSE|ECU|UNIT,? *CONTROL)",
        "Electrical",
        "electrical part",
    ),
    (
        r"\b(PISTON|CRANK|CAMSHAFT|CYLINDER|VALVE|CARBURET|JET|NEEDLE|INJECT|CONNECTING ROD|"
        r"CRANKCASE|TAPPET|ROCKER|TIMING|OIL PUMP|CLUTCH|TRANSMISSION|GEAR|SHIFT|STARTER|"
        r"IGNIT|MANIFOLD|MUFFLER|EXHAUST|RADIATOR|WATER PUMP|THERMOSTAT|POWER ?HEAD|"
        r"LOWER UNIT|PROPELLER|GEARCASE|FLYWHEEL|THROTTLE|AIR CLEANER|INTAKE|NOZZ?LE|NOZZEL|"
        r"DIAPHRAGM|BREATHER|REMOTE CONTROL|TILLER|CARB|PINION|PINOIN|DRIVE SHAFT|"
        r"CAM ?SHAFT|CYL\b|FLOAT|AIR INDUCTION|INSULATOR)",
        "Engine",
        "engine part",
    ),
    (
        r"\b(FENDER|MUDGUARD|GUARD|COWL|CRASH|BUMPER|PROTECTOR|SHIELD|MIRROR|LEVER|"
        r"HANDLE ?BAR|FOOTREST|STAND|FUEL TANK|TANK,? *FUEL|WINDSHIELD|VISOR|PEDAL|SCOOP)",
        "Body",
        "crash part",
    ),
    (
        r"\b(GRAPHIC|EMBLEM|DECAL|STICKER|STRIPE|COVER|MARK|BADGE|ORNAMENT|PANEL|CASING|"
        r"LENS|TRIM|SEAT|MAT\b|MOLDING|MOULDING)",
        "Body",
        "cosmetic part",
    ),
    (
        r"\b(OUTER TUBE|TUBE,? *OUTER|FORK|STEERING|AXLE|FRAME|SWING ?ARM|REAR ARM|SUSPENSION|"
        r"ABSORBER|SHOCK|"
        r"HUB|WHEEL|RIM|SPOKE|CALIPER|MASTER CYLINDER|DISC)",
        "Chassis",
        "chassis part",
    ),
    (
        r"\b(PLATE|RING|ROD|LINK|WASHER|PATCH|HANGER|BODY|SUPPORT|TUBE)\b",
        "Unassigned",
        "service part",
    ),
)

_NATURE = tuple((label, re.compile(p, re.I)) for label, p in NATURE_RULES)
_SECTION = tuple((re.compile(p, re.I), system, label) for p, system, label in SECTION_RULES)
_DESCRIPTION = tuple((re.compile(p, re.I), system, label) for p, system, label in DESCRIPTION_RULES)

SOURCE_NATURE = "description: part nature"
SOURCE_SECTION = "catalogue section (part number)"
SOURCE_SECTION_BY_DESCRIPTION = "catalogue section (same description)"
SOURCE_KEYWORDS = "description keywords"
SOURCE_NONE = "none"


_GLUED_YAM = re.compile(r"(?<=[A-Z])(YAM(?:AHA)?)(?=[A-Z0-9 (]|$)")


def _text(value: object) -> str:
    """Upper-cased text with "YAM" split off a glued word ("CLAMPYAMYZF155" -> "CLAMP YAM…")."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return _GLUED_YAM.sub(r" \1", str(value).upper())


def nature_class(description: object) -> str | None:
    """Layer 1: a hardware or consumable description decides the class outright."""
    text = _text(description)
    for label, pattern in _NATURE:
        if pattern.search(text):
            return label
    return None


def section_class(section: object) -> tuple[str, str] | None:
    """Catalogue section -> (system, behaviour class), or None if the section is unmapped."""
    text = _text(section)
    for pattern, system, label in _SECTION:
        if pattern.search(text):
            return system, label
    return None


def keyword_class(description: object) -> tuple[str, str] | None:
    """Layer 4: broader description keywords -> (system, behaviour class)."""
    text = _text(description)
    for pattern, system, label in _DESCRIPTION:
        if pattern.search(text):
            return system, label
    return None


#: Consumables the catalogues do not place in an assembly: named for what they are.
CONSUMABLE_SYSTEMS: tuple[tuple[str, str], ...] = (
    (r"YAMALUBE|LUBRICANT|GREASE|\bOIL\b|COOLANT|BRAKE FLUID", "Lubricants"),
    (r"TYRE|TIRE|\bTUBE\b|INNER TUBE", "Tyres"),
    (r"BATTERY", "Electrical"),
)
_CONSUMABLE = tuple((re.compile(p, re.I), system) for p, system in CONSUMABLE_SYSTEMS)


def consumable_system(description: object) -> str | None:
    """System for a consumable (oil, tyre, battery) that no catalogue section places."""
    text = _text(description)
    for pattern, system in _CONSUMABLE:
        if pattern.search(text):
            return system
    return None


def description_key(values: pd.Series) -> pd.Series:
    """Letters and digits only, upper-cased, single-spaced — to match catalogue wording."""
    cleaned = values.fillna("").astype(str).str.upper().str.replace(r"[^A-Z0-9 ]", " ", regex=True)
    return cleaned.str.split().str.join(" ")


def classify_all(
    skus: pd.DataFrame,
    sku_sections: pd.Series,
    description_sections: pd.Series,
) -> pd.DataFrame:
    """Behaviour class, system and deciding source for every SKU.

    Args:
        skus: one row per ``active_sku_id`` with ``description`` and ``brand``.
        sku_sections: ``active_sku_id`` -> the catalogue section its numbers appear in
            most often.
        description_sections: normalised catalogue description -> its most-listed section.

    Business meaning: what a part is made of or for (a bolt, a brake pad) outranks where it
    is fitted; where it is fitted (the catalogue section) outranks loose wording; a part no
    layer can place is left unclassified rather than forced into a class.
    """
    rows: list[dict[str, object]] = []
    desc_keys = description_key(skus["description"])
    for (_, sku), key in zip(skus.iterrows(), desc_keys, strict=True):
        sku_id = sku["active_sku_id"]
        description = sku.get("description")
        # Every description in the chain is searched; old numbers often carry typos.
        text = sku.get("match_text") or description
        section = sku_sections.get(sku_id)
        by_description = description_sections.get(key) if key else None
        placed = section_class(section) or section_class(by_description)
        system = placed[0] if placed else None
        nature = nature_class(text)
        if nature:
            label, source = nature, SOURCE_NATURE
        elif section is not None and section_class(section):
            label, source = section_class(section)[1], SOURCE_SECTION  # type: ignore[index]
        elif by_description is not None and section_class(by_description):
            label, source = section_class(by_description)[1], SOURCE_SECTION_BY_DESCRIPTION  # type: ignore[index]
        elif keyword_class(text):
            system, label = keyword_class(text)  # type: ignore[misc]
            source = SOURCE_KEYWORDS
        else:
            label, source = UNCLASSIFIED, SOURCE_NONE
        if system is None:
            found = keyword_class(text)
            system = found[0] if found else None
        if system is None:
            system = consumable_system(text)
        if str(sku.get("brand") or "").upper() == "OB":
            system = "Outboard"
        rows.append(
            {
                "active_sku_id": sku_id,
                "behaviour_class": label,
                "behaviour_source": source,
                "system": system or "Unassigned",
                "catalogue_section": section if section is not None else by_description,
            }
        )
    return pd.DataFrame(rows)
