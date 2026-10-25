from __future__ import annotations
import csv, json, re
from pathlib import Path
from typing import Any
import pandas as pd
from .config import DATA_DIR, OUTPUT_COLUMNS

REQUEST_NAMES = {"deletion_requests.csv", "svgdeletion_requests.csv"}
RULE_NAMES = {"deletion_rules.csv"}
SUPPORTED_TEXT = {".csv", ".txt", ".json", ".jsonl", ".log", ".md", ".tsv"}
SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist"}

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.I)
SYNC_TERMS = ("sync", "synchroniz", "replicat", "import job", "restore", "re-ingest", "reingest", "recreate", "recreated", "backfill", "etl", "pipeline")
DELETE_TERMS = ("delete", "deletion", "erase", "erasure", "redact", "anonym")
RETAIN_TERMS = ("retain", "retention", "legal hold", "must keep", "keep record", "tax", "transaction record")

def _norm(x: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(x or "").strip().lower()).strip("_")

def _first(row: dict, names: list[str], default=""):
    by_norm = {_norm(k): v for k, v in row.items()}
    for name in names:
        val = by_norm.get(_norm(name))
        if val is not None and str(val).strip() and str(val).lower() != "nan":
            return val
    return default

def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1","true","yes","y","requested","delete","deletion_requested"}

def discover_files(data_dir: Path = DATA_DIR):
    found = []
    if not data_dir.exists():
        return found
    for p in data_dir.rglob("*"):
        if not p.is_file() or any(part in SKIP_PARTS for part in p.parts):
            continue
        if p.name.lower() in {"output.csv", "predictions.csv"}:
            continue
        if p.suffix.lower() in SUPPORTED_TEXT:
            found.append(p)
    return sorted(found)

def _read_table(path: Path) -> pd.DataFrame:
    try:
        if path.suffix.lower() == ".json":
            obj = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(obj, dict):
                for key in ("records", "data", "items", "rows"):
                    if isinstance(obj.get(key), list):
                        obj = obj[key]; break
            return pd.json_normalize(obj if isinstance(obj, list) else [obj])
        if path.suffix.lower() == ".jsonl":
            return pd.read_json(path, lines=True)
        sep = "\t" if path.suffix.lower() == ".tsv" else None
        return pd.read_csv(path, sep=sep, engine="python", on_bad_lines="skip", dtype=str).fillna("")
    except Exception:
        return pd.DataFrame()

def _find_requests(files):
    # Prefer the explicitly named request file, not any evidence table that happens to contain "request".
    candidates = [p for p in files if p.name.lower() in REQUEST_NAMES]
    if not candidates:
        candidates = [p for p in files if "deletion_request" in p.name.lower() and p.suffix.lower() == ".csv"]
    if not candidates:
        return None, pd.DataFrame()
    # dataset/deletion_requests.csv is generally authoritative when present.
    candidates.sort(key=lambda p: (0 if p.name.lower() == "deletion_requests.csv" else 1, len(str(p))))
    p = candidates[0]
    return p, _read_table(p)

def _find_rules(files):
    candidates = [p for p in files if p.name.lower() in RULE_NAMES]
    return [(p, _read_table(p)) for p in candidates]

def _row_text(row: dict) -> str:
    return " | ".join(f"{k}: {v}" for k, v in row.items() if str(v).strip().lower() not in {"", "nan", "none"})

def _identity_values(req: dict):
    vals = []
    keys = ("email","user_email","customer_email","name","full_name","customer_id","user_id","account_id","phone","identifier","current_identifier","historical_identifier","old_email","previous_email")
    for k, v in req.items():
        nk = _norm(k)
        if any(token in nk for token in keys) and str(v).strip() and str(v).lower() != "nan":
            vals.append(str(v).strip())
    # Also use email/UUID identifiers discoverable from request text.
    raw = _row_text(req)
    vals.extend(EMAIL_RE.findall(raw))
    vals.extend(UUID_RE.findall(raw))
    unique = []
    for val in vals:
        if val not in unique and len(val) > 1:
            unique.append(val)
    return unique

