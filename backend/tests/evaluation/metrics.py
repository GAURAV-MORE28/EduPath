"""Shared metric recorder + gold-set loader for the evaluation suite."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

METRICS: list[dict[str, Any]] = []
GOLD_DIR = Path(__file__).parent / "gold"


def record(area: str, metric: str, value: float | int | str, target: str = "", note: str = "") -> None:
    if isinstance(value, float):
        value = round(value, 4)
    METRICS.append({"area": area, "metric": metric, "value": value, "target": target, "note": note})


def load_gold(name: str) -> Any:
    return json.loads((GOLD_DIR / name).read_text(encoding="utf-8"))
