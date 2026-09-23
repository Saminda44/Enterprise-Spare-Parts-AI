"""Import every step module so it registers itself into the global DAG.

Importing this module is what populates :data:`src.core.registry.REGISTRY`.
"""

from __future__ import annotations

import importlib

#: Step modules in dependency order. Each registers via @REGISTRY.register on import.
STEP_MODULES = (
    "src.catalogue.stage",  # 01
    "src.parts.master",  # 02
    "src.demand.orders",  # 03
    "src.demand.sales",  # 04
    "src.demand.order_analysis",  # 05
    "src.parts.classify",  # 06
    "src.forecast.backtest",  # 07
    "src.forecast.parc_demand",  # 08
    "src.parc.unit_sales",  # 09
    "src.parc.cohorts",  # 10
    "src.parc.targets",  # 11
    "src.inventory.stock",  # 12
    "src.inventory.policy",  # 13
    "src.inventory.ordering",  # 14
)


def load_stages() -> None:
    for module in STEP_MODULES:
        importlib.import_module(module)
