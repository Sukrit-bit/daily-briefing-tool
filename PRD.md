# Daily Briefing Tool — Product Design Document

## The Problem

I'm a former Director of Product, now building an AI startup. I follow 8 high-signal sources across AI, startups, strategy, and finance. The problem is simple and brutal: Dwarkesh Patel drops a 3-hour interview with a compute researcher. Lenny's Podcast publishes an hour-long conversation with a four-time founder. Ben Thompson writes 3,000 words on chip supply chains. 20VC puts out a new episode *every day*. BG2 Pod covers $285B market cap crashes in real-time.

I trust all of these sources. I can't consume any of them fast enough. I had a 6-month backlog and 5 minutes each morning.

The real problem isn't information overload — it's the inability to triage. I don't need to read everything. I need to know *which things I can skip* and *which things I can't*.

## The Core Insight

Most content summarization tools treat everything equally. "Here's a summary." But a summary of a 3-hour Dwarkesh Patel interview with 40,000 words of transcript captures maybe 30% of the value. A summary of a 5-minute AI news clip captures 95%. Treating these the same is a product design failure.

The system needed a **tier system** that answers one question: *"How much of the original value does my summary actually capture?"*

| Tier | What it means | What I do |
|------|--------------|-----------|
| **Deep Dive** | Summary captures <50%. The original has depth, nuance, and structure you'd miss. | Block 20 minutes and watch/read the original. |
| **Worth a Look** | Summary captures 60-80%. Solid content, well-summarized. | Skim the insights. Maybe click through if a tag catches my eye. |
| **Summary Sufficient** | Summary captures 90%+. You've got the gist. | Read the two-sentence summary and move on. |

This single decision — tiers instead of scores — shaped the entire product.

## Key Decisions and Why

### "Don't trust the LLM's tier assignment"

LLMs are conflict-averse. Ask them to tier content and they'll rate almost everything "worth a look." It's the equivalent of a restaurant where every review is 4 stars.

So I built a **calibration layer** that overrides the LLM based on objective signals:

- **18,000+ words?** That's a 3-hour interview. Auto-promote to deep dive, regardless of what the LLM said.
- **12,000+ words from Dwarkesh, Lenny's, or Stratechery?** These sources have consistently high density. Auto-promote.
- **Under 1,500 words?** The summary *is* the content. Auto-demote to summary sufficient.
- **Stale content rated deep dive?** Demote. A great interview from 6 weeks ago isn't worth prioritizing over today's news.

This hybrid approach — LLM judgment plus signal-based overrides — produces a tier distribution that actually feels right: ~30% deep dive, ~58% worth a look, ~12% summary sufficient.

### "LLMs will sound like LLMs unless you fight it"

The first version of the summaries was unusable. Every other sentence was "a game-changer in the landscape of AI." The insights all started with "This highlights the importance of..."

I addressed this at three levels:

**Voice definition.** The prompt specifies a persona: sharp analyst, Matt Levine / Ben Thompson style. Opinionated, occasionally funny. Avoids corporate-speak.

**Variety enforcement.** The prompt mandates 6 different opener styles (lead with a number, a contrast, a bold claim, a quote, a one-word reaction, a question) and 6 different "so what" styles (imperative, market signal, contrarian take, investment angle, time-sensitive, strategic implication). This breaks the monotony.

**Blacklist enforcement.** LLMs ignore prompt-level bans about 20% of the time. So every summary goes through a post-processing regex layer that catches and replaces 12 banned phrases. "Game-changer" becomes something specific. "The landscape" becomes something concrete. Two layers, zero tolerance.

### "Fixed categories are useless. Dynamic tags are useful."

Early versions tagged everything with generic buckets: "AI," "Finance," "Startups," "Strategy." Every item got 2-3 of these. They added zero information.

I switched to dynamic topic tags: the LLM generates specific, concrete tags per item. A briefing now shows tags like "vibe-coding," "GPU-capex," "MSFT," "churn-metrics," "founder-mode." I can scan the headline index and know in one glance which items are relevant to what I'm thinking about today.

### "A prolific source shouldn't monopolize the briefing"

20VC publishes daily. Without constraints, it would take 4-5 slots in every briefing. The composition algorithm enforces source diversity: max 2 items per source, with an exception for a 3rd if it's rated deep dive. This forces variety and surfaces content from less frequent but high-quality sources like Dwarkesh Patel or BG2 Pod.

### "The backlog should clear itself"

With 900+ items to process and only 15 per briefing, the system needed a strategy for the backlog. The answer: **dynamic allocation** based on how much fresh content arrives each day.

- Light day (0-3 fresh items): pull 8 from backlog
- Normal day (4-6 fresh): pull 5 from backlog
- Heavy day (7-9 fresh): pull 3 from backlog
- Very heavy day (10+ fresh): pull 2 from backlog

Backlog items are filtered to evergreen content only — stale news doesn't get a second chance. Over weeks, the backlog steadily clears without ever making the daily briefing feel like homework.

