"""Owner-confirmed replenishment defaults."""

from datetime import date

from src.core.settings import Settings


def test_lead_and_on_order_arrival_defaults(monkeypatch) -> None:
    monkeypatch.delenv("SPI_LEAD_TIME_MONTHS", raising=False)
    monkeypatch.delenv("SPI_ON_ORDER_INTERPRETATION", raising=False)
    settings = Settings(_env_file=None)

    assert settings.lead_time_months == 4
    assert settings.review_period_months == 1
    assert settings.on_order_interpretation == "arrival"
    assert settings.stock_snapshot_as_of == date(2026, 9, 30)
    assert settings.on_orders_verified_complete is True
