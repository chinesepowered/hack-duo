#!/usr/bin/env bash
# Capy Pals: one-command local run (laptop / stage demo). Works on Linux, macOS and Windows (Git Bash).
#   needs: uv (https://docs.astral.sh/uv/), Node 22.14+ (pnpm or npx), a filled-in .env (see .env.example)
#   FalkorDB: uses FALKORDB_HOST from .env (FalkorDB Cloud), or starts a local one if it's localhost.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { echo "copy .env.example to .env and fill in your keys first"; exit 1; }
set -a; . ./.env; set +a
export PYTHONUTF8=1                                            # emoji-safe output on Windows consoles
export CAPY_MCP_URL="${CAPY_MCP_URL:-http://127.0.0.1:8001/mcp}"
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }

# Python env (overrides.txt skips hnswlib, which Capy doesn't use and which needs a C++ compiler)
[ -d .venv ] || uv venv -q --python 3.13 .venv
PY=.venv/bin/python; [ -x .venv/Scripts/python.exe ] && PY=.venv/Scripts/python.exe
uv pip install -q --python "$PY" -r requirements.txt --override overrides.txt

mkdir -p .run data
RUN_DIR="$(pwd -W 2>/dev/null || pwd)/.run"                   # Windows path for Node under Git Bash
port_open() { "$PY" -c "import socket,sys; socket.create_connection(('127.0.0.1', int(sys.argv[1])), 1)" "$1" 2>/dev/null; }

if [ "${FALKORDB_HOST:-localhost}" = "localhost" ] && ! port_open "${FALKORDB_PORT:-6379}"; then
  if command -v docker >/dev/null; then
    docker run -d --rm --name capy-falkordb -p 6379:6379 -p 3000:3000 falkordb/falkordb:v4.22.2 >/dev/null
  elif [ "$(uname -s)" = "Linux" ]; then  # no Docker: embedded FalkorDB (Linux wheels only)
    uv pip install -q --python "$PY" falkordblite==0.11.0
    BIN=$("$PY" -c 'import redislite,os;print(os.path.dirname(redislite.__file__))')/bin
    "$BIN/redis-server" --port 6379 --daemonize yes --dir .run --loadmodule "$BIN/falkordb.so" >/dev/null
  else
    echo "no FalkorDB: set FALKORDB_HOST to your FalkorDB Cloud endpoint in .env, or install Docker"; exit 1
  fi
  for _ in $(seq 1 30); do port_open "${FALKORDB_PORT:-6379}" && break; sleep 1; done
fi

# load the prebuilt graph the first time (or if the graph is empty)
COUNT=$("$PY" - <<'PY'
from capy import graph as G
try: print(G.ro("MATCH (n) RETURN count(n)")[0][0])
except Exception: print(0)
PY
)
if [ "$COUNT" = "0" ] && [ -f data/export/capy-graph.jsonl.gz ]; then
  echo "loading graph into FalkorDB…"; "$PY" -m scripts.graph_io load data/export/capy-graph.jsonl.gz
fi

trap 'kill $(jobs -p) 2>/dev/null' EXIT                     # Ctrl+C stops both servers
echo "starting capy-graph (MCP + UI) on :8001"
"$PY" -m uvicorn capy.server:app --host 127.0.0.1 --port 8001 --log-level warning > .run/capy.log 2>&1 &
echo "starting TrueForge on :8790"
TF=(npx -y); command -v pnpm >/dev/null && TF=(pnpm dlx)
OUTBOUND_URL_ALLOWED_HOSTS='["localhost","127.0.0.1"]' SQLITE_PATH="$RUN_DIR/trueforge.sqlite" \
  "${TF[@]}" @truefoundry/trueforge@0.180.0 --port 8790 > .run/trueforge.log 2>&1 &
for i in $(seq 1 180); do
  curl -s -o /dev/null http://localhost:8790/api/v1/capabilities && break
  [ "$i" = 180 ] && { echo "TrueForge didn't start; see .run/trueforge.log"; tail -20 .run/trueforge.log; exit 1; }
  sleep 1
done
"$PY" -m scripts.setup_trueforge
echo
echo "  🦫 Capy panel:     http://localhost:8001/      (side-by-side: http://localhost:8001/?side)"
echo "  🤖 TrueForge chat: http://localhost:8790/      → Agents → capy → Try"
echo "  before going on stage: $PY -m scripts.reset_demo   (clears rehearsal meetings, intros, live lookups)"
wait