## The Email

The briefing email is the product's only interface. It needs to work in a 5-10 minute morning scan.

**Subject line:** `Feb 12: Marc Andreessen: The real AI boom hasn't... (+11 more)` — Optimized for Outlook mobile's ~75 character preview. Leads with the most important item.

**Layer 1 — Headline Index (30-second scan).** A compact table: tier emoji, title (truncated to 70 chars), source, length, relative date, and topic tag pills. I scan this over coffee and already know what kind of day it is. Between the index and the detail cards: an editorial intro — a 1-2 sentence LLM-generated synthesis of the day's themes.

**Layer 2 — Detail Cards (5-minute read).** Each tier renders differently. Deep dives get a 3-sentence summary, 3 key insights, a "so what" opinion box, and a Watch/Read link with duration. Summary sufficient items get two sentences and an inline take — no link, because the summary *is* the value.

## Architecture

The system is a four-stage pipeline:

```
fetch → process → compose → send-briefing
```

**Fetch.** YouTube Data API v3 discovers videos (full channel history, not just recent RSS). Transcripts are extracted via youtube-transcript-api. RSS feeds are parsed with feedparser. yt-dlp provides video duration metadata. YouTube Shorts (<2 min) are filtered at three layers: URL pattern, API duration, post-enrichment. Everything goes into SQLite.

**Process.** Each item goes through: prompt construction (v5.0) → LLM call → JSON response parsing → blacklist enforcement → tier calibration. Gemini 2.5 Flash is primary (1M token context window). OpenAI GPT-4o is the automatic fallback — when Gemini rate-limits, the system detects it, switches providers mid-batch, and keeps going.

**Compose.** Selects ~15 items (18 hard cap) from the undelivered pool. Applies source diversity caps, deep dive ceiling (max 3 per briefing), priority ordering, and source interleaving within tiers to prevent back-to-back items from the same source.

**Send.** Generates an editorial intro (separate LLM call), renders a two-layer HTML email, sends via Resend, marks items as delivered, saves an HTML backup.

### Bulk Processing

The initial backlog was 868 items. Processing sequentially with `--delay 5` would take over an hour. So I built a concurrent processing script using asyncio with dual-provider support:

- Splits items between Gemini (70%) and OpenAI (30%)
- Configurable concurrency (default: 5 Gemini, 3 OpenAI)
- Single asyncio.Queue consumer for thread-safe database writes

What I learned about API rate limits in practice:
- Gemini at 5 concurrent: 0 failures. At 20 concurrent: frequent 429s.
- OpenAI at 3 concurrent: still sees occasional 429s. Their limits are stricter than documented.
- 868 items took ~30 minutes at conservative concurrency. My initial estimate was 3-5 minutes. I was off by 6-10x.

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Transcript unavailable | Marked and skipped. `retry-transcripts` CLI command recovers later. |
| Paywall content | Detected via content pattern matching. Excluded from processing. |
| Content too short (<500 words) | Marked `skipped`. Also caught by Shorts filter at fetch time. |
| LLM rate limit mid-batch | Exponential backoff (30/60/90s). Auto-fallback to secondary provider. |
| LLM returns banned phrases | Dual-layer enforcement catches 100% post-processing. |
| LLM over-promotes tier | Signal-based calibration overrides based on word count + source. |
| Bulk transcript fetch throttled | 2s delay between fetches. Without this, later sources silently fail. |
| Transcript exceeds context window | Truncated at sentence boundary with "[Content truncated]" marker. |

## What I Built vs. What I'd Build Next

**Shipped (Phases 1-3):** Content fetching (YouTube API + RSS), LLM processing pipeline with dual-provider fallback, tier-based briefing composition, HTML email delivery. 906 items fetched, 868 processed, daily briefings running.

**Next — Web UI (Phase 4):** A local web interface for browsing past briefings, searching across all processed content, and flagging bad summaries. This creates a feedback loop for prompt engineering.

**Next — Automation (Phase 5):** macOS launchd scheduler so the pipeline runs every morning without me touching the terminal. Wake-from-sleep handling included.

**If I were building this as a product for others:** The composition algorithm (source diversity, tier calibration, backlog clearing) generalizes well. The prompt engineering around LLM voice and variety enforcement is transferable. The sources would need to be user-configurable with an onboarding flow. The email template works on mobile but would benefit from a web-based reading experience.

## How It Was Built

This entire project was built using [Claude Code](https://claude.ai/claude-code) over 8 sessions. I'm a product manager — the product thinking, system design, prompt engineering, and editorial voice are mine. Claude wrote the code.

The collaboration pattern: I'd define what I wanted (a tier system, a blacklist, a source diversity cap), explain the product rationale, and Claude would implement it. When something didn't work — LLM summaries sounding generic, backlog items not surfacing, YouTube Shorts wasting API calls — I'd describe the problem and we'd fix it together.

Eight sessions, zero prior Python experience on my part, fully functional daily email running in production.
