"""capy-graph: Capy's MCP server (streamable HTTP) + the web UI that lights up each answer's path.

TrueForge attaches this server by URL. Read tools are annotated read-only; `send_intro` is marked
destructive (it reaches a real person), so TrueForge pauses for human approval before it runs.

run: uvicorn capy.server:app --port 8001
"""
import asyncio
import json
import re
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from capy import brightdata as bd
from capy import graph as G
from capy import match as M
from capy.config import settings

WEB = Path(__file__).resolve().parent.parent / "web"
READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
MEMORY = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
LIVE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)
SEND = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True)

mcp = MCPServer(
    "capy-graph",
    instructions="Capy's conference knowledge graph (FalkorDB). Speakers, talks, what each speaker has "
                 "solved (with source receipts), the user's problems, and memory of who they met.",
)
_rag = None


def rag():
    global _rag
    _rag = _rag or G.rag()
    return _rag


# Sits next to the data the agent writes from; Capy must not guess anyone's pronouns from a name.
WRITING_NOTE = "Refer to each person by first name or they/their. Never he, him, his, she, her or hers."


def _brief(view: dict) -> dict:
    """What the agent needs; the full view (with graph path) goes to the UI."""
    return {"query": view["query"], "writing_note": WRITING_NOTE, "people": [
        {k: p[k] for k in ("name", "title", "company", "yuzu", "why", "problems", "linkedin_url")}
        | {"talks": [{k: t[k] for k in ("title", "day", "time", "location")} for t in p["talks"][:2]],
           "receipts": [{k: r[k] for k in ("quote", "source_url", "kind", "fetched_at")} for r in p["receipts"][:2]]}
        for p in view["people"]]}


@mcp.tool(annotations=READ)
def find_my_people(problem: str = "", limit: int = 5) -> dict:
    """Find the conference speakers who already solved the user's problem. Leave `problem` empty to use
    the problems stored in the user's profile. Returns ranked people with why, receipts (source quotes
    with URLs and fetch times) and where to catch them (talk, time, room). Lights up the path in the UI."""
    return _brief(M.find_people(problem or None, limit=limit))


@mcp.tool(annotations=READ)
def why_meet(name: str) -> dict:
    """Explain, with receipts, why the user should meet this speaker: the graph path from the user's
    problem to what this person built/solved/practices, plus the exact source quotes."""
    view = M.find_people(None, limit=40, exclude_met=False, publish_view=False)
    person = next((p for p in view["people"] if p["name"].lower() == name.lower()), None)
    if not person:
        return {"name": name, "found": False, "hint": "Not linked to the user's problems yet; try lookup_person."}
    M.publish({**view, "kind": "why", "focus": person["id"], "people": [person], "graph": M.build_path([person])})
    return {"name": person["name"], "writing_note": WRITING_NOTE, "why": person["why"], "yuzu": person["yuzu"],
            "receipts": person["receipts"],
            "talks": person["talks"], "problems": person["problems"]}


@mcp.tool(annotations=READ)
def where_to_find(name: str) -> dict:
    """Where and when to catch a speaker: their sessions with day, time and room, plus ISO `start`/`end`
    (Pacific time) for sorting and clash checks in code."""
    return M.where_to_find(name)


@mcp.tool(annotations=READ)
async def ask_graph(question: str) -> dict:
    """Ask a free-form question over everything Capy knows (talk abstracts, speakers' posts). Answers are
    grounded GraphRAG completions with their source passages."""
    res = await rag().completion(question, return_context=True)
    sources = []
    for item in (res.retriever_result.items if res.retriever_result else [])[:6]:
        meta = item.metadata or {}
        sources.append({"text": item.content[:280], "source": meta.get("source") or meta.get("path") or meta.get("section")})
    return {"answer": res.answer, "sources": sources}


@mcp.tool(annotations=MEMORY)
def remember_meeting(name: str, notes: str, where: str = "") -> dict:
    """Remember that the user met someone (persists across sessions): notes on what you talked about
    and where. The morning follow-up agent drafts follow-ups from these."""
    return M.remember_meeting(name, notes, where)


@mcp.tool(annotations=MEMORY)
def want_to_meet(name: str, reason: str) -> dict:
    """Add a speaker to the user's shortlist of people to find, with the reason."""
    return M.want_to_meet(name, reason)


@mcp.tool(annotations=READ)
def recall_me() -> dict:
    """Everything Capy remembers about the user: their problems, who they met (with notes and follow-up
    status), their shortlist and intros sent. Call this at the start of a session."""
    return M.recall_me()


