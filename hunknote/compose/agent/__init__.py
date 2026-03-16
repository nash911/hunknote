"""Compose Agent — multi-phase LLM pipeline for intelligent commit splitting.

Activated via `hunknote compose --agent`. Replaces only the plan generation
logic; parsing, inventory, caching, execution, and rendering are reused
from the existing compose module.
"""