def _is_deletion_requested(req: dict) -> bool:
    text = " ".join(f"{k} {v}" for k,v in req.items()).lower()
    for k,v in req.items():
        nk = _norm(k)
        if any(s in nk for s in ("deletion_requested","delete_requested","request_type","action","intent","request_status")):
            val = str(v).strip().lower()
            if any(word in val for word in ("not requested","no deletion","do not delete","cancelled","canceled","withdrawn")):
                return False
            if any(word in val for word in ("delete","deletion","erase","erasure","requested")):
                return True
    # Use explicit boolean-like columns if present.
    for k,v in req.items():
        nk = _norm(k)
        if nk in {"deletion_requested","delete_requested","has_deletion_request"}:
            return _as_bool(v)
    # Default is a deletion request unless the record explicitly says otherwise.
    return not any(x in text for x in ("no deletion requested", "deletion not requested", "request_type: none"))

def _matches_identity(text: str, identifiers: list[str]) -> list[str]:
    low = text.lower()
    return [x for x in identifiers if len(x) >= 3 and x.lower() in low]

def _rules_for_text(rules, text):
    # Pull matching rule rows based on broad system/data-treatment fields.
    matched = []
    for file, df in rules:
        for row in df.to_dict(orient="records"):
            rtext = _row_text(row).lower()
            # Treat a rule as relevant if it references a system/data category found in evidence,
            # or if its action describes a general retention/deletion requirement.
            terms = [str(v).strip().lower() for k,v in row.items() if str(v).strip() and _norm(k) in {
                "system","system_name","data_type","record_type","storage_location","category","copy_type","identifier"
            }]
            if (terms and any(t in text.lower() for t in terms if len(t) > 2)) or any(t in rtext for t in RETAIN_TERMS + ("must delete","must redact","must anonymize")):
                matched.append(row)
    return matched

