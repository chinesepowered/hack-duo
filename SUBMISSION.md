# Capy Pals — submission answers

Copy-paste sheet for the Patch the Conference submission form, in the form's order.
Video timestamps refer to `capy-pals-demo.mp4` (2:32).

---

## Part 1 — Project details

**Project title**
Capy Pals 🦫 — meet the people at the conference who already solved your problem

**Repository**
https://github.com/chinesepowered/hack-duo

**Demo video** (public or unlisted)
_paste the YouTube (unlisted) / Loom / Drive link_. The file is also in the repo: https://github.com/chinesepowered/hack-duo/blob/main/demo/capy-pals-demo.mp4

**Live demo or deployment** (optional)
Runs live on stage (TrueForge + our capy-graph MCP server on FalkorDB Cloud). Anyone can run it with `./start.sh`; see the README.

**Track(s)**
FalkorDB · Bright Data · TrueFoundry (TrueForge) with OpenAI

**What conference problem are you patching?**
Conferences are full of people who have already solved your problem, and you never find them. GitHub Universe 2026 has 162 sessions and 183 speakers in two days. Working out which three of them are worth your time means hours of reading abstracts and LinkedIn, and by the next morning the people you did meet have blurred together and the follow-ups never get sent. Capy patches the hallway track: it tells you who already solved your problem (with receipts), where and when to catch them, remembers who you met, and drafts follow-ups that only go out after you approve them.

**What did you build and how does it work?**
Capy Pals is a capybara agent for attendees (capybaras are famously friends with everyone).
1. Data (Bright Data): the Browser API renders the Universe session catalog, a JavaScript app, into 162 sessions and 183 speakers; SERP via Web Unlocker matches 124 speakers to their LinkedIn profiles with confidence scores; the LinkedIn posts Scraper API pulls 227 recent posts.
2. Graph (FalkorDB): the GraphRAG SDK, running on OpenAI, turns 365 documents into a typed knowledge graph of 2,393 entities and 1,911 facts (e.g. David Pereira PRACTICES "enforcing team-specific standards in code review"), linked to talks, rooms and times, plus the user's own memory.
3. Agent (TrueForge + OpenAI gpt-6-luna): ask "who here already solved X?" and Capy walks the graph from your problem to similar problems, to the speakers who solved them, to the session where you can catch them. The Capy panel lights up that path live, and every claim carries a receipt: the speaker's own words, the source, and when Bright Data fetched it.
4. It plans your days in a sandbox (Code Mode), looks people up live when you bump into them, remembers meetings across sessions, and a scheduled morning agent drafts follow-ups that wait for your Allow.

---

## Part 2 — Track details

**How did you use FalkorDB and what problems did you solve using it?**
FalkorDB is the product, not storage.
- Multi-hop + vector in one graph: the user's problem → vector index over entity embeddings → similar Problem/Practice/Tool nodes (materialised as SIMILAR_TO edges with their score) → the Speaker who SOLVED / BUILT / PRACTICES it, or 2 hops via ADDRESSES → PRESENTS → Talk (day, time, room). A chunk-vector path (Chunk → Document ← AUTHORED ← Speaker) backs it up. The GraphRAG SDK built it from 365 documents: 2,393 entities and 1,911 facts, with the provenance chain Document → Chunk ← MENTIONED_IN ← Entity.
- Explainable: every answer returns its graph path, and the Capy panel renders it with @falkordb/canvas (video 0:27–0:55). Example: Maya → FACES → "code review cannot keep up with AI-generated pull requests" → SIMILAR_TO (0.57) → "custom code review agent" ← ADDRESSES ← "enforcing team-specific standards in code review" ← PRACTICES ← David Pereira → PRESENTS → "What Copilot code review catches (and how to build a custom agent for the rest)". Every hop is a real edge; every claim cites the chunk it came from.
- Memory: (:Me)-[:MET {notes, where, follow_up}]->(:Person), plus WANTS_TO_MEET and INTRO. A brand-new session still knows who you met and who is waiting on a follow-up (video 1:39).
- Shared state between agents: the chat agent writes MET edges; a separate scheduled agent (capy-followup, daily at 8 AM) reads them, drafts the follow-ups, and flips follow_up to "sent" after approval.
- Live updates: a fresh lookup is ingested incrementally with GraphRAG `update` (a no-op when the content hash is unchanged) and cleaned up with `delete_document`.
- Who uses it: attendees looking for peers who already solved their problem; speakers, who get the right people at their sessions; organisers, who could run it as official matchmaking.

**How did you use Bright Data and what problems did you solve using it?**
Capy only works because of data a basic script can't reach.
- Hard-to-reach sources: (1) the GitHub Universe session catalog, a RainFocus JavaScript app that returns an empty shell to plain HTTP and paginates behind "Show more", rendered and clicked through with the Browser API (Bright Data MCP browser tools): 162 sessions, 183 speakers; (2) Google SERP via Web Unlocker to resolve each speaker to LinkedIn: 124/183, each with a confidence score (name + company match); (3) the LinkedIn posts Scraper API, one batched job for authored posts since Oct 2025: 227 posts; (4) live at the event, a Web Unlocker fetch of someone's public LinkedIn profile, with the LinkedIn profile Scraper API as fallback (video 1:29).
- Accuracy: every document carries source_url, collector and fetched_at, shown on every receipt ("LinkedIn profile · via Bright Data Web Unlocker · fetched 1:24 PM"). The 59 unresolved speakers keep their catalog data instead of a guessed profile. Live pages keep only the person's own words (About, posts, certifications, recommendations); sign-in chrome and reposts are stripped, turning an 85 KB page into 4.5 KB of signal. A re-lookup replaces the old copy instead of piling up stale duplicates.
- When a site changes or a request fails: retries with backoff; empty responses are retried; Web Unlocker falls back to the Scraper API; if both fail, Capy says so and answers from what the graph already knows. The catalog parser anchors on stable fields (day and time lines) of the rendered page and keeps the raw text, so a layout change means re-parsing, not re-scraping.
- Saves time: hours of agenda-reading and profile-stalking become the three people worth meeting, where and when to catch them, a clash-free plan, and a follow-up drafted from their own words.

