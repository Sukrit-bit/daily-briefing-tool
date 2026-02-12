# Daily Briefing Tool — Product Requirements Document

**Version:** 2.0 (updated to reflect what was built)
**Created:** February 2025

---

## 1. Problem

I'm drowning in valuable content across AI, startups, strategy, and finance. Eight sources I trust publish daily. Some drop 3-hour interviews. Some drop 700-word newsletters. I have 6-12 months of backlog and maybe 5 minutes each morning to figure out what matters.

I need a system that:
1. Fetches everything automatically from my 8 sources
2. Reads it all for me (transcripts, articles, the lot)
3. Decides what's worth my time and what isn't
4. Delivers a daily briefing I can scan in 5 minutes and deep-dive when I choose
5. Clears my backlog over 2-3 months without overwhelming me

## 2. Solution

A CLI pipeline that fetches content, processes it through LLMs, composes tier-based daily briefings, and delivers them via email.

```
fetch → process → compose → send-briefing
  │         │          │          │
  │         │          │          └── HTML email via Resend + LLM editorial intro
  │         │          └── Source diversity, deep dive caps, priority ordering
  │         └── LLM summarization → blacklist enforcement → tier calibration
  └── YouTube Data API v3 / RSS → transcripts → SQLite
```

No web framework. No hosted infra. Just a local Python CLI, a SQLite database, and two LLM providers.

---

## 3. Key Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Primary LLM | Gemini 2.5 Flash (`google.genai` SDK) | 1M token context, good quality, GCP credits available |
| Fallback LLM | OpenAI GPT-4o | Automatic failover when Gemini rate-limits |
| Transcripts | youtube-transcript-api | Free, no API quota, sufficient quality |
| Video discovery | YouTube Data API v3 | Full channel history (RSS only returns ~15 recent videos) |
| Email | Resend | Free tier (3K/month), simple API, real inbox delivery |
| Database | SQLite | No server, no config, local-first |
| Configuration | YAML sources + hardcoded constants | Simple. Not over-engineered for one user. |
| Content mix | 50-70% fresh / 30-50% backlog | Dynamic: light days pull more backlog |
| Daily volume | 15 target, 18 hard cap | Overflow defers to next day |
| Shorts filter | <2 min videos excluded | 3-layer filter: URL pattern, API duration, post-enrichment |

---

## 4. Sources

Eight curated sources, all fetching since January 2025:

| Source | Type | Focus | Cadence |
|--------|------|-------|---------|
| Nate B Jones | YouTube | AI news & strategy | Daily, shorter |
| Greg Isenberg | YouTube | Startup ideas, building in public | 2-3x/week |
| Y Combinator | YouTube | Startup advice, founder interviews | Irregular |
| Dwarkesh Patel | YouTube | Deep technical interviews | Long-form (1-3h) |
| Lenny's Podcast | YouTube | Product, startups, strategy | 1-2x/week |
| 20VC (Harry Stebbings) | YouTube | VC/founder interviews | Daily, 30-60m |
| BG2 Pod | YouTube | Finance, AI, strategy | Weekly, 1-2h |
| Stratechery | RSS | Strategy, tech analysis | 2-3x/week (free articles only) |

Sources are defined in `config/sources.yaml`. Adding a new one is a YAML edit + a `fetch` command.

---

## 5. Architecture

### Data Flow

1. **Fetch** — YouTube Data API v3 discovers videos (full channel history), youtube-transcript-api extracts transcripts, feedparser handles RSS. yt-dlp provides duration metadata as a fallback. Items are stored in SQLite as `ContentItem` with status `pending`.

2. **Process** — Each item goes through: prompt construction (v5.0) → LLM call (Gemini, OpenAI fallback) → JSON response parsing → blacklist enforcement → tier calibration → save as `ProcessedContent`.

3. **Compose** — The composer selects items from the undelivered pool: fresh content first, then backlog (evergreen only). Applies source diversity caps (max 2-3 per source), deep dive ceiling (max 3), priority ordering (deep dive → worth a look → summary sufficient), source interleaving within tiers.