def audit_one(req: dict, all_files, rules, request_file: Path | None = None):
    req_id = _first(req, ["request_id","deletion_request_id","requestid","id","ticket_id"], "unknown")
    identifiers = _identity_values(req)
    requested = _is_deletion_requested(req)
    evidence = []
    processes = []
    retention = []
    matched_records = 0
    all_text = []
    for p in all_files:
        if request_file and p.resolve() == request_file.resolve():
            continue
        # Do not treat rules as evidence copies, but keep them available for policy evaluation.
        if p.name.lower() in RULE_NAMES:
            continue
        df = _read_table(p) if p.suffix.lower() in {".csv",".tsv",".json",".jsonl"} else pd.DataFrame()
        if not df.empty:
            for idx, row in enumerate(df.to_dict(orient="records")):
                txt = _row_text(row)
                hits = _matches_identity(txt, identifiers)
                if hits:
                    matched_records += 1
                    snippet = txt[:450]
                    treatment = _rules_for_text(rules, txt)
                    rec = {"source": p.name, "record_id": str(idx + 2), "summary": snippet, "identifiers": hits,
                           "retention_signal": any(t in txt.lower() for t in RETAIN_TERMS),
                           "process_signal": any(t in txt.lower() for t in SYNC_TERMS)}
                    evidence.append(rec)
                    if rec["retention_signal"]:
                        retention.append(rec)
                    if rec["process_signal"]:
                        processes.append({"name": p.name, "source": f"{p.name}: row {idx+2}", "detail": snippet[:250], "risk":"HIGH"})
        else:
            try: txt = p.read_text(encoding="utf-8", errors="ignore")
            except Exception: continue
            hits = _matches_identity(txt, identifiers)
            if hits:
                matched_records += 1
                evidence.append({"source":p.name,"record_id":"file","summary":f"Identity string found in text file: {', '.join(hits)}","identifiers":hits,
                                 "retention_signal":any(t in txt.lower() for t in RETAIN_TERMS),
                                 "process_signal":any(t in txt.lower() for t in SYNC_TERMS)})
                for line_no, line in enumerate(txt.splitlines(), 1):
                    if _matches_identity(line, identifiers) and any(t in line.lower() for t in SYNC_TERMS):
                        processes.append({"name":p.name,"source":f"{p.name}: line {line_no}","detail":line[:250],"risk":"HIGH"})
        all_text.extend([str(x.get("summary","")) for x in evidence[-3:]])
    # De-duplicate process references.
    proc_unique = []
    seen = set()
    for p in processes:
        key=(p["source"],p["detail"])
        if key not in seen: seen.add(key); proc_unique.append(p)
    processes = proc_unique
    remediation = []
    if not requested:
        status = "NOT_APPLICABLE"
        remediation = ["Record that no deletion request was made; do not erase data solely because this audit ran."]
    else:
        if matched_records:
            # First stop recreation, then remediate copies, then verify.
            if processes:
                remediation.append("Disable or pause the identified sync/import/restore path before deleting downstream copies.")
                remediation.append("Remove the identity from source queues, replay topics, import manifests and restore allowlists; verify the job cannot re-create the record.")
            if retention:
                remediation.append("Apply deletion_rules.csv to retained records: preserve only legally required fields and remove/redact prohibited personal identifiers.")
            remediation.append("Delete or redact matching records in each identified active store, index, attachment, export, log and archive according to deletion_rules.csv.")
            remediation.append("Re-run the identity search across all supplied evidence files and confirm zero prohibited matches.")
            remediation.append("Verify retained records remain available with only policy-permitted identifiers.")
            status = "INCOMPLETE"
        else:
            if processes:
                remediation.extend(["Disable or validate all identified sync/import/restore paths.", "Run a second evidence scan after the process check."])
            remediation = remediation or [
                "Verify every system and media source required by deletion_rules.csv was included in the scan.",
                "Verify no active sync, import or restore path can recreate the data.",
                "Confirm legally retained records remain available and contain only permitted identifiers.",
                "Save the evidence manifest and approve closure only after all checks pass."
            ]
            # No matching records alone is not proof of deletion; the scan can only prove absence within supplied corpus.
            status = "INCOMPLETE"
    # A request that is marked deleted in source data is still not COMPLETE from a local corpus scan alone.
    # Status becomes COMPLETE only if explicit per-copy treatment and process verification evidence exists.
    req_text = _row_text(req).lower()
    evidence_text = " ".join(e.get("summary","").lower() for e in evidence)
    explicit_verified = any(term in req_text for term in ("all copies verified","deletion_verified","verified_complete","audit_verified"))
    process_clear = not processes or any(term in req_text for term in ("sync disabled","pipeline disabled","recreation blocked"))
    if requested and matched_records == 0 and explicit_verified and process_clear:
        status = "COMPLETE"
        remediation = ["Confirm the supplied evidence manifest covers all required systems and media.", "Retain the verification receipt and recheck that no sync/import/restore path can recreate the data."]
    elif requested and matched_records == 0:
        remediation = [
            "Confirm that all required systems, exports, indexes, logs, attachments, archives, backups and local media were supplied.",
            "Check that sync/import/restore paths are disabled or sanitized so deleted records cannot be recreated.",
            "Verify retained records against deletion_rules.csv and confirm only permitted identifiers remain.",
            "Store a timestamped evidence manifest; do not mark complete based only on no matches in an incomplete corpus."
        ]
    return {
        "request_id": str(req_id), "status": status, "remaining_records": matched_records,
        "recreation_paths": len(processes), "remediation_steps": remediation,
        "evidence_summary": f"{matched_records} matching record(s) found across supplied files; {len(processes)} potential recreation path(s); {len(retention)} retention signal(s).",
        "evidence": evidence, "identifiers": identifiers, "evidence_count": len(evidence),
        "next_step": remediation[0] if remediation else "Review evidence",
        "request_date": _first(req,["request_date","created_at","date"],""),
        "email": _first(req,["email","user_email","customer_email","identifier"],""),
        "processes": processes, "retention_count":len(retention), "_raw": req
    }

