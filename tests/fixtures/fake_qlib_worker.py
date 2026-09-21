from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("--request", required=True)
parser.add_argument("--response", required=True)
args = parser.parse_args()
if os.environ.get("QUANTAGENT_TEST_SECRET"):
    raise RuntimeError("host leaked QUANTAGENT_TEST_SECRET to worker")
request = json.loads(Path(args.request).read_text(encoding="utf-8"))
data_sha256 = hashlib.sha256(Path(request["data_path"]).read_bytes()).hexdigest()
response = {
    "protocol_version": "quantagent.qlib_worker.v1",
    "request_id": request["request_id"],
    "status": "ok",
    "result": {
        "contract_version": "quantagent.factor_research.v1",
        "records": [{
            "factor_name": "factor",
            "label_name": "label",
            "row_count": 20,
            "usable_row_count": 20,
            "instrument_count": 5,
            "date_count": 4,
            "valid_ic_date_count": 4,
            "valid_rank_ic_date_count": 4,
            "mean_ic": 0.45,
            "mean_rank_ic": 0.45,
            "daily_metrics": [{"date": "2026-01-02", "row_count": 5, "ic": 1.0, "rank_ic": 1.0}],
        }],
        "metadata": {
            "data_sha256": data_sha256,
            "loader": "fake protocol worker; not Qlib",
            "runtime": {"python": "test", "pyqlib": "not-exercised", "pandas": "not-exercised"},
        },
    },
}
Path(args.response).write_text(json.dumps(response), encoding="utf-8")
