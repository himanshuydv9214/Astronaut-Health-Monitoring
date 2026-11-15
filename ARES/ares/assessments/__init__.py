"""Permanent record of every astronaut test / assessment (PVT, wellness check-in, symptom report, lab panel).

store.py     - SQLite tables in the existing ares_history.db (migrated, foreign keys, indexes, transactions)
analysis.py  - metrics, personal baseline, comparison with previous tests, longitudinal trends (observed vs model)
export.py    - CSV and PDF reports (PDF via matplotlib, already a project dependency)
"""
