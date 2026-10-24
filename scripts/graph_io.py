"""Export Capy's graph to a portable file, or load that file into another FalkorDB (e.g. FalkorDB Cloud).

  python -m scripts.graph_io export data/export/capy-graph.jsonl.gz
  python -m scripts.graph_io load   data/export/capy-graph.jsonl.gz   # uses FALKORDB_* from .env

Vectors (`embedding` on chunks, entities and RELATES edges) are restored as vecf32, and the GraphRAG
vector/fulltext indexes are recreated, so retrieval works the same on the target instance.
"""
import asyncio
import gzip
import json
import sys

from capy import graph as G
from capy.config import settings

VECTOR_PROPS = {"embedding"}
BATCH = 300


def export(path: str):
    g = G.graph()
    out = gzip.open(path, "wt")
    n = e = 0
    skip = 0
    while True:
        rows = g.ro_query("MATCH (x) RETURN id(x), labels(x), properties(x) ORDER BY id(x) SKIP $s LIMIT 2000",
                          {"s": skip}).result_set
        for nid, labels, props in rows:
            out.write(json.dumps({"t": "n", "id": nid, "labels": labels, "props": props}) + "\n")
        n += len(rows)
        skip += len(rows)
        if len(rows) < 2000:
            break
    skip = 0
    while True:
        rows = g.ro_query("""MATCH (a)-[r]->(b) RETURN id(a), id(b), type(r), properties(r)
                             ORDER BY id(r) SKIP $s LIMIT 2000""", {"s": skip}).result_set
        for a, b, typ, props in rows:
            out.write(json.dumps({"t": "e", "a": a, "b": b, "type": typ, "props": props}) + "\n")
        e += len(rows)
        skip += len(rows)
        if len(rows) < 2000:
            break
    out.close()
    print(f"exported {n} nodes, {e} edges -> {path}")


def _set_clause(var: str, props: dict) -> tuple[str, dict]:
    plain = {k: v for k, v in props.items() if k not in VECTOR_PROPS}
    vecs = {k: v for k, v in props.items() if k in VECTOR_PROPS and isinstance(v, list)}
    parts = [f"{var} += row.plain"] + [f"{var}.{k} = vecf32(row.vec_{k})" for k in vecs]
    return ", ".join(parts), {"plain": plain, **{f"vec_{k}": v for k, v in vecs.items()}}


def load(path: str):
    g = G.graph()
    by_labels: dict[tuple, list] = {}
    edges: dict[tuple, list] = {}
    for line in gzip.open(path, "rt"):
        rec = json.loads(line)
        if rec["t"] == "n":
            key = (tuple(rec["labels"]), tuple(sorted(k for k in rec["props"] if k in VECTOR_PROPS)))
            by_labels.setdefault(key, []).append(rec)
        else:
            key = (rec["type"], tuple(sorted(k for k in rec["props"] if k in VECTOR_PROPS)))
            edges.setdefault(key, []).append(rec)
    g.query("CREATE INDEX FOR (n:__capy_import__) ON (n.__iid)")
    for (labels, vec_keys), recs in by_labels.items():
        lbl = ":".join(f"`{l}`" for l in labels) or "`__node__`"
        sets = ", ".join(["n += row.plain"] + [f"n.{k} = vecf32(row.vec_{k})" for k in vec_keys])
        for i in range(0, len(recs), BATCH):
            rows = [{"iid": r["id"], "plain": {k: v for k, v in r["props"].items() if k not in VECTOR_PROPS},
                     **{f"vec_{k}": r["props"][k] for k in vec_keys}} for r in recs[i:i + BATCH]]
            g.query(f"UNWIND $rows AS row CREATE (n:{lbl}:__capy_import__ {{__iid: row.iid}}) SET {sets}", {"rows": rows})
    for (typ, vec_keys), recs in edges.items():
        sets = ", ".join(["r += row.plain"] + [f"r.{k} = vecf32(row.vec_{k})" for k in vec_keys])
        for i in range(0, len(recs), BATCH):
            rows = [{"a": r["a"], "b": r["b"], "plain": {k: v for k, v in r["props"].items() if k not in VECTOR_PROPS},
                     **{f"vec_{k}": r["props"][k] for k in vec_keys}} for r in recs[i:i + BATCH]]
            g.query(f"""UNWIND $rows AS row
                        MATCH (a:__capy_import__ {{__iid: row.a}}), (b:__capy_import__ {{__iid: row.b}})
                        CREATE (a)-[r:`{typ}`]->(b) SET {sets}""", {"rows": rows})
    g.query("MATCH (n:__capy_import__) REMOVE n:__capy_import__, n.__iid")
    g.query("DROP INDEX FOR (n:__capy_import__) ON (n.__iid)")
    asyncio.run(_indexes())
    stats = g.ro_query("MATCH (n) RETURN count(n)").result_set[0][0]
    print(f"loaded {stats} nodes into {settings.falkordb_host}:{settings.falkordb_port}/{settings.graph_name}")


async def _indexes():
    rag = G.rag()
    try:
        await rag.finalize()  # recreates vector + fulltext indexes; nothing left to dedup
    except Exception as e:  # noqa: BLE001
        print(f"index rebuild note: {str(e)[:200]}")


if __name__ == "__main__":
    {"export": export, "load": load}[sys.argv[1]](sys.argv[2] if len(sys.argv) > 2 else "data/export/capy-graph.jsonl.gz")