@mcp.tool(annotations=READ)
def intro_context(name: str) -> dict:
    """Common ground between the user and a person, for writing a short, specific intro or follow-up."""
    rec = M.recall_me(publish_view=False)
    met = next((m for m in rec["met"] if m["name"].lower() == name.lower()), None)
    view = M.find_people(None, limit=40, exclude_met=False, publish_view=False)
    person = next((p for p in view["people"] if p["name"].lower() == name.lower()), None)
    if person:  # show what the draft is grounded in
        M.publish({**view, "kind": "why", "query": f"follow-up to {name}", "focus": person["id"], "people": [person],
                   "graph": M.build_path([person])})
    return {"to": name, "writing_note": WRITING_NOTE, "user": rec["me"], "user_problems": rec["problems"], "met_notes": met,
            "their_relevant_work": person["receipts"][:2] if person else [], "why": person["why"] if person else None}


@mcp.tool(annotations=SEND)
def send_intro(name: str, message: str) -> dict:
    """Send an intro or follow-up message to a person on the user's behalf. Always requires the user's
    approval; never call it without showing the exact message first."""
    return M.record_intro(name, message, "sent")


@mcp.tool(annotations=LIVE)
async def lookup_person(name: str, company: str = "") -> dict:
    """Live lookup of someone the user just met (or any speaker): Bright Data finds their LinkedIn profile
    and fetches it fresh, Capy adds it to the graph, then reports common ground with the user's problems.
    `fresh_from_profile` is what the live fetch added: new facts and the person's own sentence closest to
    one of the user's problems."""
    known = G.ro("MATCH (p:Person {id: $id}) RETURN p.linkedin_url, p.linkedin_confidence, p.company",
                 id=G.person_id(name))
    if known and known[0][0]:
        hit, how = {"linkedin_url": known[0][0], "confidence": known[0][1] or 0.7}, "graph identity"
        company = company or known[0][2] or ""
    else:
        from scripts.research_speakers import pick_profile
        query = f'"{name}" {company} linkedin'.strip()
        hit, how = pick_profile(name, company, (await bd.serp([query])).get(query, [])), "brightdata:serp"
        if not hit:
            return {"name": name, "found": False, "searched": query}
    fetched_at = bd.now()
    text, collector = await _fresh_profile_text(hit["linkedin_url"])
    if not text:
        return {"name": name, "found": True, "linkedin_url": hit["linkedin_url"], "fresh_fetch": "failed",
                "note": "Bright Data couldn't fetch the profile right now; using what the graph already knows.",
                **M.common_ground(name)}
    doc_id = f"linkedin-profile:{G.person_id(name)}"  # one live profile per person: a re-lookup replaces it
    res = await rag().update(text=f"LinkedIn profile of {name} ({company}), fetched {fetched_at[:10]}:\n\n{text}",
                             document_id=doc_id, extractor=_extractor(), if_missing="ingest")
    G.q("""MERGE (p:__Entity__:Person {id: $pid}) ON CREATE SET p.name = $name
           SET p.linkedin_url = $li, p.linkedin_confidence = $conf, p.company = coalesce(p.company, $company)
           WITH p MATCH (d:Document {path: $doc})
           SET d.kind = 'linkedin_profile', d.source_url = $li, d.collector = $collector, d.fetched_at = $fetched
           MERGE (p)-[:AUTHORED]->(d)""", pid=G.person_id(name), name=name, li=hit["linkedin_url"],
        conf=hit["confidence"], company=company, doc=doc_id, collector=collector, fetched=fetched_at)
    fresh = M.fresh_findings(name, doc_id)
    receipt = {"quote": fresh["quote"], "kind": "linkedin_profile", "source_url": hit["linkedin_url"],
               "collector": collector, "fetched_at": fetched_at} if fresh.get("quote") else None
    overlap = M.common_ground(name, fresh_receipt=receipt)
    return {"name": name, "found": True, "linkedin_url": hit["linkedin_url"], "identity": how,
            "identity_confidence": hit["confidence"], "fetched_at": fetched_at, "collector": collector,
            "graph_update": "unchanged since last fetch" if res.no_op else "added to the graph",
            "fresh_from_profile": fresh, "writing_note": WRITING_NOTE, **overlap}


_KEEP = ("about", "activity", "experience", "education", "licenses", "certifications", "recommendations",
         "projects", "publications", "honors", "volunteer", "languages")
_CHROME = re.compile(r"^(copy|linkedin|facebook|x|posts|comments|reactions|see more|show more|show|or|password|"
                     r"email or phone|no more previous content|report this (post|profile)|\d+[smhdwy]o?|"
                     r"\d+ comments?|(join now|sign in|continue with|forgot password|new to linkedin).*)$", re.I)


