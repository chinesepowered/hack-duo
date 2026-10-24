"""Fetch the conference session catalog through Bright Data's Browser API (via its MCP server).

RainFocus catalogs are JS-rendered and paginated behind a "Show more" button, so a plain HTTP
fetch only returns an app shell. We drive a remote Bright Data browser, click until every
session is loaded, then save the raw text (with provenance) and a parsed sessions.json.

usage: python -m scripts.fetch_catalog [catalog_url]
"""
import asyncio
import json
import re
import sys
from datetime import datetime, timezone

from capy.bdmcp import call, session
from capy.config import settings

DEFAULT_URL = "https://reg.githubuniverse.com/flow/github/universe26/attendee-portal/page/sessioncatalog"
RAW = settings.data_dir / "raw"
UNTRUSTED = re.compile(r"^(SECURITY NOTICE:.*|=====UNTRUSTED_[0-9a-f]+_(BEGIN|END)=====)$")
DAY = re.compile(r"^(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day, \w{3} \d{1,2}$")
TIME = re.compile(r"^\d{1,2}:\d{2} [AP]M - \d{1,2}:\d{2} [AP]M \w+$")
FLAGS = {"In-person", "Recorded", "Livestream", "AI summary", "Virtual"}
KINDS = {"Keynote", "Breakout Session", "Product Demo", "Ship & Tell", "Sandbox Session", "Special Event",
         "Main Stage", "Session After Party", "Social", "Workshop", "Lightning Talk", "Panel", "Fireside Chat"}


def reparse(path=None):
    """Re-parse a saved catalog_text.txt without re-fetching (keeps the original provenance)."""
    raw = RAW / "catalog_text.txt"
    prev = json.loads((RAW / "sessions.json").read_text()) if (RAW / "sessions.json").exists() else []
    meta = {k: prev[0][k] for k in ("source_url", "fetched_at", "collector")} if prev else {}
    sessions = parse(clean_lines(raw.read_text()))
    for s in sessions:
        s.update(meta)
    (RAW / "sessions.json").write_text(json.dumps(sessions, indent=2))
    return sessions


async def try_call(s, tool: str, **args) -> str | None:
    try:
        return await call(s, tool, **args)
    except Exception as e:  # noqa: BLE001 - a flaky click shouldn't kill the whole browser session
        print(f"  {tool} failed: {str(e)[:120]}", file=sys.stderr)
        return None


async def fetch_text(url: str) -> str:
    async with session("browser") as s:
        await call(s, "scraping_browser_navigate", url=url)
        await asyncio.sleep(10)
        loaded, clicks = 0, 0
        for _ in range(16):  # the list lazy-loads on scroll, then pages 50 at a time behind "Show more"
            await try_call(s, "scraping_browser_scroll")
            await asyncio.sleep(4)
            snap = await try_call(s, "scraping_browser_snapshot") or ""
            loaded = snap.count("See details")
            m = re.search(r'button "Show more" \[ref=([\w-]+)\]', snap)
            print(f"  loaded={loaded} show_more={'yes' if m else 'no'}", file=sys.stderr)
            if not m:
                if loaded:
                    break
                continue  # list not rendered yet; keep scrolling
            await try_call(s, "scraping_browser_scroll_to_ref", ref=m.group(1), element="Show more button")
            if await try_call(s, "scraping_browser_click_ref", ref=m.group(1), element="Show more button"):
                clicks += 1
            await asyncio.sleep(5)
        print(f"  done: {loaded} sessions after {clicks} clicks", file=sys.stderr)
        return await call(s, "scraping_browser_get_text")


def clean_lines(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines() if l.strip() and not UNTRUSTED.match(l.strip())]


def parse(lines: list[str]) -> list[dict]:
    """Each entry: title, type/flags, description, speakers, 'See details', day, time, location."""
    try:
        start = next(i for i, l in enumerate(lines) if re.match(r"^Thu, Oct \d+ \(\d+\)$", l)) + 1
    except StopIteration:
        start = 0
    sessions, i = [], start
    while i < len(lines):
        try:
            end = lines.index("See details", i)
        except ValueError:
            break
        body = lines[i:end]
        # footer: [button lines like "Add to agenda"] day, time, [location]; anchor on the day line
        j = end + 1
        while j < min(end + 4, len(lines)) and not DAY.match(lines[j]):
            j += 1
        day, time_, loc, nxt = "", "", "", end + 1
        if j < len(lines) and DAY.match(lines[j]) and j + 1 < len(lines) and TIME.match(lines[j + 1]):
            day, time_ = lines[j], lines[j + 1]
            has_loc = j + 3 >= len(lines) or lines[j + 3] not in KINDS
            loc = lines[j + 2] if has_loc and j + 2 < len(lines) else ""
            nxt = j + (3 if has_loc else 2)
        speakers, desc, kinds = [], [], []
        title = body[0] if body else ""
        j = 1
        while j < len(body) and (body[j] in FLAGS or len(body[j].split()) <= 3 and not body[j].endswith(".")):
            if j + 1 < len(body) and body[j + 1].startswith("/"):
                break  # this short line is a speaker name
            (kinds if body[j] not in FLAGS else kinds).append(body[j])
            j += 1
        k = j
        while k < len(body):
            if k + 1 < len(body) and body[k + 1].startswith("/") and k + 2 < len(body) and body[k + 2].startswith(","):
                role = body[k + 2].lstrip(", ").strip()
                parts = [p.strip() for p in role.split(",")]
                speakers.append({"name": body[k], "title": ", ".join(parts[:-1]), "company": parts[-1] if parts else ""})
                k += 3
            else:
                if not speakers:
                    desc.append(body[k])
                k += 1
        sessions.append(
            {
                "title": title,
                "kind": next((x for x in kinds if x not in FLAGS), ""),
                "flags": [x for x in kinds if x in FLAGS],
                "description": " ".join(desc).strip(),
                "speakers": speakers,
                "day": day,
                "time": time_,
                "location": loc,
            }
        )
        i = nxt
    return sessions


async def main(url: str):
    RAW.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    text = await fetch_text(url)
    (RAW / "catalog_text.txt").write_text(text)
    sessions = parse(clean_lines(text))
    for s in sessions:
        s.update(source_url=url, fetched_at=fetched_at, collector="brightdata:browser_api")
    (RAW / "sessions.json").write_text(json.dumps(sessions, indent=2))
    n_spk = len({sp["name"] for s in sessions for sp in s["speakers"]})
    print(f"{len(sessions)} sessions, {n_spk} unique speakers -> {RAW / 'sessions.json'}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL))
