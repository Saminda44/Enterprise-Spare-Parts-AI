"""Catalogue browser reader: misprint repairs, side-by-side tables, colour rules."""

from __future__ import annotations

from typing import Any

import pytest
from src.catalogue.browser.overrides import override_for
from src.catalogue.browser.pdf_extractor import YamahaCatalogueExtractor as Reader
from src.catalogue.browser.remark_parser import parse_applicability


def _word(text: str, x0: float = 0.0, top: float = 0.0, width: float = 100.0) -> dict[str, Any]:
    return {"text": text, "x0": x0, "x1": x0 + width, "top": top}


def _split(text: str) -> list[str]:
    return [w["text"] for w in Reader._split_run_together_part_numbers([_word(text)])]


@pytest.mark.parametrize(
    ("printed", "read"),
    [
        ("10.5TS-E4710-00-00", ["10.", "5TS-E4710-00-00"]),
        ("1a)5KA-H3500-00-00", ["1a)", "5KA-H3500-00-00"]),
        ("5YY.F6331-00-00", ["5YY-F6331-00-00"]),
        ("5TS-F2211.00-00", ["5TS-F2211-00-00"]),
        ("4LS--F5355-00-00LEVERCAMSHAFT", ["4LS-F5355-00-00", "LEVERCAMSHAFT"]),
        ("4LS-E3451-00X-00", ["4LS-E3451-00-00"]),
        ("4LS-F3118-0-00", ["4LS-F3118-00-00"]),
        ("KIT-5YYWF514-00-00", ["KIT", "5YY-WF514-00-00"]),
        ("4LS-E-111F-00-00", ["4LS-E111F-00-00"]),
        ("5TS-WF151-00-00FRONT", ["5TS-WF151-00-00", "FRONT"]),
    ],
)
def test_misprinted_part_numbers_are_repaired(printed: str, read: list[str]) -> None:
    assert _split(printed) == read


@pytest.mark.parametrize(
    "clean", ["5TS-WF151-00-00", "93306-20215-00", "B65-F174G-C0", "5T-F2211-00", "SEAL,"]
)
def test_well_formed_tokens_pass_through(clean: str) -> None:
    assert _split(clean) == [clean]


def _table(x_ref: float, x_pn: float, n: int, prefix: str) -> list[dict[str, Any]]:
    words = []
    for i in range(n):
        top = 100.0 + 15 * i
        words.append(_word(str(i + 1), x_ref, top, 8))
        words.append(_word(f"{prefix}-E{1000 + i}-00-00", x_pn, top, 70))
        words.append(_word("GEAR", x_pn + 75, top, 30))
    return words


def test_two_tables_side_by_side_are_split() -> None:
    words = _table(88, 103, 4, "5TS") + _table(465, 485, 4, "5KA")
    halves = Reader._side_by_side_tables(words)
    assert len(halves) == 2
    assert {w["text"] for w in halves[1]} >= {"5KA-E1000-00-00", "5KA-E1003-00-00"}
    assert not any(w["text"].startswith("5KA") for w in halves[0])


def test_second_12_digit_column_without_refs_is_not_a_table() -> None:
    # An Escort / Superseded 12-digit column: no ref number beside it.
    words = _table(88, 103, 4, "5TS")
    words += [_word(f"5KA-E{2000 + i}-00-00", 600, 100.0 + 15 * i, 70) for i in range(4)]
    assert len(Reader._side_by_side_tables(words)) == 1


def test_multi_word_colour_in_remark_restricts() -> None:
    result = parse_applicability("FOR YAMAHA BLACK", {"YB", "YAMAHA BLACK"})
    assert not result.is_universal
    assert result.ordered == ["YAMAHA BLACK"]


def test_single_token_remark_grammar_unchanged() -> None:
    assert parse_applicability("LLGS6 FOR DBNM8", {"DBNM8"}).ordered == ["DBNM8"]
    assert parse_applicability("YB", {"YB"}).is_universal
    assert parse_applicability("EXCEPT SL3", {"SL3"}).is_except_mode


def _colour(abbr: str, name: str) -> dict[str, Any]:
    return {"code": "", "name": name, "abbreviation": abbr, "is_model_colour": False}


