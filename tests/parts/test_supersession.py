"""Supersession identity and the labelled lookup."""

from __future__ import annotations

import pandas as pd
import pytest
from src.parts.supersession import (
    SupersessionCycleError,
    SupersessionLookup,
    build_successor_map,
    normalise,
    resolve_chains,
    walk,
)


def test_normalise_is_dash_insensitive() -> None:
    assert normalise("5VL-F341E-00") == normalise("5VLF341E00") == "5VLF341E00"
    assert normalise(None) == ""


def _frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    columns = [
        "Material",
        "Latest SS",
        "Material description",
        "active_sku_id",
        *[f"{n} Supersede" for n in ("1st", "2nd")],
    ]
    return pd.DataFrame(rows).reindex(columns=columns)


def test_successor_edge_runs_from_superseded_to_current() -> None:
    frame = _frame([{"Material": "NEW-1", "1st Supersede": "OLD-1", "Latest SS": "NEW-1"}])
    assert build_successor_map(frame)[normalise("OLD-1")] == "NEW-1"


def test_walk_reaches_the_terminal_node() -> None:
    successor = {normalise("A-1"): "B-1", normalise("B-1"): "C-1"}
    terminal, chain, depth = walk("A-1", successor)

    assert terminal == "C-1"
    assert chain == ["A-1", "B-1", "C-1"]
    assert depth == 2


def test_cycle_is_detected_rather_than_looping_forever() -> None:
    successor = {normalise("A-1"): "B-1", normalise("B-1"): "A-1"}
    with pytest.raises(SupersessionCycleError, match="cycle"):
        walk("A-1", successor)


def test_resolve_uses_latest_ss_and_flags_disagreement() -> None:
    frame = _frame(
        [
            {"Material": "OLD-1", "Latest SS": "NEW-1"},
            {"Material": "NEW-1", "Latest SS": "NEW-1", "1st Supersede": "OLD-1"},
        ]
    )
    resolutions, cycles = resolve_chains(frame)

    assert cycles == []
    assert all(r.active_sku_id == "NEW-1" for r in resolutions), "one identity per part"
    assert resolutions[0].agrees_with_latest_ss, "chain and Latest SS agree"


def test_lookup_labels_every_member_of_the_chain() -> None:
    frame = _frame(
        [
            {
                "Material": "5VL-F341E-10",
                "Latest SS": "5VL-F341E-10",
                "active_sku_id": "5VL-F341E-10",
                "Material description": "DISC, BRAKE",
                "1st Supersede": "5VL-F341E-00",
            }
        ]
    )
    hits = {h.part_no: h.label for h in SupersessionLookup(frame).lookup("5VL-F341E-00")}

    assert hits["5VL-F341E-00"] == "QUERIED"
    assert hits["5VL-F341E-10"] == "CURRENT"


def test_lookup_is_dash_insensitive_and_supports_partials() -> None:
    frame = _frame(
        [
            {
                "Material": "5VL-F341E-10",
                "Latest SS": "5VL-F341E-10",
                "active_sku_id": "5VL-F341E-10",
                "1st Supersede": "5VL-F341E-00",
            }
        ]
    )
    lookup = SupersessionLookup(frame)

    dashed = {h.part_no for h in lookup.lookup("5VL-F341E-10")}
    undashed = {h.part_no for h in lookup.lookup("5VLF341E10")}
    partial = {h.part_no for h in lookup.lookup("5VL-F341E")}

    assert dashed == undashed, "with or without dashes gives the same answer"
    assert partial >= dashed, "a partial number matches all its versions"


def test_unknown_number_returns_nothing_rather_than_a_guess() -> None:
    """A wrong supersession merge corrupts every downstream demand series."""
    frame = _frame([{"Material": "A-1", "Latest SS": "A-1", "active_sku_id": "A-1"}])
    assert SupersessionLookup(frame).lookup("ZZZZ-99999-99") == []


def test_lookup_handles_lowercased_part_master_columns() -> None:
    """part_master renames Material to material; the lookup must still build."""
    frame = pd.DataFrame([{"material": "A-1", "active_sku_id": "A-1", "description": "WIDGET"}])
    hits = SupersessionLookup(frame).lookup("A-1")

    assert [h.label for h in hits] == ["QUERIED"]
    assert hits[0].description == "WIDGET"
