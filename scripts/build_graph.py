"""Build Capy's knowledge graph in FalkorDB.

1. Structured layer: Talk nodes + speaker Person nodes (same ids GraphRAG uses, so extraction merges in).
2. GraphRAG SDK ingestion (OpenAI extraction) of talk abstracts, speakers' LinkedIn posts and the persona.
3. Provenance: every Document gets source_url / collector / fetched_at and an AUTHORED edge from its author.
4. finalize(): entity dedup, relationship embeddings, vector + fulltext indexes.

usage: python -m scripts.build_graph [--limit N] [--only talks,posts,persona] [--no-finalize]
"""
import argparse
import asyncio
import hashlib
import json
import time

from graphrag_sdk import GraphExtraction, LLMExtractor

from capy import graph as G
from capy.config import settings

RAW = settings.data_dir / "raw"
EVENT = "GitHub Universe 2026"


def slug(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def talk_docs(sessions: list[dict]) -> list[dict]:
    docs = []
    for s in sessions:
        if not s["speakers"] or len(s["description"]) < 40:
            continue
        by = "; ".join(f'{p["name"]} ({p["title"]}, {p["company"]})' for p in s["speakers"])
        docs.append({
            "id": f"talk:{slug(s['title'], s['day'], s['time'])}", "kind": "talk", "authors": [p["name"] for p in s["speakers"]],
            "source_url": s["source_url"], "collector": s["collector"], "fetched_at": s["fetched_at"],
            "text": f'{EVENT} session: "{s["title"]}" ({s["kind"]}), {s["day"]} {s["time"]}, {s["location"]}.\n'
                    f"Presented by: {by}.\n\nAbstract: {s['description']}",
        })
    return docs


def post_docs(posts: list[dict], people: dict[str, dict]) -> list[dict]:
    docs = []
    for p in posts:
        who = p.get("speaker")
        if not who or who not in people:
            continue
        role = f'{people[who]["title"]} at {people[who]["company"]}'
        docs.append({
            "id": f"linkedin:{slug(p['url'] or p['text'][:80])}", "kind": "linkedin_post", "authors": [who],
            "source_url": p["url"], "collector": p["collector"], "fetched_at": p["fetched_at"],
            "date_posted": p.get("date_posted"),
            "text": f"LinkedIn post by {who} ({role}), posted {str(p.get('date_posted') or '')[:10]}:\n\n{p['text'][:2500]}",
        })
    return docs


def persona_doc() -> dict:
    return {"id": "persona:maya", "kind": "persona", "authors": ["Maya Chen"], "source_url": "capy://persona/maya",
            "collector": "capy:persona", "fetched_at": "2026-10-24T00:00:00+00:00", "text": G.PERSONA}


def write_structured(sessions: list[dict], identities: dict[str, dict], avatars: dict[str, str]):
    for s in sessions:
        tid = f"talk:{slug(s['title'], s['day'], s['time'])}"
        G.q("""MERGE (t:Talk {id: $id})
               SET t.title = $title, t.kind = $kind, t.description = $desc, t.day = $day, t.time = $time,
                   t.location = $loc, t.source_url = $url, t.fetched_at = $fetched, t.collector = $collector""",
            id=tid, title=s["title"], kind=s["kind"], desc=s["description"], day=s["day"], time=s["time"],
            loc=s["location"], url=s["source_url"], fetched=s["fetched_at"], collector=s["collector"])
        for sp in s["speakers"]:
            ident = identities.get(sp["name"], {})
            G.q("""MERGE (p:__Entity__:Person {id: $pid})
                   ON CREATE SET p.name = $name
                   SET p:Speaker, p.title = $title, p.company = $company, p.linkedin_url = $li,
                       p.linkedin_confidence = $conf, p.avatar = coalesce($avatar, p.avatar)
                   WITH p MATCH (t:Talk {id: $tid}) MERGE (p)-[:PRESENTS]->(t)""",
                pid=G.person_id(sp["name"]), name=sp["name"], title=sp["title"], company=sp["company"],
                li=ident.get("linkedin_url"), conf=ident.get("confidence", 0.0), avatar=avatars.get(sp["name"]), tid=tid)


def write_provenance(docs: list[dict]):
    for d in docs:
        G.q("""MATCH (doc:Document {path: $id})
               SET doc.kind = $kind, doc.source_url = $url, doc.collector = $collector,
                   doc.fetched_at = $fetched, doc.date_posted = $posted
               WITH doc UNWIND $authors AS author
               MERGE (a:__Entity__:Person {id: author.pid}) ON CREATE SET a.name = author.name
               MERGE (a)-[:AUTHORED]->(doc)""",
            id=d["id"], kind=d["kind"], url=d["source_url"], collector=d["collector"], fetched=d["fetched_at"],
            posted=d.get("date_posted"), authors=[{"pid": G.person_id(n), "name": n} for n in d["authors"]])
    G.q("MATCH (me:Person {id: $me}) SET me:Me", me=G.ME)


def already_ingested() -> set[str]:
    try:
        return {r[0] for r in G.ro("MATCH (d:Document) RETURN d.path")}
    except Exception:  # noqa: BLE001 - graph may not exist yet
        return set()


async def ingest(docs: list[dict], concurrency: int):
    rag = G.rag()
    # LLM-only extraction (OpenAI does NER + relations); the default local NER model is heavy on CPU.
    extractor = GraphExtraction(rag.llm, entity_extractor=LLMExtractor(rag.llm, threshold=0.6),
                                entity_types=[e.label for e in G.ONTOLOGY.entities])
    done = already_ingested()
    todo = [d for d in docs if d["id"] not in done]
    print(f"ingesting {len(todo)} docs ({len(docs) - len(todo)} already in graph)", flush=True)
    sem, t0, ok = asyncio.Semaphore(concurrency), time.time(), 0

    async def one(d):
        nonlocal ok
        async with sem:
            try:
                r = await rag.ingest(text=d["text"], document_id=d["id"], extractor=extractor)
                ok += 1
                if ok % 10 == 0 or ok == len(todo):
                    print(f"  {ok}/{len(todo)} docs, {time.time() - t0:.0f}s (last: +{r.nodes_created} nodes, "
                          f"+{r.relationships_created} rels)", flush=True)
            except Exception as e:  # noqa: BLE001 - keep going; report failures
                print(f"  FAILED {d['id']}: {str(e)[:160]}", flush=True)

    await asyncio.gather(*(one(d) for d in todo))
    return rag


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="talks,posts,persona")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--no-finalize", action="store_true")
    a = ap.parse_args()
    sessions = list({(s["title"], s["day"], s["time"]): s
                     for s in json.loads((RAW / "sessions.json").read_text())}.values())
    identities = json.loads((RAW / "identities.json").read_text()) if (RAW / "identities.json").exists() else {}
    posts = json.loads((RAW / "linkedin_posts.json").read_text()) if (RAW / "linkedin_posts.json").exists() else []
    people = {sp["name"]: sp for s in sessions for sp in s["speakers"]}
    avatars = {p["speaker"]: p["avatar"] for p in posts if p.get("speaker") and p.get("avatar")}

    write_structured(sessions, identities, avatars)
    docs = []
    if "persona" in a.only:
        docs.append(persona_doc())
    if "talks" in a.only:
        docs += talk_docs(sessions)
    if "posts" in a.only:
        docs += post_docs(posts, people)
    if a.limit:
        docs = docs[: a.limit]
    rag = await ingest(docs, a.concurrency)
    write_provenance(docs)
    if not a.no_finalize:
        t0 = time.time()
        res = await rag.finalize()
        print(f"finalize: {time.time() - t0:.0f}s, deduped={res.entities_deduplicated}, "
              f"embedded={res.entities_embedded} entities / {res.relationships_embedded} rels", flush=True)
    stats = G.ro("MATCH (n) RETURN labels(n)[0] AS l, count(*) ORDER BY count(*) DESC")
    print("nodes:", stats[:12])
    print("rels:", G.ro("MATCH ()-[r:RELATES]->() RETURN r.rel_type, count(*) ORDER BY count(*) DESC")[:12])


if __name__ == "__main__":
    asyncio.run(main())
