#!/usr/bin/env python3
import json
from pathlib import Path
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {
    "workspace.agent": json.loads((ROOT / "schemas" / "workspace.agent.schema.json").read_text()),
    "workspace.graph": json.loads((ROOT / "schemas" / "workspace-graph.schema.json").read_text()),
    "workspace.sync": json.loads((ROOT / "schemas" / "workspace-sync.schema.json").read_text()),
    "workspace.evidence": json.loads((ROOT / "schemas" / "evidence-record.schema.json").read_text()),
}

EXAMPLES = [
    ("workspace.agent", ROOT / "examples" / "node-postgres" / "workspace.agent.yaml"),
    ("workspace.graph", ROOT / "examples" / "node-postgres" / "workspace-graph.yaml"),
    ("workspace.sync", ROOT / "examples" / "node-postgres" / "workspace-sync.yaml"),
    ("workspace.evidence", ROOT / "examples" / "node-postgres" / "evidence-record.json"),
    ("workspace.agent", ROOT / "examples" / "python-fastapi-postgres" / "workspace.agent.yaml"),
    ("workspace.graph", ROOT / "examples" / "python-fastapi-postgres" / "workspace-graph.yaml"),
    ("workspace.sync", ROOT / "examples" / "python-fastapi-postgres" / "workspace-sync.yaml"),
    ("workspace.evidence", ROOT / "examples" / "python-fastapi-postgres" / "evidence-record.json"),
]

report = {"status": "ok", "checks": []}

for schema_name, path in EXAMPLES:
    schema = SCHEMAS[schema_name]
    if path.suffix == ".json":
        data = json.loads(path.read_text())
    else:
        data = yaml.safe_load(path.read_text())
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    report["checks"].append({
        "schema": schema_name,
        "file": str(path.relative_to(ROOT)),
        "valid": len(errors) == 0,
        "errors": [e.message for e in errors],
    })

if any(not c["valid"] for c in report["checks"]):
    report["status"] = "failed"

out = ROOT / "manifest" / "validation-report.json"
out.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
