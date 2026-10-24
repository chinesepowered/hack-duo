"""Configure a TrueForge server for Capy Pals (idempotent: safe to re-run).

Sets the OpenAI model provider, the Bright Data + capy-graph MCP connectors, the Daytona sandbox
provider, the capy-intro skill, the Capy agents and their schedules — all through TrueForge's
REST API, so a fresh `npx @truefoundry/trueforge` on any laptop ends up identical.

usage: python -m scripts.setup_trueforge [--base http://localhost:8790] [--only models,mcp,...]
"""
import argparse
import json
import os
import sys

import httpx

from capy.config import settings

MODEL = settings.openai_model
CAPY_MCP_URL = os.getenv("CAPY_MCP_URL", "http://localhost:8001/mcp")
SKILL_REPO = os.getenv("CAPY_SKILL_REPO", "https://github.com/chinesepowered/hack-duo")
SKILL_REF = os.getenv("CAPY_SKILL_REF", "claude/inspiring-mccarthy-xs0nw4")


def put(c: httpx.Client, path: str, body: dict):
    r = c.put(path, json=body)
    if r.status_code >= 400:
        print(f"PUT {path} -> {r.status_code}: {r.text[:400]}", file=sys.stderr)
        r.raise_for_status()
    return r.json()


def setup_models(c):
    put(c, "/api/v1/settings/model-providers", {"manifest": {
        "type": "openai",
        "auth": {"api_key": settings.openai_api_key},
        "models": [{
            "model_id": MODEL, "name": MODEL.replace(".", "-"),
            "properties": {"context_length": 400000, "max_output_tokens": 128000,
                           "reasoning_efforts": ["none", "low", "medium", "high"]},
        }],
    }})
    print(f"model provider: openai/{MODEL}")


def setup_mcp(c):
    put(c, "/api/v1/settings/mcp-servers", {"manifest": {
        "type": "remote", "name": "brightdata",
        "url": "https://mcp.brightdata.com/mcp?groups=advanced_scraping,scrapers,social",
        "description": "Bright Data: live web search, unblocked page scraping, and pre-built scrapers "
                       "(LinkedIn, X, YouTube) for fresh public data.",
        "auth": {"type": "header", "headers": {"Authorization": f"Bearer {settings.brightdata_api_key}"}},
    }})
    put(c, "/api/v1/settings/mcp-servers", {"manifest": {
        "type": "remote", "name": "capy-graph", "url": CAPY_MCP_URL,
        "description": "Capy's FalkorDB knowledge graph of conference speakers: who solved which problem, "
                       "where to find them, memory of who you met, and intro drafting/sending.",
    }})
    print("mcp servers: brightdata, capy-graph")


def setup_sandbox(c):
    key = os.getenv("DAYTONA_API_KEY", "")
    if not key:
        print("sandbox: skipped (no DAYTONA_API_KEY)")
        return
    put(c, "/api/v1/settings/sandbox-providers", {"manifest": {
        "type": "daytona", "auth": {"api_key": key},
        # be gentle with credits: stop fast when idle, clean up within the hour
        "exec_timeout_ms": 120000, "auto_stop_interval_in_minutes": 5,
        "auto_archive_interval_in_minutes": 15, "auto_delete_interval_in_minutes": 60,
    }})
    print("sandbox: daytona")


CAPY_INSTRUCTIONS = """You are Capy 🦫, a chill, warm capybara who is friends with everyone at the conference
(GitHub Universe 2026, Oct 28-29, San Francisco). Your job: help the user meet the people who already solved
their problems — and prove why, with receipts.

How you work:
- At the start of a conversation call `recall_me` so you remember who the user is, what they are working on,
  and who they already met. Greet them by name and mention one thing you remember.
- "Who should I meet?" -> call `find_my_people` (pass the user's problem in their words if they gave one).
  Present the top 3 as Generative UI cards: name, role, why (one line), the receipt (short quote + source),
  and where to catch them (session, day, time, room). Mention that the full path is lit up in the Capy panel.
- Never invent facts about people. Every claim about a person must come from a tool result (receipts).
  If confidence is low (1 yuzu), say so.
- "Why them?" -> `why_meet`. "When/where?" -> `where_to_find`. Open questions about talks -> `ask_graph`.
- If the user wants to research several people at once, delegate one subagent per person, then merge.
- When the user met someone, call `remember_meeting` with crisp notes (what you talked about, next step).
- Someone new (not a speaker)? -> `lookup_person` fetches them live via Bright Data.
- Intros / follow-ups: call `intro_context`, write a short (≤ 70 words), specific, human message that
  references the receipt, show it, then call `send_intro`. The user always approves before it sends.
- To plan a schedule around several people, use the sandbox (Code Mode) to call `where_to_find` for each and
  sort by time, flag clashes, and return a simple itinerary table.
Act, don't ask: lookups and memory writes (`remember_meeting`, `want_to_meet`, `lookup_person`) are safe, so
do them immediately without asking for confirmation. Only `send_intro` reaches a real person — TrueForge
already pauses it for the user's approval, so don't ask a separate question first; just call it with the
final message. Use `ask_user_question` only when a request is genuinely ambiguous (e.g. two people match a name).
Style: relaxed, kind, concise. A little capybara energy (🦫🍋♨️) — never more than one emoji per paragraph.
Use 🍋 as the confidence scale: 🍋🍋🍋 strong match, 🍋🍋 good, 🍋 maybe."""