def test_unlisted_description_colours() -> None:
    table = [_colour("CNM", "Candy Maroon"), _colour("BG", "Black Gold")]
    rows = [
        # Three printings of one fender family, one of them in a table colour.
        {"part_no": "5TS-WF151-10-00", "colour_hint": "CNM", "colour_hint_source": "description"},
        {"part_no": "5TS-WF151-50-00", "colour_name_unmatched": "DEEP PURPLE"},
        {"part_no": "5TS-WF151-60-00", "colour_name_unmatched": "DEEP PURPLE BLUE METALLIC"},
        {"part_no": "5US-F1710-10-00", "colour_name_unmatched": "MAROON"},
        {"part_no": "95307-06700", "colour_name_unmatched": "YELLOW"},
        {"part_no": "21C-F4614-00-P0", "colour_name_unmatched": "SILVER"},
        {"part_no": "1WD-11656-00", "colour_name_unmatched": "BLUE PAINT MARK"},
        {
            "part_no": "5TS-F1720-80-00",
            "colour_name_unmatched": "SILVER",
            "colour_hint": "BG",
            "colour_hint_source": "remarks",
        },
    ]
    out, colours = Reader._adopt_unlisted_desc_colours(rows, table)
    assert out[1]["colour_hint"] == out[2]["colour_hint"] == "DEEP PURPLE BLUE METALLIC"
    assert out[3]["colour_hint"] == "CNM"  # the one table colour containing MAROON
    assert "hardware" in out[4]["colour_ignored"]
    assert "finish" in out[5]["colour_ignored"]  # a lone silver plate is not a variant
    assert "marking" in out[6]["colour_ignored"]
    assert out[7]["colour_hint"] == "BG"  # the remark outranks the description
    added = [c for c in colours if c.get("source") == "description"]
    assert [c["abbreviation"] for c in added] == ["DEEP PURPLE BLUE METALLIC"]


def test_colour_name_glossing_a_code_is_the_code() -> None:
    table = [_colour("VRC1", "Vivid Red Cocktail 1")]
    rows = [
        {
            "part_no": "1GC-XF151-30-P8",
            "ref_no": "1",
            "section": "FENDER",
            "description": "FENDER, FRONT -CM6(cyan metallic",
            "colour_name_unmatched": "cyan metallic",
        },
        {
            "part_no": "1GC-XF151-40-P8",
            "ref_no": "1",
            "section": "FENDER",
            "description": "FENDER, FRONT -VRC1",
            "colour_hint": "VRC1",
        },
        {
            "part_no": "5TS-F1710-40-00",
            "ref_no": "2",
            "section": "SIDE COVER",
            "description": "COVER, SIDE ASSY1(YAMAHA BLACK )",
            "colour_name_unmatched": "YAMAHA BLACK",
        },
    ]
    out, _ = Reader._adopt_unlisted_desc_colours(rows, table)
    assert out[0]["colour_hint"] == "CM6"
    assert out[2].get("colour_hint") != "ASSY1"


def test_declared_overrides() -> None:
    from pathlib import Path

    ybx = override_for(Path("x/MC/YBX/YBX125.pdf"))
    assert [c.abbreviation for c in ybx.colour_table] == ["BG", "DPRC3", "DPBMC"]
    crux = override_for(Path("x/MC/CRUX/Crux_ Crux R Parts Catalogue_New 5ka1.pdf"))
    assert crux.excluded_sections[0][0] == "PARTS EXCLUSIVE TO CRUX (5KA2)"
    assert override_for(Path("x/MC/LIBERO/LIBERO  G5.pdf")).drop_kit_rows
    assert override_for(Path("x/MC/R 15/R15 1CK5.pdf")).excluded_reason


def test_product_folder_layout(tmp_path) -> None:
    from pathlib import Path

    from src.catalogue.browser.overrides import (
        model_folder_of,
        model_folders,
        product_type_of,
        relative_key,
    )

    assert relative_key(Path("root/MC/AEROX/B65L.pdf")) == "MC/AEROX/B65L.pdf"
    assert relative_key(Path("root/OBM/F40/F40FETL.pdf")) == "OBM/F40/F40FETL.pdf"
    assert product_type_of("OBM/F40/F40FETL.pdf") == "OBM"
    assert product_type_of("MC/FZ & FZS/x.pdf") == "MC"
    assert model_folder_of("OBM/F40/F40FETL.pdf") == "F40"
    assert model_folder_of("MC/FZ & FZS/x.pdf") == "FZ & FZS"
    for rel in ("MC/AEROX", "MC/FZ & FZS", "OBM/F40"):
        (tmp_path / rel).mkdir(parents=True)
    found = [(p, f.name) for p, f in model_folders(tmp_path)]
    assert found == [("MC", "AEROX"), ("MC", "FZ & FZS"), ("OBM", "F40")]


