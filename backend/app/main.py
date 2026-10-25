from __future__ import annotations
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from .config import DATA_DIR, OUTPUT_PATH, OUTPUT_COLUMNS
from .engine import run_audit, write_output, evaluate, _read_table

app = FastAPI(title="GhostTrace AI API", version="1.0.0", description="Evidence-led deletion audit API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def snapshot():
    return run_audit(DATA_DIR)

def dashboard_payload(snap):
    results=snap["results"]
    counts={"total":len(results),"COMPLETE":0,"INCOMPLETE":0,"NOT_APPLICABLE":0}
    for r in results: counts[r["status"]]=counts.get(r["status"],0)+1
    processes=[]
    for r in results: processes.extend(r.get("processes",[]))
    evidence_count=sum(r.get("evidence_count",0) for r in results)
    retention_count=sum(r.get("retention_count",0) for r in results)
    return {"counts":counts,"requests":[{k:v for k,v in r.items() if k not in {"_raw","processes"}} for r in results],
            "file_inventory":snap["inventory"],"files_scanned":len(snap["inventory"]),
            "evidence_count":evidence_count,"retention_count":retention_count,"recreation_paths":len(processes),
            "processes":processes,"data_dir":str(DATA_DIR),"request_file":snap["request_file"].name if snap["request_file"] else None,
            "output_columns":OUTPUT_COLUMNS}

@app.get("/")
def root():
    return {"name":"GhostTrace AI","status":"online","docs":"/docs","health":"/api/health"}

@app.get("/api/health")
def health():
    return {"status":"ok","data_dir_exists":DATA_DIR.exists(),"data_dir":str(DATA_DIR)}

@app.get("/api/dashboard")
def dashboard():
    return dashboard_payload(snapshot())

@app.get("/api/requests")
def requests():
    return dashboard_payload(snapshot())["requests"]

@app.get("/api/evidence")
def evidence():
    snap=snapshot()
    return [{"request_id":r["request_id"],"evidence":r["evidence"]} for r in snap["results"]]

@app.get("/api/processes")
def processes():
    return dashboard_payload(snapshot())["processes"]

@app.post("/api/audit")
def audit():
    snap=snapshot()
    write_output(snap["results"], OUTPUT_PATH, OUTPUT_COLUMNS)
    return {"processed":len(snap["results"]),"output_path":str(OUTPUT_PATH),"counts":dashboard_payload(snap)["counts"]}

@app.post("/api/evaluate")
def run_evaluation():
    snap=snapshot()
    write_output(snap["results"], OUTPUT_PATH, OUTPUT_COLUMNS)
    request_df=_read_table(snap["request_file"]) if snap["request_file"] else None
    if request_df is None:
        from pandas import DataFrame
        request_df=DataFrame()
    report=evaluate(snap["results"],request_df)
    report["output_path"]=str(OUTPUT_PATH)
    return report

@app.get("/api/output.csv")
def output_csv():
    snap=snapshot()
    write_output(snap["results"], OUTPUT_PATH, OUTPUT_COLUMNS)
    if not OUTPUT_PATH.exists():
        raise HTTPException(status_code=404,detail="Output has not been generated")
    return FileResponse(OUTPUT_PATH, media_type="text/csv", filename="output.csv")

@app.get("/api/config")
def config():
    return {"data_dir":str(DATA_DIR),"output_path":str(OUTPUT_PATH),"output_columns":OUTPUT_COLUMNS,
            "warning":"Set OUTPUT_COLUMNS to exactly match the official problem statement before submission."}
