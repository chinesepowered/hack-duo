#!/usr/bin/env bash
# Capy Pals — one-command local run (laptop / stage demo).
#   needs: Python 3.11+, Node 22.14+, a filled-in .env (see .env.example)
#   FalkorDB: uses FALKORDB_HOST from .env (FalkorDB Cloud), or starts a local one if it's localhost.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { echo "copy .env.example to .env and fill in your keys first"; exit 1; }
set -a; . ./.env; set +a

if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate
pip install -q -r requirements.txt

mkdir -p .run
if [ "${FALKORDB_HOST:-localhost}" = "localhost" ] && ! (echo PING | nc -w1 localhost "${FALKORDB_PORT:-6379}" >/dev/null 2>&1); then
  if command -v docker >/dev/null; then
    docker run -d --rm --name capy-falkordb -p 6379:6379 -p 3000:3000 falkordb/falkordb:v4.22.2 >/dev/null
  else  # no Docker: embedded FalkorDB (Linux wheels)
    pip install -q falkordblite==0.11.0
    BIN=$(python -c 'import redislite,os;print(os.path.dirname(redislite.__file__))')/bin
    "$BIN/redis-server" --port 6379 --daemonize yes --dir .run --loadmodule "$BIN/falkordb.so" >/dev/null
  fi
  sleep 2
fi

# load the prebuilt graph the first time (or if the graph is empty)
COUNT=$(python - <<'PY'
from capy import graph as G
try: print(G.ro("MATCH (n) RETURN count(n)")[0][0])
except Exception: print(0)
PY
)
if [ "$COUNT" = "0" ] && [ -f data/export/capy-graph.jsonl.gz ]; then
  echo "loading graph into FalkorDB…"; python -m scripts.graph_io load data/export/capy-graph.jsonl.gz
fi

echo "starting capy-graph (MCP + UI) on :8001"
uvicorn capy.server:app --host 127.0.0.1 --port 8001 --log-level warning > .run/capy.log 2>&1 &
echo "starting TrueForge on :8790"
OUTBOUND_URL_ALLOWED_HOSTS='["localhost","127.0.0.1"]' SQLITE_PATH="$PWD/.run/trueforge.sqlite" \
  npx -y @truefoundry/trueforge@0.180.0 --port 8790 > .run/trueforge.log 2>&1 &
until curl -s -o /dev/null http://localhost:8790/api/v1/capabilities; do sleep 1; done
python -m scripts.setup_trueforge
echo
echo "  🦫 Capy panel:     http://localhost:8001/      (side-by-side: http://localhost:8001/?side)"
echo "  🤖 TrueForge chat: http://localhost:8790/      → Agents → capy → Try"
echo "  before going on stage: python -m scripts.reset_demo   (clears rehearsal meetings, intros, live lookups)"
wait
