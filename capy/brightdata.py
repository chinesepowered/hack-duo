"""Bright Data helpers: Scraper API (sync with snapshot fallback) and batched SERP via the MCP server."""
import asyncio
import json
import re
import time
from datetime import datetime, timezone

import httpx

from capy import bdmcp
from capy.config import settings

API = "https://api.brightdata.com"

LINKEDIN_POSTS = "gd_lyy3tktm25m4avu764"
LINKEDIN_PROFILES = "gd_l1viktl72bvl7bjuj0"
YOUTUBE_VIDEOS = "gd_lk56epmy2i5g7lzu0k"
X_PROFILES = "gd_lwxmeb2u1cniijd7t4"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _client() -> httpx.Client:
    return httpx.Client(base_url=API, timeout=120,
                        headers={"Authorization": f"Bearer {settings.brightdata_api_key}"})


def wait_snapshot(c: httpx.Client, snapshot_id: str, timeout_s: int = 900) -> list[dict]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = c.get(f"/datasets/v3/progress/{snapshot_id}").json().get("status")
        if status == "ready":
            return c.get(f"/datasets/v3/snapshot/{snapshot_id}", params={"format": "json"}).json()
        if status in ("failed", "canceled"):
            raise RuntimeError(f"snapshot {snapshot_id} {status}")
        time.sleep(10)
    raise TimeoutError(f"snapshot {snapshot_id} not ready after {timeout_s}s")


def scrape(dataset_id: str, inputs: list[dict], discover_by: str | None = None,
           limit_per_input: int | None = None) -> list[dict]:
    """Synchronous Scraper API call; a job that outlives the 1-minute window comes back as a
    snapshot (HTTP 202), which we poll. Records with an `error` field are kept so callers can
    see which inputs failed instead of silently losing them."""
    params = {"dataset_id": dataset_id, "format": "json", "include_errors": "true", "notify": "false"}
    if discover_by:
        params |= {"type": "discover_new", "discover_by": discover_by}
    with _client() as c:
        r = c.post("/datasets/v3/scrape", params=params,
                   json={"input": inputs, "limit_per_input": limit_per_input})
        if r.status_code == 202:
            return wait_snapshot(c, r.json()["snapshot_id"])
        r.raise_for_status()
        if "application/json" in r.headers.get("content-type", ""):
            data = r.json()
            return data if isinstance(data, list) else [data]
        return [json.loads(line) for line in r.text.splitlines() if line.strip()]


def trigger(dataset_id: str, inputs: list[dict], discover_by: str | None = None,
            limit_per_input: int | None = None) -> str:
    """Async batch job: one request for many inputs (avoids the per-IP 429 limit)."""
    params = {"dataset_id": dataset_id, "include_errors": "true"}
    if discover_by:
        params |= {"type": "discover_new", "discover_by": discover_by}
    if limit_per_input:
        params["limit_per_input"] = limit_per_input
    with _client() as c:
        r = c.post("/datasets/v3/trigger", params=params, json=inputs)
        r.raise_for_status()
        return r.json()["snapshot_id"]


def collect(snapshot_id: str, timeout_s: int = 900) -> list[dict]:
    with _client() as c:
        return wait_snapshot(c, snapshot_id, timeout_s)


async def serp(queries: list[str], concurrency: int = 8) -> dict[str, list[dict]]:
    """Google results (structured JSON) through the Web Unlocker zone, many queries in parallel,
    each with a timeout and retries so one slow request can't stall the whole run."""
    from urllib.parse import quote_plus
    sem, out, done = asyncio.Semaphore(concurrency), {}, 0
    async with httpx.AsyncClient(timeout=60, headers={"Authorization": f"Bearer {settings.brightdata_api_key}"}) as c:
        async def one(q):
            nonlocal done
            async with sem:
                for attempt in range(3):
                    try:
                        r = await c.post(f"{API}/request", json={
                            "zone": settings.brightdata_unlocker_zone, "format": "raw",
                            "url": f"https://www.google.com/search?q={quote_plus(q)}&hl=en&gl=us&brd_json=1"})
                        r.raise_for_status()
                        out[q] = r.json().get("organic", [])
                        break
                    except (httpx.HTTPError, ValueError) as e:
                        if attempt == 2:
                            print(f"  serp failed for {q[:50]}: {str(e)[:80]}", flush=True)
                            out[q] = []
                        await asyncio.sleep(2 ** (attempt + 1))
                done += 1
                if done % 20 == 0 or done == len(queries):
                    print(f"  serp {done}/{len(queries)}", flush=True)
        await asyncio.gather(*(one(q) for q in queries))
    return out


async def serp_batch(queries: list[str]) -> dict[str, list[dict]]:
    """Google results for many queries via the MCP `search_engine_batch` tool (10 per call)."""
    out: dict[str, list[dict]] = {}
    async with bdmcp.session("advanced_scraping") as s:
        for i in range(0, len(queries), 10):
            chunk = queries[i:i + 10]
            for attempt in range(4):  # transient 5xx happen; back off 2s, 4s, 8s
                try:
                    raw = await bdmcp.call(s, "search_engine_batch",
                                           queries=[{"query": q, "engine": "google"} for q in chunk])
                    break
                except RuntimeError as e:
                    print(f"  serp batch {i // 10} attempt {attempt + 1} failed: {str(e)[:80]}", flush=True)
                    await asyncio.sleep(2 ** (attempt + 1))
            else:
                raw = "[]"  # give up on this batch; those speakers stay unresolved
            for q, res in zip(chunk, _split_batch(raw, len(chunk))):
                out[q] = res
    return out


def _split_batch(raw: str, n: int) -> list[list[dict]]:
    """Pull the organic results for each query out of the batch tool's text output."""
    body = re.sub(r"^SECURITY NOTICE:.*$|^=====UNTRUSTED_[0-9a-f]+_(BEGIN|END)=====$", "", raw, flags=re.M).strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        start = body.find("[")
        data = json.loads(body[start:]) if start >= 0 else []
    results = []
    for item in (data if isinstance(data, list) else [data])[:n]:
        res = item.get("result", item) if isinstance(item, dict) else item
        if isinstance(res, str):
            try:
                res = json.loads(res)
            except json.JSONDecodeError:
                res = {}
        results.append(res.get("organic", []) if isinstance(res, dict) else [])
    return results + [[] for _ in range(n - len(results))]


if __name__ == "__main__":
    print(json.dumps(asyncio.run(serp_batch(['"Cassidy Williams" GitHub linkedin'])), indent=1)[:1500])
