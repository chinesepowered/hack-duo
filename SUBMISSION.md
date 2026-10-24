# Capy Pals — submission notes

**One-liner:** Capy is friends with everyone — it finds the people at the conference who already solved
your problem, shows the receipts, tells you where to catch them, remembers who you met, and drafts
follow-ups that only send after you approve.

**Repo:** https://github.com/chinesepowered/hack-duo · **Video:** `demo/out/capy-pals-demo.mp4` (2–3 min)

---

## Track 1 — FalkorDB (graph at the core · explainable · real problem · live)
- **GraphRAG SDK** builds the knowledge graph from 365 real documents (162 Universe sessions' abstracts +
  227 speakers' LinkedIn posts): ~2,400 typed entities and ~1,900 facts (`SOLVED`, `PRACTICES`, `BUILT`, …).
- **Multi-hop + vector in one query plan**: Maya's problem → vector-similar problems/practices (stored as
  `SIMILAR_TO` edges) → the speaker who `SOLVED` it (or 2 hops via `ADDRESSES`) → `PRESENTS` → the talk, room and time.
- **Explainable**: every answer comes with its path, rendered live with **@falkordb/canvas** ("the lit path is
  the proof"), and every claim cites the GraphRAG chunk it came from.
- **Memory across sessions** (`MET`, `WANTS_TO_MEET`, `INTRO` edges) and **shared state between agents**:
  the chat agent writes meetings, the scheduled follow-up agent reads them.

## Track 2 — Bright Data (hard-to-get data · data quality · usefulness · live)
- The Universe catalog is a **JavaScript app** (RainFocus) — plain HTTP returns an empty shell. Bright Data's
  **Browser API** (MCP browser tools) renders it and clicks through pagination: 162 sessions, 183 speakers.
- **SERP via Web Unlocker** resolves speakers to LinkedIn profiles with confidence scores (124/183);
  the **LinkedIn posts Scraper API** pulls 227 recent authored posts in one batched job.
- **Live lookup** at the event: Web Unlocker fetch of a fresh profile with a **Scraper API fallback**,
  ingested into the graph in ~30 s.
- **Quality**: `source_url` + `collector` + `fetched_at` on every document and shown on every receipt;
  retries with backoff; failed records reported, not dropped; graceful fallback to cached graph data.
- **Saves time**: hours of profile-stalking → the 3 people worth finding, with where/when to catch them.

## Track 3 — TrueForge with OpenAI (built on TrueForge · OpenAI heavy lifting · real problem · live)
- Two saved agents on **OpenAI `gpt-6-luna`**: `capy` (chat) and `capy-followup` (**8:00 daily schedule**).
- **MCP tools**: our `capy-graph` server + the Bright Data remote MCP (deferred tool discovery).
- **Human approval**: `send_intro` pauses with the exact message and Allow/Deny before anything reaches a person.
- **Sandbox / Code Mode**: Capy writes Python in a Daytona sandbox that calls the graph tools to build a clash-free day.
- **Skill**: `capy-intro` (receipt-grounded intro playbook) · Generative UI cards · subagents · clarifying questions.
- OpenAI also does every GraphRAG extraction, the embeddings and the evidence rerank.

---

## 90-second live demo (stage)
1. Open the TrueForge chat (left) and the Capy panel `localhost:8001/?side` (right).
2. *"Hi Capy! Code review can't keep up with all the AI-generated pull requests on my team. Who here already solved that?"*
   → point at the lit path + receipts (source + fetched-at).
3. *"Plan my Wednesday so I can catch them — use the sandbox."* → Code Mode itinerary.
4. *"I just bumped into Andy Kelly from Precisely — look him up fresh."* → live Bright Data fetch.
5. *"Remember I met Franck after his Home Assistant session…"* → New chat → *"Good morning Capy! Who am I following up with?"*
6. *"Draft a follow-up to Franck and send it."* → **Allow** → sent (demo outbox).

If the venue Wi-Fi fails, play the video.