**How did you use TrueFoundry and OpenAI and what problems did you solve using it?**
- Built on TrueForge: everything (model provider, MCP servers, Daytona sandbox, skill, agents, schedule) is configured through TrueForge's REST API by one idempotent script (scripts/setup_trueforge.py), so a fresh `npx @truefoundry/trueforge` ends up identical.
  - Agents: `capy` (chat) and `capy-followup` (daily 8 AM schedule; "Run now" on stage).
  - MCP tools: our capy-graph server plus the Bright Data remote MCP, discovered on demand (deferred tool loading).
  - Approvals: `send_intro` is in require_approval_for_tools, so TrueForge shows the exact message and waits for Allow / Deny before anything reaches a person (video 1:48).
  - Sandbox / Code Mode: Capy writes Python in a Daytona sandbox that calls `where_to_find` for each speaker through the MCP client, sorts the sessions and checks for clashes (video 0:55).
  - Skill: `capy-intro`, a receipt-grounded intro playbook, imported from our repo. Generative UI cards for the picks; sub-agents enabled.
- OpenAI does the heavy lifting: gpt-6-luna runs both agents (tool planning, writing the sandbox scripts, drafting follow-ups) and every GraphRAG extraction over the 365 documents; text-embedding-3-small powers the vector search over entities, chunks and the user's problems; gpt-6-luna also reranks evidence relevance, and the embeddings match fresh profile sentences to the user's problems.
- Who uses it: attendees at any multi-track conference (Universe here), and organisers who want matchmaking that explains itself and never sends anything without consent.

**Qodo track PR links**
N/A (we're not entering the Qodo track)

---

## Part 3 — Feedback (optional)

**FalkorDB: what we liked, what we'd improve**
Liked: the GraphRAG SDK's incremental `update` and `delete_document` (crash-safe, content-hash no-op) made live lookups clean; vector search and graph traversal in one Cypher query; @falkordb/canvas dropped straight into our UI for the lit path.
Improve: vector `queryNodes` returns cosine *distance* as `score`, which is easy to misread as similarity and worth calling out in the docs; a stored ontology can't be extended, so adding one relation pattern meant rebuilding the graph; relations that don't match the ontology are pruned with only a log warning; the default GLiNER extractor hit protobuf/sentencepiece install issues, so we used the LLM extractor; FalkorDB Cloud speaks only the Redis protocol, which HTTP-only networks (cloud dev boxes, agent sandboxes) can't reach, so an HTTPS or WebSocket endpoint would help.

**Bright Data: what we liked, what we'd improve**
Liked: the Browser API over MCP rendered and paginated a JavaScript catalog with no custom scraper; Web Unlocker with `brd_json` gave structured SERP results; one Scraper API job pulled 227 LinkedIn posts; the remote MCP plugs straight into agents.
Improve: `search_engine_batch` over MCP returned 502s and hung under load (we moved to the REST API); Google's `site:` operator is ignored in SERP JSON; Web Unlocker with `data_format: markdown` occasionally answers 200 with an empty body; a "main content only" option for LinkedIn pages would save cleanup (85 KB of page chrome around 4.5 KB of content); the LinkedIn profile dataset no longer includes experience/education.

**TrueFoundry: what we liked, what we'd improve**
Liked: every piece is configurable over REST, so our whole setup is one script; per-tool approvals that show the exact payload; Code Mode calling MCP tools from the sandbox; schedules with "Run now".
Improve: MCP servers on localhost are blocked until you set OUTBOUND_URL_ALLOWED_HOSTS, which is easy to miss in a local setup; skills register without checking that the repo is reachable; agents sometimes ask "should I send this?" before a tool that is already approval-gated (double confirmation); a few turns stalled for minutes with no error until cancelled; field naming varies across endpoints (`agent_name` vs `agentName`); tools without an outputSchema make Code Mode inspect a sample response first.

---

## Stage demo script (~4 min)

Open the TrueForge chat (left) and the Capy panel `localhost:8001/?side` (right). Run `python -m scripts.reset_demo` first.
1. *"Hi Capy! Code review can't keep up with all the AI-generated pull requests on my team. Who here already solved that?"* → the lit path + receipts (source + fetched-at).
2. *"Plan my two days so I can catch all three. Write a quick sandbox script that pulls their sessions through the graph tools, sorts them by time and flags any clashes."* → open Agent steps → the Code Mode script.
3. *"I just bumped into Andy Kelly from Precisely at the badge party! Look Andy up fresh. What do we have in common?"* → live Bright Data fetch (~45–60 s); the first receipt comes from the fresh profile.
4. *"Remember that I met David Pereira after the Copilot code review session. We swapped notes on PR review load, and I promised to send over our numbers: agent PRs tripled since June, and our median review wait is 2.5 days."*
5. **Schedules → capy-morning-followups → Run now** → open the new capy-followup session: a second agent read the meeting from FalkorDB and drafted the follow-up → **Allow** → "Sent" toast in the Capy panel (demo outbox). If Capy also logged Andy in step 3, you'll get a draft for each.
   (Shorter alternative: New Chat → *"Good morning Capy! ☕ Who am I waiting to follow up with?"* → *"Please draft a short follow-up to David and send it."* → **Allow**.)

If the venue Wi-Fi fails, play the video.
