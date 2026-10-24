"""Capy's matchmaking: who here already solved your problem — and the graph path that proves it.

Hybrid retrieval, all inside FalkorDB:
  1. vector search over entity embeddings: your problem -> similar Problem/Practice/Tool entities
     (cached as SIMILAR_TO edges so the path is a real path in the graph)
  2. graph traversal: Speaker -[RELATES {SOLVED|BUILT|PRACTICES|...}]-> concept   (1 hop)
                      Speaker -[RELATES]-> x -[RELATES {ADDRESSES}]-> concept        (2 hops)
  3. lexical fallback: vector search over Chunks -> Document <- AUTHORED - Speaker
Every hit carries a receipt: the source chunk text, its Document's source_url, collector and fetched_at.
"""
import json
import time
from datetime import datetime, timezone

from openai import OpenAI

from capy import graph as G
from capy.config import settings

REL_WEIGHT = {"SOLVED": 1.0, "BUILT": 0.9, "PRACTICES": 0.8, "ADDRESSES": 0.75, "USES": 0.5, "FACES": 0.45}
VIEW_PATH = settings.data_dir / "view.json"
_oai = None


def embed(text: str) -> list[float]:
    global _oai
    _oai = _oai or OpenAI(api_key=settings.openai_api_key)
    r = _oai.embeddings.create(model=settings.embedding_model, input=text, dimensions=G.EMBED_DIM)
    return r.data[0].embedding


def sim(score: float) -> float:
    """FalkorDB returns cosine *distance* for cosine indexes; convert to similarity."""
    return max(0.0, 1.0 - float(score))


def my_problems() -> list[dict]:
    rows = G.ro("""MATCH (me:Me)-[r:RELATES {rel_type: 'FACES'}]->(p:__Entity__)
                   RETURN p.id, p.name, p.embedding""")
    return [{"id": r[0], "name": r[1], "embedding": r[2]} for r in rows if r[2] is not None]