@pytest.mark.parametrize(
    ("desc", "text", "code", "cleaned"),
    [
        ("CAST WHEEL, FRONT-CALM YELLOW", "CALM YELLOW", "CALM YELLOW", "CAST WHEEL, FRONT"),
        ("FRONT FENDER (YAMAHA BLACK)", "YAMAHA BLACK", "YAMAHA BLACK", "FRONT FENDER"),
        ("FRONT FENDER (LIGHT YELLOW", "LIGHT YELLOW", "LYNM9", "FRONT FENDER"),
        ("PANEL 1 - S8 (Silver)", "Silver", "S8", "PANEL 1"),
        ("COVER ASSY.", "SILVER", "SILVER", "COVER ASSY."),  # colour not at the end
    ],
)
def test_colour_suffix_is_cut_from_description(
    desc: str, text: str, code: str, cleaned: str
) -> None:
    from src.catalogue.browser.pdf_extractor import _strip_colour_suffix

    assert _strip_colour_suffix(desc, text, code) == cleaned


def test_quantity_glued_to_a_colour_code_is_split() -> None:
    rows = [
        {"description": "CAST WHEEL, REAR -YB FOR LGM61", "qty": ""},
        {"description": "SCOOP & GUIDE AIR 1 -VRC1 FOR BWCQ11", "qty": ""},
        {"description": "COVER, SIDE 3 -S3", "qty": ""},  # S3 is itself a colour code
    ]
    assert Reader._split_glued_colour_qty(rows, {"YB", "LGM6", "BWC1", "S3"}) == 2
    assert (rows[0]["description"], rows[0]["qty"]) == ("CAST WHEEL, REAR -YB FOR LGM6", "1")
    assert (rows[1]["description"], rows[1]["qty"]) == ("SCOOP & GUIDE AIR 1 -VRC1 FOR BWC1", "1")
    assert rows[2]["qty"] == ""


def test_missing_quantity_is_taken_as_one_except_kits() -> None:
    rows = [
        {"part_no": "4LS-F4524-00-00", "description": "LEVER, COCK", "qty": ""},
        {"part_no": "5DGE44120000", "description": "CAP,CLEANER CASE1", "qty": "///"},
        {"part_no": "5US-W0045-00-00", "description": "BRAKE PAD KIT", "qty": ""},
        {"part_no": "5YY-F5130-00-00", "description": "BRAKE SHOE 1", "qty": "", "kit_note": True},
        {"part_no": "2FB-E1191-00", "description": "COVER, CYLINDER HEAD 1", "qty": "1"},
    ]
    assert Reader._assume_missing_qty(rows) == 2
    assert [r["qty"] for r in rows] == ["1", "1", "", "", "1"]
    assert rows[0]["qty_assumed"] and "qty_assumed" not in rows[4]


def test_description_words_are_not_part_numbers() -> None:
    from src.catalogue.browser.pdf_extractor import _PN_PAT

    assert not _PN_PAT.search("CAST WHEEL, FRONT-CALM YELLOW")
    assert not _PN_PAT.search("CAST WHEEL, FRONT-VRC1")
    for pn in ("93306-20215", "95E32-06010", "5TS-WF151-00-00", "B65-F174G-C0"):
        assert _PN_PAT.search(pn).group(1) == pn