4. **Send** — Generates an editorial intro (separate LLM call), composes a two-layer HTML email, sends via Resend, marks items as delivered, saves HTML backup to `data/`.

### LLM Processing Pipeline

```
ContentItem
    │
    ├── Skip if: no transcript, paywall detected, <500 words
    │
    ▼
build_summarization_prompt()  ← Prompt v5.0 with voice, blacklist, variety rules
    │
    ▼
LLMClient.generate()  ← Gemini primary, auto-fallback to OpenAI
    │
    ▼
_parse_response()  ← Extract JSON, validate fields
    │
    ▼
_enforce_blacklist()  ← Regex replacement of 12 banned phrases + entity corrections
    │
    ▼
_calibrate_tier()  ← Signal-based overrides (word count, source, content type)
    │
    ▼
ProcessedContent → SQLite
```

### Tier Calibration

LLMs tend to default everything to `worth_a_look`. The calibration layer applies signal-based overrides:

| Rule | Trigger | Action |
|------|---------|--------|
| Long-form auto-promote | 18K+ words | → deep_dive regardless of source |
| Deep source promote | 12K+ words from Dwarkesh/Lenny's/Stratechery | → deep_dive |
| Interview promote | 12K+ words + interview type | → deep_dive |
| Insight density promote | 12K+ words + 5+ insights | → deep_dive |
| Short content demote | 1,500 words or less | → summary_sufficient |
| Stale content demote | Stale + deep_dive | → worth_a_look |

### Blacklist Enforcement

LLMs ignore prompt-level blacklists about 20% of the time. The system uses two layers:

- **Layer 1 (prompt):** Instructions in the prompt text tell the LLM to avoid specific phrases
- **Layer 2 (post-processing):** `_enforce_blacklist()` uses case-insensitive regex to catch and replace anything that slips through

Currently banned: "game-changer", "non-negotiable", "the message is clear", "leveraging AI", "paradigm shift", "the landscape", and 6 others.

---

## 6. Prompt Design (v5.0)

The prompt defines a specific voice: sharp analyst, Matt Levine / Ben Thompson style, opinionated, occasionally funny, never sounds like a press release.

**Structural constraints:**
- `core_summary`: 2-3 sentences maximum. Lead with the most surprising claim.
- `key_insights`: 3-5 bullets, each one sentence, max 25 words.
- `concepts_explained`: Only genuinely novel terms. Max 3, with analogies.
- `so_what`: 1-2 sentences. Specific and opinionated.
- `topic_tags`: 2-3 dynamic tags. Concrete (e.g., "vibe-coding", "GPU-capex", "MSFT"), not generic ("ai", "strategy").

**Variety enforcement:**
The prompt mandates 6 different opener styles (number, contrast, bold claim, quote, one-word reaction, question) and 6 different so_what styles (imperative, market signal, contrarian take, investment angle, time-sensitive, strategic implication). This prevents the monotonous "X is transforming Y" pattern that makes LLM-generated content immediately recognizable.

**JSON response format:**
```json
{
  "core_summary": "...",
  "key_insights": ["...", "..."],
  "concepts_explained": [{"term": "...", "explanation": "..."}],
  "so_what": "...",
  "topic_tags": ["vibe-coding", "solo-builders", "AI-tools"],
  "content_type": "interview",
  "freshness": "fresh",
  "tier": "deep_dive",
  "tier_rationale": "..."
}
```

---

## 7. Data Models

### ContentItem (raw fetched content)

```
id                 Hash of source_id + url (unique)
source_id          e.g., "dwarkesh-patel"
source_name        e.g., "Dwarkesh Patel"
content_type       "video" | "article"
title, url         From source
published_at       Publication datetime
fetched_at         When we fetched it
duration_seconds   Video length (nullable)
transcript         Full text content (nullable)
word_count         For filtering and calibration
status             "pending" | "processed" | "failed" | "skipped" | "no_transcript" | "paywall"
```

### ProcessedContent (after LLM)

