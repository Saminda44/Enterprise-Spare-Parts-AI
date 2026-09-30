"""Model-level unit forecast methods and the backtest that scores them."""

from __future__ import annotations

import pandas as pd
import pytest
from src.dashboard import unit_forecast


def _series(values: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame({"period": list(values), "actual_units": list(values.values())})


def test_horizon_follows_the_last_period() -> None:
    assert unit_forecast.horizon_after("2025-11", 3) == ["2025-12", "2026-01", "2026-02"]


def test_seasonal_run_rate_places_the_run_rate_on_the_profile() -> None:
    observed = _series({"2025-01": 100, "2025-02": 300})
    points = unit_forecast.seasonal_run_rate(observed, ["2026-01", "2026-02"])
    assert sum(points) == pytest.approx(400)  # mean 200 × 2 months
    assert points == pytest.approx([100, 300])  # January weight 1, February weight 3


def test_unseen_month_gets_the_profile_mean() -> None:
    observed = _series({"2025-01": 100, "2025-02": 300})
    points = unit_forecast.seasonal_run_rate(observed, ["2026-03"])
    assert points == pytest.approx([200])


def test_recent_average_uses_the_latest_months_flat() -> None:
    observed = _series({f"2025-{m:02d}": m * 10 for m in range(1, 9)})
    points = unit_forecast.recent_average(observed, ["2025-09", "2025-10"])
    assert points == pytest.approx([55, 55])  # mean of months 3..8


def test_backtest_never_sees_the_scored_months() -> None:
    actual = pd.DataFrame(
        {
            "period": ["2025-01", "2025-02", "2025-03", "2025-04", "2025-03"],
            "model": ["A", "A", "A", "A", "NEW"],
            "actual_units": [10, 10, 99, 99, 5],
        }
    )
    out = unit_forecast.backtest(actual, "2025-01", "2025-02", 3)
    a = out[out["model"] == "A"].set_index("period")
    assert list(a.index) == ["2025-03", "2025-04", "2025-05"]
    assert a["recent_average"].tolist() == pytest.approx([10, 10, 10])  # the 99s are unseen
    assert a["actual_units"].tolist()[:2] == [99, 99]
    assert pd.isna(a.loc["2025-05", "actual_units"])  # beyond the last observed month
    new = out[out["model"] == "NEW"]
    assert (new["train_months"] == 0).all()
    assert new["recent_average"].sum() == 0


def test_monthly_series_fills_gaps_after_first_sale() -> None:
    y = unit_forecast.monthly_series(_series({"2025-03": 5, "2025-05": 7}), "2025-06")
    assert y.to_dict() == {"2025-03": 5, "2025-04": 0, "2025-05": 7, "2025-06": 0}


def test_family_split_keeps_family_volume_and_follows_recent_mix() -> None:
    train = pd.DataFrame(
        {
            "period": ["2025-01", "2025-02", "2025-03", "2025-03"],
            "model": ["OLD", "OLD", "OLD", "NEW"],
            "actual_units": [90, 90, 30, 60],
        }
    )
    out = unit_forecast.family_split(train, {"OLD": "FZ", "NEW": "FZ"}, ["2025-04"])
    assert out["OLD"][0] + out["NEW"][0] == pytest.approx(90)  # family 3-month mean
    assert out["NEW"][0] == pytest.approx(90 * 60 / 270)  # NEW's share of the last 3 months


def test_every_method_scores_in_the_backtest() -> None:
    actual = pd.DataFrame(
        {
            "period": ["2025-01", "2025-02", "2025-03"],
            "model": ["A"] * 3,
            "actual_units": [10, 20, 30],
        }
    )
    out = unit_forecast.backtest(actual, "2025-01", "2025-02", 1, {"A": "FAM"})
    keys = [k for k, _ in unit_forecast.all_methods()]
    assert set(keys) <= set(out.columns)
    assert out[keys].notna().all(axis=None)


def test_damped_growth_is_capped_and_fades() -> None:
    rising = pd.Series([100, 100, 100, 200, 200, 200], dtype=float)  # far above the cap
    path = unit_forecast.damped_growth_path(rising, 24)
    first_step = path[0] - 1
    assert first_step == pytest.approx(unit_forecast.GROWTH_CAP * unit_forecast.GROWTH_DAMPING)
    steps = [path[i] / path[i - 1] - 1 for i in range(1, len(path))]
    assert all(b < a for a, b in zip(steps, steps[1:], strict=False))  # growth fades
    assert unit_forecast.damped_growth_path(rising.head(4), 3) == [1.0, 1.0, 1.0]  # too short


def test_family_growth_total_follows_level_times_growth() -> None:
    months = [f"2025-{m:02d}" for m in range(1, 7)]
    train = pd.DataFrame(
        {
            "period": months * 2,
            "model": ["A"] * 6 + ["B"] * 6,
            "actual_units": [50, 50, 50, 60, 60, 60] + [50, 50, 50, 60, 60, 60],
        }
    )
    horizon = ["2025-07", "2025-08"]
    out = unit_forecast.family_growth(train, {"A": "F", "B": "F"}, horizon)
    path = unit_forecast.damped_growth_path(pd.Series([100, 100, 100, 120, 120, 120.0]), 2)
    for i in range(2):
        assert out["A"][i] + out["B"][i] == pytest.approx(120 * path[i])
    assert out["A"][0] == pytest.approx(out["B"][0])


def test_band_beyond_scored_horizon_widens_in_log_space() -> None:
    bands = {1: (0.9, 1.1), 6: (0.8, 1.25)}
    assert unit_forecast.band_at(bands, 6) == (0.8, 1.25)
    low, high = unit_forecast.band_at(bands, 12)
    assert low < 0.8 and high > 1.25
    assert (low * high) == pytest.approx(0.8 * 1.25)  # same centre, wider
    assert unit_forecast.band_at({}, 3) == (1.0, 1.0)  # no bands, no interval claimed


def test_band_ratios_score_only_unseen_months() -> None:
    months = [f"2025-{m:02d}" for m in range(1, 13)]
    actual = pd.DataFrame({"period": months, "model": ["A"] * 12, "actual_units": [100.0] * 12})
    bands = unit_forecast.band_ratios(actual, {"A": "F"})
    assert bands["total"]  # scored at least one horizon
    for low, high in bands["total"].values():
        assert low == pytest.approx(1.0) and high == pytest.approx(1.0)  # flat series: exact


def test_whole_unit_split_sums_exactly() -> None:
    parts = unit_forecast.whole_unit_split(50000, [13321, 9231, 7893, 1, 3, 4])
    assert sum(parts) == 50000
    assert all(isinstance(x, int) for x in parts)
    assert unit_forecast.whole_unit_split(10, [1, 1, 1]) in ([4, 3, 3], [3, 4, 3], [3, 3, 4])
    assert unit_forecast.whole_unit_split(0, [1, 2]) == [0, 0]


def test_recent_mix_uses_only_the_last_months() -> None:
    from src.dashboard.vehicles import recent_mix

    frame = pd.DataFrame(
        {
            "month": ["2025-01", "2025-02", "2025-03", "2025-03"],
            "model_name": ["A", "A", "A", "B"],
            "colour": ["RED", "RED", "BLUE", "RED"],
            "units": [1.0, 1.0, 1.0, 1.0],
        }
    )
    mix = recent_mix(frame, months=2)
    assert set(mix["window_start"]) == {"2025-02"}
    assert mix.set_index(["model_name", "colour"])["units"].to_dict() == {
        ("A", "BLUE"): 1.0,
        ("A", "RED"): 1.0,
        ("B", "RED"): 1.0,
    }


def test_age_bucket_sort_key() -> None:
    from src.dashboard.vehicles import _age_start

    buckets = ["15+", "0-1", "10-11", "2-3"]
    assert sorted(buckets, key=_age_start) == ["0-1", "2-3", "10-11", "15+"]


def test_behaviour_layers_nature_then_catalogue_then_keywords() -> None:
    from src.parts import behaviour as bh

    skus = pd.DataFrame(
        {
            "active_sku_id": ["BOLT-1", "CAT-1", "DESC-1", "KEY-1", "NONE-1", "OB-1", "MARK-1"],
            "description": [
                "BOLT, FLANGE",
                "REED VALVE ASSY",
                "LEVER 1",
                "C.D.I. UNIT ASSY",
                "MOLE 1",
                "SHAFT",
                "TUNING FORK MARK",
            ],
            "brand": ["YM", "YM", "YM", "YM", "YM", "OB", "YM"],
        }
    )
    sku_sections = pd.Series({"BOLT-1": "CYLINDER", "CAT-1": "CYLINDER", "MARK-1": "LEG SHIELD"})
    desc_sections = pd.Series({"LEVER 1": "STAND & FOOTREST"})
    out = bh.classify_all(skus, sku_sections, desc_sections).set_index("active_sku_id")
    assert out.at["BOLT-1", "behaviour_class"] == "service part"  # nature beats section
    assert out.at["BOLT-1", "system"] == "Engine"  # but the section still names the system
    assert out.at["CAT-1", "behaviour_class"] == "engine part"
    assert out.at["CAT-1", "behaviour_source"] == bh.SOURCE_SECTION
    assert out.at["DESC-1", "behaviour_source"] == bh.SOURCE_SECTION_BY_DESCRIPTION
    assert out.at["KEY-1", "behaviour_class"] == "electrical part"
    assert out.at["NONE-1", "behaviour_class"] == bh.UNCLASSIFIED
    assert out.at["OB-1", "system"] == "Outboard"
    assert out.at["MARK-1", "behaviour_class"] == "cosmetic part"


def test_price_bands_cover_every_price() -> None:
    from src.dashboard.vehicles import price_band

    assert price_band(584_661) == "Under 600K"
    assert price_band(699_068) == "600K–800K"
    assert price_band(906_695) == "800K–1M"
    assert price_band(1_042_288) == "1M–1.2M"
    assert price_band(1_402_458) == "Over 1.2M"


def test_buyer_age_bands_and_implausible_ages() -> None:
    from src.dashboard.vehicles import UNKNOWN_AGE, buyer_age_band

    assert buyer_age_band(16) == "16–20"
    assert buyer_age_band(25) == "21–25"
    assert buyer_age_band(40) == "36–45"
    assert buyer_age_band(70) == "66+"
    assert buyer_age_band(116) == UNKNOWN_AGE  # a recording error, not a buyer
    assert buyer_age_band(float("nan")) == UNKNOWN_AGE


def test_segments_follow_the_current_numbers_brand() -> None:
    from src.dashboard.segments import segment_of_material_group, sku_segments

    master = pd.DataFrame(
        {
            "material": ["OLD-1", "NEW-1", "YM-2", "KT-3"],
            "active_sku_id": ["NEW-1", "NEW-1", "YM-2", "KT-3"],
            "brand": ["YM", "OB", "YM", "KT"],
            "chain_depth": [1, 0, 0, 0],
        }
    )
    seg = sku_segments(master)
    assert seg["NEW-1"] == "OBM"  # an old YM number superseded by an outboard part
    assert seg["YM-2"] == "MC" and seg["KT-3"] == "MC"
    groups = pd.Series(["AWPOB0014", "AWPYM0021", "AWLCA0011"])
    assert segment_of_material_group(groups).tolist() == ["OBM", "MC", "MC"]


def test_mc_categories_follow_the_material_category_rule() -> None:
    from src.dashboard.segments import part_category, sales_category

    desc = pd.Series(
        ["YAMALUBE 10W40", "KARATE BATTERY", "90/100-10 KATANA TYRE", "BRAKE PAD", "S. PLUG"]
    )
    seg = pd.Series(["MC", "MC", "MC", "MC", "OBM"])
    assert part_category(desc, seg).tolist() == [
        "Lubricant",
        "Battery",
        "Tyre",
        "Spare Parts",
        "OBM Spare Parts",
    ]
    # Billed sales: another brand's oil is a lubricant, not a spare part.
    sales = sales_category(
        pd.Series(["CASTROL GTX 10W30", "BOLT"]),
        pd.Series(["AWLCA0011", "AWPYM0001"]),
        pd.Series(["MC", "MC"]),
    )
    assert sales.tolist() == ["Lubricant", "Spare Parts"]


def test_vehicle_search_ignores_spaces_and_dashes() -> None:
    from src.api.compat.bikes import VEHICLE_SEARCH_MIN_CHARS, _clean_id

    assert _clean_id(" me1-se 12a ") == "ME1SE12A"
    assert len(_clean_id("ab")) < VEHICLE_SEARCH_MIN_CHARS  # too short to search
