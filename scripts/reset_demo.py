"""Reset Capy to a clean demo start: forget meetings, intros and the shortlist, and remove live lookups
(they are re-fetched fresh on stage). The built graph — talks, speakers, posts — is untouched.

  python -m scripts.reset_demo
"""
import asyncio

from capy import graph as G
from capy.config import settings


async def main():
    G.q("MATCH (:Me)-[r:MET|INTRO|WANTS_TO_MEET]->() DELETE r")
    docs = [r[0] for r in G.ro("MATCH (d:Document) WHERE d.id STARTS WITH 'linkedin-profile:' RETURN d.id")]
    rag = G.rag()
    for d in docs:  # SDK delete: chunks, orphaned entities and facts only this document supported
        await rag.delete_document(d, if_missing="ignore")
    for f in ("view.json", "outbox.json"):
        (settings.data_dir / f).unlink(missing_ok=True)
    print(f"reset: memory cleared, {len(docs)} live lookup(s) removed")


if __name__ == "__main__":
    asyncio.run(main())
