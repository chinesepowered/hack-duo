"""Resolve each speaker to a LinkedIn profile, then pull their recent authored posts.

1. Google (Bright Data SERP via MCP) for `"Name" Company site:linkedin.com/in`; accept a profile only when
   the result title carries the speaker's name, and score confidence higher when it also carries the company.
2. One batched Scraper API job: LinkedIn posts discovered by profile URL (authored only, recent).

Every record keeps where it came from and when, so answers can cite it and stale facts can be spotted.

usage: python -m scripts.research_speakers [--posts-per-person 3] [--since 2025-10-01]
"""
import argparse
import asyncio
import json
import re
import unicodedata

from capy import brightdata as bd
from capy.config import settings

RAW = settings.data_dir / "raw"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def speakers_from_sessions() -> dict[str, dict]:
    people: dict[str, dict] = {}
    for s in json.loads((RAW / "sessions.json").read_text()):
        for sp in s["speakers"]:
            p = people.setdefault(sp["name"], {**sp, "talks": []})
            p["talks"].append(s["title"])
    return people


def pick_profile(name: str, company: str, results: list[dict]) -> dict | None:
    n, c = norm(name), norm(company)
    first_last = n.split()
    for r in results:
        link = r.get("link", "")
        m = re.match(r"https?://([a-z]{2,3}\.)?linkedin\.com/in/([^/?#]+)", link)
        if not m:
            continue
        title = norm(r.get("title", "") + " " + r.get("description", ""))
        if not all(part in title for part in (first_last[0], first_last[-1])):
            continue
        conf = 0.9 if c and c.split()[0] in title else 0.7
        return {"linkedin_url": f"https://www.linkedin.com/in/{m.group(2)}", "confidence": conf,
                "evidence": r.get("title", "")[:160]}
    return None


async def resolve(people: dict[str, dict]) -> dict[str, dict]:
    queries = {name: f'"{name}" {p["company"]} linkedin' for name, p in people.items()}
    results = await bd.serp(list(queries.values()))
    out = {}
    for name, q in queries.items():
        hit = pick_profile(name, people[name]["company"], results.get(q, []))
        out[name] = {**(hit or {"linkedin_url": None, "confidence": 0.0}), "query": q,
                     "collector": "brightdata:serp", "fetched_at": bd.now()}
    return out


def fetch_posts(identities: dict[str, dict], per_person: int, since: str) -> list[dict]:
    targets = {v["linkedin_url"]: name for name, v in identities.items() if v.get("linkedin_url")}
    inputs = [{"url": url, "start_date": f"{since}T00:00:00.000Z", "only_authored_posts": True} for url in targets]
    snapshot = bd.trigger(bd.LINKEDIN_POSTS, inputs, discover_by="profile_url", limit_per_input=per_person)
    print(f"posts job {snapshot} for {len(inputs)} profiles…", flush=True)
    records = bd.collect(snapshot, timeout_s=1500)
    fetched_at = bd.now()
    posts = []
    for r in records:
        if r.get("error") or not r.get("post_text"):
            continue
        src = (r.get("input") or {}).get("url") or r.get("use_url") or ""
        author = targets.get(src) or next((n for u, n in targets.items() if r.get("user_id") and r["user_id"] in u), None)
        posts.append({"speaker": author, "url": r.get("url"), "date_posted": r.get("date_posted"),
                      "text": r["post_text"], "num_likes": r.get("num_likes"), "user_title": r.get("user_title"),
                      "avatar": r.get("author_profile_pic") or r.get("user_profile_pic"),
                      "collector": f"brightdata:scraper:{bd.LINKEDIN_POSTS}", "fetched_at": fetched_at})
    errors = sum(1 for r in records if r.get("error"))
    print(f"{len(posts)} posts kept, {errors} inputs errored", flush=True)
    return posts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--posts-per-person", type=int, default=3)
    ap.add_argument("--since", default="2025-10-01")
    ap.add_argument("--skip-resolve", action="store_true")
    a = ap.parse_args()
    people = speakers_from_sessions()
    ident_path = RAW / "identities.json"
    if a.skip_resolve and ident_path.exists():
        identities = json.loads(ident_path.read_text())
    else:
        identities = asyncio.run(resolve(people))
        ident_path.write_text(json.dumps(identities, indent=1))
    found = sum(1 for v in identities.values() if v.get("linkedin_url"))
    print(f"{found}/{len(people)} speakers resolved to LinkedIn profiles", flush=True)
    posts = fetch_posts(identities, a.posts_per_person, a.since)
    (RAW / "linkedin_posts.json").write_text(json.dumps(posts, indent=1))


if __name__ == "__main__":
    main()
