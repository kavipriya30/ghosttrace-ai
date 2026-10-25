import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))).resolve()
OUTPUT_PATH = Path(os.getenv("OUTPUT_PATH", str(BASE_DIR / "output.csv"))).resolve()

# IMPORTANT: Replace this ordered list with the exact schema from problem_statement.md.
# The exporter intentionally keeps this in one obvious place so it is easy to validate.
OUTPUT_COLUMNS = [
    "request_id",
    "status",
    "remaining_records",
    "recreation_paths",
    "remediation_steps",
    "evidence_summary",
]
