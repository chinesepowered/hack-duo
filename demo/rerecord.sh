#!/usr/bin/env bash
# Full re-take of the app scenes from a clean state, then the code insert and the final assembly.
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -m scripts.reset_demo  # memory + live lookups; the built graph stays
rm -f demo/out/clips/state.json demo/out/clips/s04b_plan_raw.mp4
for sid in $(curl -sS "http://localhost:8790/api/v1/sessions?page_size=100" | python3 -c 'import sys,json; print(" ".join(s["id"] for s in json.load(sys.stdin)["data"]))'); do
  curl -sS -X DELETE -o /dev/null "http://localhost:8790/api/v1/sessions/$sid"
done
node demo/record.cjs s03_ask s04b_plan s06_lookup s07_memory s08_approve
node demo/record_code_insert.cjs
.venv/bin/python demo/assemble.py
