"""Catalog ingestion (design §35's package-per-responsibility convention;
ARCHITECTURE_CONTRACTS.md §5). Loads the offline-curated domain-pack JSON
(`data/dataset/*.json`) into the Postgres graph/catalog tables, validating
graph invariants (`app/graph/validation.py`) before anything is written.
"""