def test_suffix_colours_dropped_where_descriptions_contradict_them() -> None:
    suffix_map = {"00": "BG", "10": "CNM"}
    rows = [
        {
            "part_no": "5TM-F8350-10-00",
            "desc_colour": "SILVER",
            "colour_hint": "SILVER",
            "colour_hint_source": "description",
        },
        {
            "part_no": "5TM-F4845-10-00",
            "desc_colour": "GREEN",
            "colour_hint": "GREEN",
            "colour_hint_source": "description",
        },
        {
            "part_no": "5DG-F4845-00-00",
            "desc_colour": "BG",
            "colour_hint": "BG",
            "colour_hint_source": "suffix",
        },
        {
            "part_no": "5KA-H3500-10-00",
            "description": "METER ASSY (JNS INST LTD)",
            "colour_hint": "CNM",
            "colour_hint_source": "suffix",
        },
    ]
    assert Reader._drop_unreliable_suffix_hints(rows, suffix_map)
    assert rows[2]["colour_hint"] == "BG"  # its description says so
    assert "colour_hint" not in rows[3]


def test_store_explodes_rows_per_model() -> None:
    from pathlib import Path

    from src.catalogue.browser.pdf_extractor import ExtractionResult
    from src.catalogue.store import _explode

    result = ExtractionResult(
        pdf_path=Path("x.pdf"),
        model="AEROX",
        rows=[
            {"part_no": "B65-F1511-00", "description": "FENDER", "qty": "1/1//"},
            {"part_no": "B65-F1512-00", "description": "STAY", "qty": "2"},
            {
                "part_no": "5YY-F5130-00-00",
                "description": "BRAKE SHOE 1",
                "qty": "",
                "kit_note": True,
            },
        ],
        pages_scanned=1,
        sections_found=1,
        ocr_flagged=0,
        variants=["B65J", "B65L", "B65M", "B65N"],
    )
    records = _explode(result)
    fender = [(r["model_code"], r["quantity"]) for r in records if r["row_no"] == 0]
    stay = [(r["model_code"], r["quantity"]) for r in records if r["row_no"] == 1]
    kit = [r for r in records if r["row_no"] == 2]
    assert fender == [("B65J", 1), ("B65L", 1)]
    assert stay == [("B65J", 2), ("B65L", 2), ("B65M", 2), ("B65N", 2)]
    assert len(kit) == 1 and kit[0]["model_code"] is None and kit[0]["row_kind"] == "kit_note"


def test_material_key_ignores_separators() -> None:
    from src.catalogue.store import material_key

    assert material_key("B65-E3907-10") == material_key("B65E390710") == "B65E390710"
    assert material_key(" 5dg-e4412-00 ") == "5DGE441200"


@pytest.mark.parametrize(
    ("text", "number"),
    [("PARTS CATALOGUE 1UB9E-470EA", "1UB9E-470EA"), ("1SB62 - 470EA", "1SB62-470EA")],
)
def test_catalogue_number_on_cover(text: str, number: str) -> None:
    from src.catalogue.browser.pdf_extractor import _CATALOGUE_NO

    m = _CATALOGUE_NO.search(text)
    assert m and f"{m.group(1)}-{m.group(2)}" == number


def test_catalogue_number_in_file_name() -> None:
    from src.catalogue.browser.pdf_extractor import _CATALOGUE_NO_GLUED

    m = _CATALOGUE_NO_GLUED.search("1UB65460EV-AEROX")
    assert m and f"{m.group(1)}-{m.group(2)}" == "1UB65-460EV"
    assert not _CATALOGUE_NO_GLUED.search("YZF-R15 2FB5 PC")


def test_ten_and_twelve_digit_forms_are_one_part() -> None:
    from src.catalogue.store import material_key, material_key_forms

    assert "B65E39071000" in material_key_forms(material_key("B65-E3907-10"))
    assert "B65E390710" in material_key_forms(material_key("B65-E3907-10-00"))
    assert material_key_forms("B65E3907P1") == ["B65E3907P1", "B65E3907P100"]
    assert material_key_forms("B65F174GC011") == ["B65F174GC011"]  # not ending 00: one form


def test_pn_yamaha_columns_declared() -> None:
    from src.catalogue.store import PN_YAMAHA_BRAND, PN_YAMAHA_COLUMNS

    assert PN_YAMAHA_BRAND == "YM"
    assert list(PN_YAMAHA_COLUMNS)[:3] == ["Material", "Latest SS", "Material description"]
    assert PN_YAMAHA_COLUMNS["10th Supersede"] == "supersede_10"
    assert len(PN_YAMAHA_COLUMNS) == 13