def _chunks(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    rows = G.ro("""MATCH (d:Document)-[:PART_OF]->(c:Chunk) WHERE c.id IN $ids
                   RETURN c.id, c.text, d.path, d.kind, d.source_url, d.collector, d.fetched_at, d.date_posted""",
                ids=ids[:3])
    return [{"chunk_id": r[0], "quote": r[1], "doc": r[2], "kind": r[3], "source_url": r[4],
             "collector": r[5], "fetched_at": r[6], "date_posted": r[7]} for r in rows]


def find_people(problem: str | None = None, limit: int = 5, exclude_met: bool = True) -> dict:
    """Rank speakers by how well their talks/posts show they solved one of your problems."""
    t0 = time.time()
    if problem:
        targets = [{"id": None, "name": problem, "embedding": embed(problem)}]
    else:
        targets = my_problems()
    people: dict[str, dict] = {}

    def add(pid, pname, score, hit):
        p = people.setdefault(pid, {"id": pid, "name": pname, "score": 0.0, "hits": []})
        hit["score"] = score
        p["hits"].append(hit)

    for t in targets:
        vec = t["embedding"]
        concepts = G.ro("""CALL db.idx.vector.queryNodes('__Entity__', 'embedding', 30, vecf32($v)) YIELD node, score
                           WITH node, score WHERE NOT node:Person AND NOT node:Organization AND NOT node:Me
                           RETURN node.id, node.name, labels(node), score""", v=vec)
        concepts = [(cid, cname, [l for l in labels if l != "__Entity__"][:1], sim(s))
                    for cid, cname, labels, s in concepts if cid != t["id"] and sim(s) >= 0.5]
        for cid, cname, clabel, s in concepts:
            if t["id"]:  # make the semantic link a real, visible edge
                G.q("""MATCH (a:__Entity__ {id: $a}), (b:__Entity__ {id: $b})
                       MERGE (a)-[e:SIMILAR_TO]->(b) SET e.score = $s""", a=t["id"], b=cid, s=round(s, 3))
            direct = G.ro("""MATCH (p:Speaker)-[r:RELATES]->(c:__Entity__ {id: $cid})
                             RETURN p.id, p.name, r.rel_type, r.fact, r.source_chunk_ids""", cid=cid)
            for pid, pname, rel, fact, chunk_ids in direct:
                add(pid, pname, s * REL_WEIGHT.get(rel, 0.4), {
                    "problem": t["name"], "problem_id": t["id"], "concept": cname, "concept_id": cid,
                    "concept_label": clabel[0] if clabel else "Concept", "similarity": round(s, 3),
                    "rel": rel, "fact": fact, "via": None, "evidence": _chunks(chunk_ids or [])})
            two_hop = G.ro("""MATCH (p:Speaker)-[r1:RELATES]->(x:__Entity__)-[r2:RELATES {rel_type: 'ADDRESSES'}]->(c:__Entity__ {id: $cid})
                              RETURN p.id, p.name, r1.rel_type, x.name, x.id, r2.fact, r1.source_chunk_ids""", cid=cid)
            for pid, pname, rel, xname, xid, fact, chunk_ids in two_hop:
                add(pid, pname, s * REL_WEIGHT.get(rel, 0.4) * 0.85, {
                    "problem": t["name"], "problem_id": t["id"], "concept": cname, "concept_id": cid,
                    "concept_label": clabel[0] if clabel else "Concept", "similarity": round(s, 3),
                    "rel": rel, "fact": fact, "via": {"name": xname, "id": xid}, "evidence": _chunks(chunk_ids or [])})
        # lexical fallback: passages that talk about the problem, traced to their authors
        for pid, pname, cid, text, doc, kind, url, collector, fetched, posted, s in G.ro(
                """CALL db.idx.vector.queryNodes('Chunk', 'embedding', 12, vecf32($v)) YIELD node, score
                   MATCH (d:Document)-[:PART_OF]->(node) MATCH (p:Speaker)-[:AUTHORED]->(d)
                   RETURN p.id, p.name, node.id, node.text, d.path, d.kind, d.source_url, d.collector,
                          d.fetched_at, d.date_posted, score""", v=vec):
            if sim(s) < 0.45:
                continue
            add(pid, pname, sim(s) * 0.6, {
                "problem": t["name"], "problem_id": t["id"], "concept": None, "concept_id": None,
                "concept_label": None, "similarity": round(sim(s), 3), "rel": "TALKS_ABOUT", "fact": None, "via": None,
                "evidence": [{"chunk_id": cid, "quote": text, "doc": doc, "kind": kind, "source_url": url,
                              "collector": collector, "fetched_at": fetched, "date_posted": posted}]})

    for p in people.values():  # strongest evidence wins; corroboration adds a little
        scores = sorted((h["score"] for h in p["hits"]), reverse=True)
        p["score"] = scores[0] + 0.25 * sum(scores[1:4])
    met = {r[0] for r in G.ro("MATCH (:Me)-[:MET]->(p) RETURN p.id")} if exclude_met else set()
    ranked = sorted((p for p in people.values() if p["id"] not in met), key=lambda p: -p["score"])[:limit]
    out = [profile(p) for p in ranked]
    view = {"kind": "matches", "query": problem or "Maya's problems", "generated_at": _now(),
            "took_ms": int((time.time() - t0) * 1000), "people": out,
            "graph": build_path(out[:3])}
    publish(view)
    return view


def profile(p: dict) -> dict:
    row = G.ro("""MATCH (s:Speaker {id: $id}) OPTIONAL MATCH (s)-[:PRESENTS]->(t:Talk)
                  RETURN s.name, s.title, s.company, s.linkedin_url, s.linkedin_confidence, s.avatar,
                         collect(t {.id, .title, .kind, .day, .time, .location, .source_url, .fetched_at})""", id=p["id"])
    name, title, company, li, conf, avatar, talks = row[0] if row else (p["name"], "", "", None, 0, None, [])
    hits = sorted(p["hits"], key=lambda h: -h["score"])
    best = hits[0]
    seen, receipts = set(), []
    for h in hits:
        for e in h["evidence"]:
            if e["chunk_id"] in seen:
                continue
            seen.add(e["chunk_id"])
            receipts.append({**e, "quote": _snippet(e["quote"], h["concept"] or h["problem"]), "fact": h["fact"],
                             "rel": h["rel"], "problem": h["problem"]})
    score = round(p["score"], 3)
    return {"id": p["id"], "name": name, "title": title, "company": company, "linkedin_url": li,
            "identity_confidence": conf, "avatar": avatar, "score": score,
            "yuzu": 3 if best["similarity"] >= 0.62 else 2 if best["similarity"] >= 0.53 else 1,
            "why": _why(best, name), "best_hit": best, "talks": [t for t in talks if t.get("id")],
            "receipts": receipts[:4], "problems": sorted({h["problem"] for h in hits})}


def _why(h: dict, name: str) -> str:
    rel = {"SOLVED": "solved", "BUILT": "built", "PRACTICES": "practices", "ADDRESSES": "works on",
           "USES": "uses", "FACES": "is also wrestling with", "TALKS_ABOUT": "talks about"}.get(h["rel"], "works on")
    target = h["via"]["name"] if h.get("via") else (h["concept"] or "this")
    return f'{name} {rel} "{target}" — close to your problem "{h["problem"]}" (similarity {h["similarity"]:.2f})'


def _snippet(text: str, around: str | None, width: int = 320) -> str:
    text = " ".join((text or "").split())
    if around:
        i = text.lower().find(around.lower().split()[0])
        if i > 80:
            text = "…" + text[i - 80:]
    return text[:width] + ("…" if len(text) > width else "")


def build_path(people: list[dict]) -> dict:
    """Nodes/links for the lit-path view: Maya -> her problem -> similar concept <- speaker -> talk."""
    nodes, links = {}, []

    def node(nid, label, name, **data):
        nodes.setdefault(nid, {"id": nid, "label": label, "name": name, **data})

    me = G.ro("MATCH (me:Me) RETURN me.id, me.name")
    if not me:
        return {"nodes": [], "links": []}
    node(me[0][0], "Me", me[0][1])
    for p in people:
        h = p["best_hit"]
        node(p["id"], "Speaker", p["name"], title=p["title"], company=p["company"], avatar=p["avatar"])
        if h["problem_id"]:
            node(h["problem_id"], "Problem", h["problem"])
            links.append({"source": me[0][0], "target": h["problem_id"], "rel": "FACES"})
        anchor = h["problem_id"] or me[0][0]
        if h["concept_id"]:
            node(h["concept_id"], h["concept_label"] or "Concept", h["concept"])
            links.append({"source": anchor, "target": h["concept_id"], "rel": f"SIMILAR_TO {h['similarity']:.2f}"})
            if h.get("via"):
                node(h["via"]["id"], "Practice", h["via"]["name"])
                links.append({"source": p["id"], "target": h["via"]["id"], "rel": h["rel"]})
                links.append({"source": h["via"]["id"], "target": h["concept_id"], "rel": "ADDRESSES"})
            else:
                links.append({"source": p["id"], "target": h["concept_id"], "rel": h["rel"]})
        elif h["evidence"]:
            doc = h["evidence"][0]
            node(doc["doc"], "Document", (doc["kind"] or "source").replace("_", " "), url=doc["source_url"])
            links.append({"source": anchor, "target": doc["doc"], "rel": f"SIMILAR_TO {h['similarity']:.2f}"})
            links.append({"source": p["id"], "target": doc["doc"], "rel": "AUTHORED"})
        for t in p["talks"][:1]:
            node(t["id"], "Talk", t["title"], when=f'{t["day"]} {t["time"]}', where=t["location"])
            links.append({"source": p["id"], "target": t["id"], "rel": "PRESENTS"})
    return {"nodes": list(nodes.values()), "links": [dict(l, id=i) for i, l in enumerate(links)]}


def common_ground(name: str) -> dict:
    """What links a (possibly just-looked-up) person to the user's problems, with the path for the UI."""
    view = find_people(None, limit=60, exclude_met=False)
    person = next((p for p in view["people"] if p["name"].lower() == name.lower()), None)
    if person:
        publish({**view, "kind": "lookup", "focus": person["id"], "people": [person], "graph": build_path([person])})
        return {"common_ground": person["why"], "yuzu": person["yuzu"], "receipts": person["receipts"][:2],
                "talks": person["talks"][:2]}
    concepts = [r[0] for r in G.ro("""MATCH (p:Person {id: $id})-[r:RELATES]->(c) WHERE NOT c:Person
                                      RETURN c.name LIMIT 8""", id=G.person_id(name))]
    return {"common_ground": None, "their_topics": concepts}


def where_to_find(name: str) -> dict:
    pid = G.person_id(name)
    rows = G.ro("""MATCH (s:Person {id: $id})-[:PRESENTS]->(t:Talk)
                   RETURN t.title, t.kind, t.day, t.time, t.location, t.source_url ORDER BY t.day, t.time""", id=pid)
    return {"name": name, "talks": [dict(zip(["title", "kind", "day", "time", "location", "source_url"], r)) for r in rows]}


def remember_meeting(name: str, notes: str, where: str = "") -> dict:
    pid = G.person_id(name)
    G.q("""MATCH (me:Me) MERGE (p:__Entity__:Person {id: $pid}) ON CREATE SET p.name = $name
           MERGE (me)-[m:MET]->(p) SET m.notes = $notes, m.where = $where, m.at = $at, m.follow_up = 'pending'""",
        pid=pid, name=name, notes=notes, where=where, at=_now())
    view = {"kind": "memory", "generated_at": _now(), "event": f"Remembered meeting {name}", **recall_me(publish_view=False)}
    publish(view)
    return {"ok": True, "remembered": name, "notes": notes, "where": where}


def want_to_meet(name: str, reason: str) -> dict:
    G.q("""MATCH (me:Me), (p:Person {id: $pid}) MERGE (me)-[w:WANTS_TO_MEET]->(p)
           SET w.reason = $reason, w.at = $at""", pid=G.person_id(name), reason=reason, at=_now())
    return {"ok": True, "shortlisted": name}


def recall_me(publish_view: bool = True) -> dict:
    me = G.ro("MATCH (me:Me) RETURN me.name, me.description")
    problems = [r[0] for r in G.ro("MATCH (:Me)-[:RELATES {rel_type: 'FACES'}]->(p) RETURN p.name")]
    met = [{"name": r[0], "company": r[1], "notes": r[2], "where": r[3], "at": r[4], "follow_up": r[5]}
           for r in G.ro("""MATCH (:Me)-[m:MET]->(p) RETURN p.name, p.company, m.notes, m.where, m.at, m.follow_up
                            ORDER BY m.at DESC""")]
    shortlist = [{"name": r[0], "reason": r[1]} for r in G.ro("MATCH (:Me)-[w:WANTS_TO_MEET]->(p) RETURN p.name, w.reason")]
    intros = [{"name": r[0], "status": r[1], "at": r[2]} for r in G.ro(
        "MATCH (:Me)-[i:INTRO]->(p) RETURN p.name, i.status, i.at ORDER BY i.at DESC")]
    out = {"me": me[0][0] if me else None, "problems": problems, "met": met, "shortlist": shortlist, "intros": intros}
    if publish_view:
        publish({"kind": "memory", "generated_at": _now(), **out})
    return out


def record_intro(name: str, message: str, status: str) -> dict:
    G.q("""MATCH (me:Me), (p:Person {id: $pid}) MERGE (me)-[i:INTRO]->(p)
           SET i.message = $msg, i.status = $status, i.at = $at
           WITH p OPTIONAL MATCH (:Me)-[m:MET]->(p) SET m.follow_up = CASE WHEN m IS NULL THEN NULL ELSE $status END""",
        pid=G.person_id(name), msg=message, status=status, at=_now())
    outbox = settings.data_dir / "outbox.json"
    items = json.loads(outbox.read_text()) if outbox.exists() else []
    items.insert(0, {"to": name, "message": message, "status": status, "at": _now()})
    outbox.write_text(json.dumps(items, indent=1))
    publish({"kind": "sent", "generated_at": _now(), "to": name, "message": message, "status": status})
    return {"ok": True, "to": name, "status": status}


def publish(view: dict):
    VIEW_PATH.write_text(json.dumps(view, indent=1, default=str))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
