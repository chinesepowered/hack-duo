"""Drive the Capy agent on TrueForge from the terminal (handy for testing and for the demo script).

usage: python -m scripts.chat "who should I meet?" [--session ID] [--approve]
Prints tool calls, approval requests and Capy's reply. With --approve, approves pending tool calls.
"""
import argparse
import json
import os
import sys
import time

import httpx

BASE = os.getenv("TRUEFORGE_BASE_URL", "http://localhost:8790")


def wait_turn(c, sid, tid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        turn = c.get(f"/api/v1/sessions/{sid}/turns/{tid}").json()["data"]
        if turn["state"]["status"] not in ("running", "queued", "pending"):
            return turn
        time.sleep(1.5)
    raise TimeoutError(tid)


def show(c, sid, tid):
    events = c.get(f"/api/v1/sessions/{sid}/turns/{tid}/events", params={"page_size": 200}).json()["data"]
    pending = []
    for e in events:
        ev = e.get("event", e)
        t = ev.get("type")
        if t == "model.message":
            for tc in ev.get("tool_calls") or ev.get("toolCalls") or []:
                fn = tc.get("function", {})
                print(f"  🔧 {(tc.get('tool_info') or tc.get('toolInfo') or {}).get('name') or fn.get('name')}({fn.get('arguments', '')[:160]})")
            text = ev.get("content") or ""
            if isinstance(text, list):
                text = " ".join(p.get("text", "") for p in text if isinstance(p, dict))
            if text.strip():
                print(f"\n🦫 {text.strip()}\n")
        elif t == "tool.approval_required":
            pending.append(ev)
            print("  ⏸  approval required")
        elif t == "thread.created":
            print(f"  🧵 subagent: {ev.get('name') or ev.get('title') or ev.get('threadId')}")
    return pending


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("message")
    ap.add_argument("--session")
    ap.add_argument("--agent", default="capy")
    ap.add_argument("--approve", action="store_true")
    a = ap.parse_args()
    with httpx.Client(base_url=BASE, timeout=120, trust_env=False) as c:
        sid = a.session or c.post("/api/v1/sessions", json={"agent": {"name": a.agent}}).json()["data"]["id"]
        print(f"session {sid}")
        turn = c.post(f"/api/v1/sessions/{sid}/turns", json={
            "input": [{"type": "user.message", "content": a.message}], "stream": False}).json()["data"]
        turn = wait_turn(c, sid, turn["id"])
        pending = show(c, sid, turn["id"])
        status = turn["state"]["status"]
        while pending and a.approve:
            items = []
            for p in pending:
                for ref in p.get("tool_calls") or p.get("toolCalls") or []:
                    items.append({"type": "user.tool_approval", "thread_id": p.get("thread_id") or p.get("threadId"),
                                  "tool_call_id": ref["id"], "approval": {"status": "allow"}})
            print(f"  ✅ approving {len(items)} call(s)")
            turn = c.post(f"/api/v1/sessions/{sid}/turns", json={"input": items, "stream": False}).json()["data"]
            turn = wait_turn(c, sid, turn["id"])
            pending = show(c, sid, turn["id"])
            status = turn["state"]["status"]
        print(f"[{status}] session={sid}")


if __name__ == "__main__":
    sys.exit(main())