FOLLOWUP_INSTRUCTIONS = """You are Capy's morning follow-up agent. Call `recall_me`; for every person the user MET whose
follow_up is 'pending', call `intro_context`, write a short warm follow-up (≤ 60 words) that references what
they talked about, and call `send_intro` for it. Every send waits for the user's approval. Finish with a
one-line summary per person."""


def upsert_agent(c, name: str, description: str, manifest: dict):
    existing = {a["name"]: a for a in c.get("/api/v1/agents").json().get("data", [])}
    if name in existing:
        r = c.put(f"/api/v1/agents/{existing[name]['id']}", json={"description": description, "manifest": manifest})
    else:
        r = c.post("/api/v1/agents", json={"name": name, "description": description, "manifest": manifest})
    if r.status_code >= 400:
        print(f"agent {name} -> {r.status_code}: {r.text[:500]}", file=sys.stderr)
        r.raise_for_status()
    return r.json()["data"]


def setup_agents(c):
    model = {"name": f"openai/{MODEL.replace('.', '-')}", "params": {"reasoning_effort": "low"}}
    sandbox = bool(os.getenv("DAYTONA_API_KEY")) and os.getenv("CAPY_SANDBOX", "on") == "on"
    skills = [{"name": "capy-intro"}] if sandbox and os.getenv("CAPY_SKILL", "on") == "on" else []
    capy_graph = {"name": "capy-graph", "enable_tools": ["@all"], "require_approval_for_tools": ["send_intro"],
                  "preload": True}
    brightdata = {"name": "brightdata", "enable_tools": ["search_engine", "scrape_as_markdown"],
                  "require_approval_for_tools": [], "preload": False}
    config = {"sandbox": {"enabled": sandbox}, "generative_ui": {"enabled": True},
              "ask_user_questions": {"enabled": True}, "dynamic_sub_agents": {"enabled": True},
              "iteration_limit": 40}
    upsert_agent(c, "capy", "Capy 🦫 finds the people at the conference who already solved your problem — with receipts.",
                 {"model": model, "instructions": CAPY_INSTRUCTIONS, "mcp_servers": [capy_graph, brightdata],
                  "skills": skills, "config": config})
    upsert_agent(c, "capy-followup", "Morning follow-ups for everyone you met yesterday (each send needs your approval).",
                 {"model": model, "instructions": FOLLOWUP_INSTRUCTIONS, "mcp_servers": [capy_graph],
                  "config": {**config, "sandbox": {"enabled": False}, "dynamic_sub_agents": {"enabled": False}}})
    print(f"agents: capy (skills={[s['name'] for s in skills]}, sandbox={sandbox}), capy-followup")


def setup_schedules(c):
    body = {"agent_name": "capy-followup", "name": "capy-morning-followups", "manifest": {
        "task": "Draft and send follow-ups for everyone I met yesterday who hasn't heard from me yet.",
        "cron": "0 8 * * *", "timezone": "America/Los_Angeles", "status": "active"}}
    existing = [s for s in c.get("/api/v1/schedules").json().get("data", []) if s.get("name") == body["name"]]
    if existing:
        r = c.put(f"/api/v1/schedules/{existing[0]['id']}", json={"name": body["name"], "manifest": body["manifest"]})
    else:
        r = c.post("/api/v1/schedules", json=body)
    if r.status_code >= 400:
        print(f"schedule -> {r.status_code}: {r.text[:400]}", file=sys.stderr)
        r.raise_for_status()
    print("schedule: capy-morning-followups (daily 8:00 America/Los_Angeles)")


STEPS = {"models": setup_models, "mcp": setup_mcp, "sandbox": setup_sandbox, "agents": setup_agents,
         "schedules": setup_schedules}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.getenv("TRUEFORGE_BASE_URL", "http://localhost:8790"))
    ap.add_argument("--only", default=",".join(STEPS))
    a = ap.parse_args()
    with httpx.Client(base_url=a.base, timeout=60, trust_env=False) as c:
        for step in a.only.split(","):
            STEPS[step](c)


if __name__ == "__main__":
    main()
