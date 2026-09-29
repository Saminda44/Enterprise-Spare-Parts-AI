"""Catalogue database configuration defaults."""

from src.core.settings import Settings


def test_catalogue_database_matches_example_configuration(monkeypatch) -> None:
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    assert Settings(_env_file=None).postgres_db == "spare_parts"
