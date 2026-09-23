"""Source reading: Excel to parquet once, the SAP glued-column parser, layer access."""

from src.io.sap import GLUED_COLUMNS, GluedColumn, split_code_label, split_columns, split_for_source

__all__ = [
    "GLUED_COLUMNS",
    "GluedColumn",
    "split_code_label",
    "split_columns",
    "split_for_source",
]
