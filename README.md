# GhostTrace AI — Full-stack Deletion Audit Agent

A runnable React + FastAPI starter for the Northstar Shop deletion-audit challenge. It includes a dark dashboard, CSV ingestion, evidence scanning across CSV/text/JSON files, policy-aware audit logic, evaluation workflow, and CSV export.

> Important: The challenge's `problem_statement.md` defines the authoritative output schema and the dataset is required for meaningful predictions. This project deliberately does not hardcode challenge labels or pretend demo data is real. Before submission, copy the challenge corpus into `backend/data/` (or configure `DATA_DIR`) and align `OUTPUT_COLUMNS` in `backend/app/config.py` exactly with the required schema in the challenge statement.

## Features
- Overview dashboard and status breakdown (`COMPLETE`, `INCOMPLETE`, `NOT_APPLICABLE`)
- Request table with search and status filtering
- Per-request evidence inventory and ordered remediation suggestions
- CSV ingestion for deletion requests, deletion rules, and related evidence tables
- Local media/text scan (TXT, CSV, JSON, JSONL, log, MD; OCR is an optional extension)
- Detection of likely active recreation paths using evidence and sync/import/restore wording
- Evaluation endpoint that compares predictions to expected labels if a validation column exists
- Downloadable `output.csv`
- No API key required; deterministic rules-based baseline that can be enhanced with an LLM/VLM

## Requirements
- Node.js 18+
- Python 3.10+

## Run locally

### Backend
```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
API docs: http://localhost:8000/docs

### Frontend
In another terminal:
```bash
cd frontend
npm install
npm run dev
```
Open the Vite URL printed in the terminal (normally http://localhost:5173).

## Add the challenge data
Place the provided files under `backend/data/`, preserving their names where possible, for example:
- `deletion_requests.csv`
- `deletion_rules.csv`
- all evidence CSVs and local media files

Or set `DATA_DIR` to the dataset/corpus directory. The backend searches recursively. It excludes virtualenvs, node_modules, and output files.

## Output schema
Open `backend/app/config.py`. Set `OUTPUT_COLUMNS` to the exact ordered column names specified by the challenge `problem_statement.md`. The exporter preserves that order. The engine maps common field names (request ID, status, remaining records, evidence, remediation) when present; unmapped required columns are emitted as empty strings rather than fabricated facts.

## Evaluation
Use the UI's **Run evaluation** button or:
```bash
curl -X POST http://localhost:8000/api/evaluate
```
Evaluation checks for an expected/ground-truth status column in the request CSV, when present. It reports accuracy and a confusion matrix only when labels are available. It does not use expected labels to generate predictions.

## Submission checklist
1. Verify all requests are processed: `GET /api/requests`
2. Run evaluation and inspect errors.
3. Download `output.csv` and confirm the exact schema/order against the challenge statement.
4. Zip only your `code/` directory for the platform. Exclude virtualenvs, node_modules, build outputs, and data/corpus.
5. Include the platform-required `log.txt` chat transcript from the challenge logging instructions.
6. Do not upload demo-only results; use the supplied dataset.

## Limitations to discuss honestly
This is a transparent, explainable baseline rather than a production erasure service. It audits records and recommends actions; it does not directly delete data from real systems. CSV/text scanning cannot prove absence from opaque binary media or inaccessible backups. For production use, add OCR/VLM for images, connectors for each storage system, signed evidence receipts, and an approval-controlled deletion executor.
