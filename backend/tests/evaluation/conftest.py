"""Evaluation harness (Phase 12, design §32).

Each evaluation test *measures* something against a gold set, records the number with
`record(...)`, and asserts a threshold. At the end of the session every recorded metric is
written to `backend/reports/evaluation_metrics.json` (+ a Markdown table) so the numbers in
`docs/FINAL_IMPLEMENTATION_STATUS.md` come from a run, not from memory.

    cd backend && python -m pytest tests/evaluation -q      # writes reports/evaluation_metrics.*
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.evaluation.metrics import METRICS

REPORT_DIR = Path(__file__).resolve().parents[2] / "reports"


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    if not METRICS:
        return
    REPORT_DIR.mkdir(exist_ok=True)
    (REPORT_DIR / "evaluation_metrics.json").write_text(json.dumps(METRICS, indent=2, default=str), encoding="utf-8")
    lines = ["| Area | Metric | Value | Target | Note |", "|---|---|---|---|---|"]
    for m in METRICS:
        lines.append(f"| {m['area']} | {m['metric']} | {m['value']} | {m['target']} | {m['note']} |")
    (REPORT_DIR / "evaluation_metrics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
