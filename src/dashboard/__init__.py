"""Legacy-dashboard compatibility marts.

The original React dashboard speaks a ``/api/v1`` contract that predates the 16-step
rework: it asks for ``material_9``, ``policy_tier``, ``stock_status``, ``order_urgency``
and a pile of EDA cuts that the new facts do not carry under those names.

Rather than compute any of that inside a request handler — the service rule is that the
API serves published marts and computes nothing — the reshaping happens here, in a stage
that reads the new facts and writes marts in the shape the UI already knows. The API
layer under ``src/api/compat`` then only selects and renames.
"""