def _clean_profile(md: str) -> str:
    """A public LinkedIn page is mostly cookie/sign-in chrome. Keep what the person wrote or listed (about,
    posts, experience, certifications, recommendations) so only their own words reach the graph."""
    md = re.sub(r"(?s)SECURITY NOTICE:.*?_BEGIN=====|=====UNTRUSTED_[0-9a-f]+_END=====", "", md)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)                    # images
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md).replace("\\", "")  # links -> their text
    lines = [l.strip(" \t*") for l in md.splitlines()]
    out, seen = [next((l for l in lines if l), "")], set()  # first line: "Name - Company | LinkedIn"
    keep = repost = False
    for l in lines:
        if l.startswith("## "):
            keep, repost = any(k in l.lower() for k in _KEEP) and "full profile" not in l.lower(), False
            if keep:
                out.append(l)
            continue
        if re.search(r"(posted|shared|reposted) this$", l):  # a repost is someone else's words, not theirs
            repost = l.endswith("reposted this")
        if (repost or not keep or not l or l in seen or _CHROME.match(l) or "public_profile" in l or "undefined" in l
                or not re.search(r"[A-Za-z]{2}", l.replace("*", ""))):
            continue
        seen.add(l)
        out.append(l)
    return "\n".join(out)


async def _fresh_profile_text(url: str) -> tuple[str, str]:
    """Web Unlocker first (fast); if LinkedIn serves a wall or a thin page, use the LinkedIn profile Scraper API."""
    try:
        text = ""
        for _ in range(2):  # the unlocker occasionally answers 200 with an empty body
            text = _clean_profile(await _unlock_markdown(url))
            if len(text) > 300:
                break
        if len(text) > 300 and "authwall" not in text.lower():
            return text[:6000], "brightdata:web_unlocker"
    except Exception as e:  # noqa: BLE001 - fall through to the scraper
        print(f"unlocker failed for {url}: {str(e)[:120]}")
    try:
        recs = await asyncio.to_thread(bd.scrape, bd.LINKEDIN_PROFILES, [{"url": url}])
        r = next((x for x in recs if not x.get("error")), None)
        if r:
            bits = [r.get("about") or "", f"Current company: {(r.get('current_company') or {}).get('name', '')}",
                    *[f"Recent post: {p.get('title') or p.get('attribution') or ''}" for p in (r.get("posts") or [])[:5]]]
            return "\n".join(b for b in bits if b.strip())[:5000], f"brightdata:scraper:{bd.LINKEDIN_PROFILES}"
    except Exception as e:  # noqa: BLE001
        print(f"profile scraper failed for {url}: {str(e)[:120]}")
    return "", ""


def _extractor():
    from graphrag_sdk import GraphExtraction, LLMExtractor
    return GraphExtraction(rag().llm, entity_extractor=LLMExtractor(rag().llm, threshold=0.6),
                           entity_types=[e.label for e in G.ONTOLOGY.entities])


async def _unlock_markdown(url: str) -> str:
    import httpx
    async with httpx.AsyncClient(timeout=90, headers={"Authorization": f"Bearer {settings.brightdata_api_key}"}) as c:
        r = await c.post("https://api.brightdata.com/request", json={
            "zone": settings.brightdata_unlocker_zone, "url": url, "format": "raw", "data_format": "markdown"})
        r.raise_for_status()
        return r.text


# ---- web UI + its JSON API (same process, same port) -------------------------------------------

@mcp.custom_route("/", methods=["GET"])
async def index(_: Request) -> Response:
    return FileResponse(WEB / "index.html")


@mcp.custom_route("/assets/{name}", methods=["GET"])
async def asset(request: Request) -> Response:
    path = (WEB / "assets" / request.path_params["name"]).resolve()
    if WEB not in path.parents or not path.exists():
        return Response(status_code=404)
    return FileResponse(path)


@mcp.custom_route("/api/view", methods=["GET"])
async def api_view(_: Request) -> Response:
    p = M.VIEW_PATH
    return JSONResponse(json.loads(p.read_text()) if p.exists() else {"kind": "empty"})


@mcp.custom_route("/api/stats", methods=["GET"])
async def api_stats(_: Request) -> Response:
    rows = dict(G.ro("""MATCH (n) WITH labels(n) AS ls UNWIND ls AS l
                        WITH l WHERE l IN ['Speaker','Talk','Document','Chunk','Problem','Practice','Tool','Organization']
                        RETURN l, count(*)"""))
    rows["facts"] = G.ro("MATCH ()-[r:RELATES]->() RETURN count(r)")[0][0]
    return JSONResponse(rows)


@mcp.custom_route("/api/outbox", methods=["GET"])
async def api_outbox(_: Request) -> Response:
    p = settings.data_dir / "outbox.json"
    return JSONResponse(json.loads(p.read_text()) if p.exists() else [])


app = mcp.streamable_http_app(
    stateless_http=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