```
content_id         FK to ContentItem
core_summary       2-3 sentence summary
key_insights       JSON array of bullet strings
concepts_explained JSON array of {term, explanation}
so_what            Opinionated take
domains            JSON array of topic tags (dynamic, not fixed categories)
content_category   market_call | news_analysis | industry_trend | framework | tutorial | interview | commentary
freshness          fresh | evergreen | stale
tier               deep_dive | worth_a_look | summary_sufficient
tier_rationale     Why this tier (includes calibration notes)
processed_at       Timestamp
prompt_version     "v5.0"
model_used         "gemini-2.5-flash" or "gpt-4o"
source_id          For diversity enforcement
is_backlog         True if >14 days old at processing time
delivered          Whether included in a sent briefing
delivered_at       When delivered (nullable)
```

### DailyBriefing

```
id                 Hash of "briefing:{date}"
briefing_date      Unique per day
created_at         Timestamp
fresh_count        Count of fresh items
backlog_count      Count of backlog items
total_count        Total items in this briefing
item_ids           Ordered list of content_ids
email_sent         Boolean
email_sent_at      Timestamp (nullable)
```

---

## 8. Email Design

The email is optimized for a 5-10 minute morning scan on mobile. Two layers:

### Subject Line
```
Feb 10: Claude's Computer Use Just Changed... (+11 more)
```
Optimized for Outlook mobile (~75 char preview). Leads with the top item title, truncated at word boundaries.

### Layer 1 — Headline Index (30-second scan)

A compact table with one row per item:
- Tier emoji (red/yellow/green circle)
- Title (truncated to 70 chars)
- Source, length, relative date
- Topic tag pills (small gray chips)
- Backlog badge if applicable

Between the headline index and detail cards: an **editorial intro** — a 1-2 sentence LLM-generated synthesis of the day's themes. Styled with an indigo left border.

### Layer 2 — Detail Cards (5-minute read)

Three tiers render differently:

**Deep Dive (red accent):**
- 3-sentence summary
- Top 3 key insights (bullet list)
- So-what box (blue background, specific opinion)
- "Watch (42m) →" or "Read →" link

**Worth a Look (default):**
- 2-sentence summary
- Top 3 key insights
- So-what box
- Watch/Read link

**Summary Sufficient (compact):**
- 2-sentence summary
- Inline "Take:" (italic, no box)
- No link (the summary IS the value)

### Footer
- Backlog progress bar with percentage
- Cumulative stats
- "Built by Sukrit with Claude"

---

## 9. Composition Algorithm

```python
# Step 1: Get fresh content (not yet delivered, <6 weeks old, not stale)
fresh_pool = get_undelivered_fresh(max_age_weeks=6)

# Step 2: Dynamic backlog allocation
if fresh_count <= 3:   backlog_target = 8   # Light day
elif fresh_count <= 6: backlog_target = 5   # Normal day
elif fresh_count <= 9: backlog_target = 3   # Heavy day
else:                  backlog_target = 2   # Very heavy day

# Step 3: Get backlog (evergreen only, priority-ordered)
backlog_pool = get_undelivered_backlog(limit=backlog_target)

# Step 4: Combine → source diversity → deep dive cap → total cap
all_items = fresh + backlog
all_items = enforce_source_diversity(all_items)   # Max 2 per source (3 if deep_dive)
all_items = cap_deep_dives(all_items)             # Max 3, demote excess to worth_a_look
all_items = prioritize_and_cap(all_items, 18)     # Hard cap

# Step 5: Order for display
# Group by tier → interleave sources within tier → fresh before backlog
ordered = order_for_display(all_items)
```

Key behaviors:
- Source diversity caps prevent any single source from dominating
- Deep dive cap demotions are persisted to the database (not just in-memory)
- Overflow items stay undelivered and surface in future briefings
- Source interleaving ensures the same source never appears back-to-back

---

## 10. Bulk Processing

For large backlogs, the sequential CLI (`process --all --delay 5`) is too slow. The `scripts/concurrent_process.py` script provides async dual-provider processing:

- Splits items between Gemini (70%) and OpenAI (30%) by default
- Uses asyncio with configurable concurrency (default: 5 Gemini, 3 OpenAI)
- Single asyncio.Queue consumer for thread-safe DB writes
- Reuses the Summarizer's `_parse_response()` for consistent post-processing

Real-world concurrency limits (learned the hard way):
- Gemini with GCP credits: 5 concurrent requests = 0 failures. 20 = frequent 429s.
- OpenAI: 3 concurrent = occasional 429s. Their tier limits are stricter than documented.
- 868 items took ~30 minutes at conservative concurrency, not the estimated 3-5 minutes.

---

## 11. Edge Cases

| Scenario | Handling |
|----------|----------|
| YouTube transcript unavailable | Mark `no_transcript`, skip processing. `retry-transcripts` CLI command recovers later. |
| Paywall content (Stratechery) | Detected via content pattern matching. Marked `paywall`, excluded. |
| Content too short (<500 words) | Marked `skipped`. Shorts filter also catches <2min videos at fetch time. |
| LLM rate limit | Exponential backoff (30s, 60s, 90s). Auto-fallback to secondary provider. |
| LLM returns banned phrases | Dual-layer enforcement: prompt instructions + regex post-processing. |
| LLM over-promotes to deep_dive | Signal-based calibration demotes based on word count and source. |
| Same-day recompose | Returns existing briefing. Delete from DB to recompose. |
| YouTube bulk transcript fetch | 2s delay between fetches. Without throttling, later sources silently fail. |
| Very long transcript (>context window) | Truncated at sentence boundary, tagged with "[Content truncated]". |
| Mac sleep during scheduled run | launchd runs job when Mac wakes (Phase 5, not yet implemented). |

---

## 12. File Structure

```
daily-briefing-tool/
├── config/
│   └── sources.yaml              # 8 content sources (YAML)
├── src/
│   ├── cli.py                    # All CLI commands (Click)
│   ├── fetchers/
│   │   ├── base.py               # Abstract fetcher with throttled fetch_all()
│   │   ├── youtube.py            # YouTube Data API v3 + transcript extraction + yt-dlp
│   │   └── rss.py                # RSS parsing + paywall detection + paginated historical fetch
│   ├── processors/
│   │   ├── prompts.py            # Prompt v5.0, BLACKLISTED_PHRASES, ENTITY_CORRECTIONS
│   │   ├── summarizer.py         # Orchestrator: process → parse → blacklist → calibrate → save
│   │   ├── llm_client.py         # Multi-provider wrapper with auto-fallback
│   │   ├── gemini_client.py      # Gemini 2.5 Flash via google.genai SDK
│   │   └── openai_client.py      # GPT-4o wrapper
│   ├── briefing/
│   │   ├── composer.py           # Selection, diversity caps, deep dive ceiling, ordering
│   │   └── emailer.py            # Two-layer HTML email + Resend delivery
│   └── storage/
│       ├── database.py           # All SQLite operations
│       └── models.py             # ContentItem, ProcessedContent, DailyBriefing, etc.
├── scripts/
│   ├── full_fetch.py             # Sequential historical fetch across all sources
│   └── concurrent_process.py     # Async dual-provider bulk LLM processing
├── data/                         # SQLite DB + HTML backups (gitignored)
├── .env.example                  # API key template
└── requirements.txt
```

---

## 13. Project Status

| Phase | Status | What it includes |
|-------|--------|------------------|
| 1 — Fetching | **Complete** | YouTube Data API v3, RSS, transcripts, yt-dlp durations, Shorts filter |
| 2 — LLM Processing | **Complete** | Gemini + OpenAI, prompt v5.0, blacklist, tier calibration, concurrent bulk |
| 3 — Briefing + Email | **Complete** | Composition algorithm, two-layer HTML email, editorial intro, Resend delivery |
| 4 — Web UI | Not started | FastAPI + Jinja2 templates planned at `src/web/` |
| 5 — Automation | Not started | macOS launchd scheduler for daily runs |