def run_audit(data_dir: Path = DATA_DIR):
    files = discover_files(data_dir)
    request_file, request_df = _find_requests(files)
    rules = _find_rules(files)
    results = []
    if not request_df.empty:
        for req in request_df.fillna("").to_dict(orient="records"):
            results.append(audit_one(req, files, rules, request_file))
    inventory = []
    for p in files:
        df = _read_table(p) if p.suffix.lower() in {".csv",".tsv",".json",".jsonl"} else pd.DataFrame()
        inventory.append({"name":p.name,"kind":p.suffix.lower().lstrip(".").upper() or "FILE",
                          "records":len(df) if not df.empty else sum(1 for _ in p.open("r",encoding="utf-8",errors="ignore")) if p.suffix.lower() in SUPPORTED_TEXT else 0,
                          "status":"SCANNED"})
    return {"files":files,"request_file":request_file,"results":results,"inventory":inventory,"rules":rules}

def make_output(results: list[dict], columns=OUTPUT_COLUMNS):
    rows=[]
    aliases={
        "request_id":["request_id","id","deletion_request_id"],
        "status":["status","deletion_status","audit_status","classification"],
        "remaining_records":["remaining_records","remaining_record_count","matching_records","records_found"],
        "recreation_paths":["recreation_paths","recreation_path_count","active_processes"],
        "remediation_steps":["remediation_steps","remediation","next_steps","actions"],
        "evidence_summary":["evidence_summary","evidence","summary","findings"]
    }
    for r in results:
        row={}
        for col in columns:
            norm=_norm(col)
            source=next((s for s,opts in aliases.items() if norm in {_norm(o) for o in opts}),None)
            val=r.get(source,"") if source else ""
            if isinstance(val,(list,dict)): val=json.dumps(val,ensure_ascii=False)
            row[col]=val
        rows.append(row)
    return rows

def write_output(results, path, columns=OUTPUT_COLUMNS):
    rows=make_output(results, columns)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=columns,extrasaction="ignore")
        writer.writeheader();writer.writerows(rows)
    return path

def evaluate(results, request_df: pd.DataFrame):
    if request_df.empty or not results:
        return {"evaluated_rows":0,"unlabelled_rows":len(results),"accuracy":None,"label_column":None,"labels":[],"confusion_matrix":[],"message":"No deletion requests were found. Add the supplied dataset and retry."}
    candidate_cols=[c for c in request_df.columns if _norm(c) in {"expected_status","expected_label","ground_truth","ground_truth_status","actual_status","label","expected_output","target_status"}]
    if not candidate_cols:
        return {"evaluated_rows":0,"unlabelled_rows":len(results),"accuracy":None,"label_column":None,"labels":[],"confusion_matrix":[],"message":"No expected-status column was detected. Predictions were generated without labels; evaluation metrics are unavailable."}
    col=candidate_cols[0]
    actual=[]; predicted=[]
    for raw, result in zip(request_df.fillna("").to_dict(orient="records"),results):
        y=str(raw.get(col,"")).strip().upper().replace(" ","_")
        if y in {"COMPLETE","INCOMPLETE","NOT_APPLICABLE"}:
            actual.append(y);predicted.append(result["status"])
    labels=["COMPLETE","INCOMPLETE","NOT_APPLICABLE"]
    matrix=[[sum(1 for a,p in zip(actual,predicted) if a==lab and p==pred) for pred in labels] for lab in labels]
    accuracy=sum(a==p for a,p in zip(actual,predicted))/len(actual) if actual else None
    return {"evaluated_rows":len(actual),"unlabelled_rows":len(results)-len(actual),"accuracy":accuracy,"label_column":col,"labels":labels,"confusion_matrix":matrix,"message":"Expected labels were used only for scoring, not for prediction." if actual else "Expected column exists but contains no recognized status labels."}
