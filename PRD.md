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

The full prompt is the most iterated artifact in the project — five major versions across ten sessions. See [PROMPT.md](PROMPT.md).

### "Fixed categories are useless. Dynamic tags are useful."

Early versions tagged everything with generic buckets: "AI," "Finance," "Startups," "Strategy." Every item got 2-3 of these. They added zero information.

I switched to dynamic topic tags: the LLM generates specific, concrete tags per item. A briefing now shows tags like "vibe-coding," "GPU-capex," "MSFT," "churn-metrics," "founder-mode." I can scan the headline index and know in one glance which items are relevant to what I'm thinking about today.

### "A prolific source shouldn't monopolize the briefing"

20VC publishes daily. Without constraints, it would take 4-5 slots in every briefing. The composition algorithm enforces source diversity: max 2 items per source, with an exception for a 3rd if it's rated deep dive. This forces variety and surfaces content from less frequent but high-quality sources like Dwarkesh Patel or BG2 Pod.

### "The backlog should clear itself"

With 912 items to process and only 15 per briefing, the system needed a strategy for the backlog. The answer: **dynamic allocation** based on how much fresh content arrives each day.

- Light day (0-3 fresh items): pull 8 from backlog
- Normal day (4-6 fresh): pull 5 from backlog
- Heavy day (7-9 fresh): pull 3 from backlog
- Very heavy day (10+ fresh): pull 2 from backlog

Backlog items are filtered to evergreen content only — stale news doesn't get a second chance. Over weeks, the backlog steadily clears without ever making the daily briefing feel like homework.

### "If I have to remember to run it, I won't"

The system runs four commands in sequence: fetch, process, compose, send. In the manual workflow, that's a terminal, a virtual environment, and 2 minutes of waiting. It's fine on a Saturday. It doesn't survive a Monday.

The whole point of this tool is saving time. Requiring me to spend 2 minutes to save 30 defeats the purpose. So the pipeline runs automatically every morning at 7 AM, even if my laptop is off. If a step fails, the next step still runs with whatever succeeded — a partial briefing is better than no briefing.

The product insight: **automation isn't a nice-to-have feature that ships later. It's the difference between a tool you built and a tool you use.** Every content summarizer I've tried required me to go somewhere and do something. The ones I stopped using are the ones that required a habit change. This one requires nothing. The email arrives. I read it or I don't.

## The Email

The email is the entire product. There's no app, no dashboard, no feed to check. If the email doesn't work in a 5-10 minute morning scan, nothing works.

This constraint shaped every design decision.

**Subject line:** `Feb 12: Marc Andreessen: The real AI boom hasn't... (+11 more)` — The subject is optimized for Outlook mobile's ~75 character preview. It leads with the most important item, not a generic "Daily Briefing" header. The goal: give me enough context to decide whether to open it *now* or after my first meeting.

**Why two layers?** Because scanning and reading are different activities with different time budgets. Some mornings I have 30 seconds. Some mornings I have 10 minutes. A single-layer design forces me to choose between "skim everything" and "read everything." Two layers let me do the 30-second scan every morning and the 5-minute read when I have time.

**Layer 1 — Headline Index (30-second scan).** Tier emoji, title, source, length, relative date, topic tag pills. No summaries, no insights — just enough to answer "what kind of day is it?" Between the index and the detail cards: an editorial intro that synthesizes the day's themes into 1-2 sentences. This exists because 15 individual items don't tell you what's *happening* — the editorial intro connects them.

**Layer 2 — Detail Cards (5-minute read).** Each tier renders with a different information density — and this is a deliberate product decision, not just formatting. Deep dives get the full treatment: 3-sentence summary, 3 key insights, an opinionated "so what" box, and a Watch/Read link. Summary sufficient items get two sentences and an inline take — *no link*. Omitting the link is the design choice that matters most. Including a link would imply "there's more value in the original." For summary sufficient items, there isn't. The summary *is* the value. The missing link is the product saying: "You're done. Move on."

**Why not a web UI?** Email is the only interface that survives the "I haven't opened a new tab yet" test. It's already in my morning flow. There's no app to install, no habit to build, no URL to remember. The tradeoff is obvious — no search, no bookmarking, no feedback mechanism. But for a morning triage tool, reach beats richness.

## Architecture

Four stages, each with a distinct job:

```
fetch → process → compose → send
```

**Fetch** answers: *"What's new?"* It discovers every video and article from my 8 sources — going back to January 2025, not just the recent feed — and extracts the full text. Short clips and YouTube Shorts are filtered out before anything else touches them. The system knows I care about substance, not volume.

**Process** answers: *"What does this mean for me?"* Each item gets summarized, tagged, tiered, and checked for LLM slop. If one AI provider is down, the system silently switches to the other and keeps going. The reader never sees a gap.

**Compose** answers: *"What's worth my time today?"* It selects ~15 items from the undelivered pool, enforcing the rules described above — source diversity, deep dive ceiling, backlog mixing, and source interleaving so I never see three items from the same creator back-to-back. This is where the curation value lives.

**Send** answers: *"How do I get it without thinking about it?"* It generates the editorial intro, builds the email, delivers it to all recipients, and saves a backup. The full pipeline runs automatically every morning — I haven't touched the terminal in weeks.

For the engineering decisions behind each stage — rate limit strategies, concurrent processing, transcript recovery, edge case handling — see [TECHNICAL.md](TECHNICAL.md).

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Transcript unavailable | Marked and skipped. Automatically recovered on a later run. |
| Paywall content | Detected via content pattern matching. Excluded from processing. |
| Content too short (<500 words) | Skipped. Also caught by the Shorts filter at fetch time. |
| LLM rate limit mid-batch | Automatic retry with backoff. Falls back to secondary provider if the primary stays down. |
| LLM returns banned phrases | Dual-layer enforcement: prompt-level ban + post-processing regex. 100% catch rate. |
| LLM over-promotes tier | Signal-based calibration overrides based on word count and source reputation. |
| Bulk transcript fetch throttled | Throttled automatically. Without pacing, later sources silently fail. |
| Transcript exceeds context window | Truncated at sentence boundary so the LLM still gets coherent input. |

## What I Built vs. What I'd Build Next

**Shipped (Phases 1-3, 5):** Content fetching (YouTube API + RSS), LLM processing pipeline with dual-provider fallback, tier-based briefing composition, HTML email delivery to multiple recipients, and fully automated daily scheduling with cloud and local fallback options. 912 items fetched, 874 processed, daily briefings running hands-free every morning.

**Next — Web UI (Phase 4):** A local web interface for browsing past briefings, searching across all processed content, and flagging bad summaries. This creates a feedback loop for prompt engineering.

### If This Were a Product for Others

The composition algorithm — source diversity, tier calibration, dynamic backlog clearing — generalizes well beyond my 8 sources. The prompt engineering around LLM voice control and variety enforcement is transferable to any summarization product.

What would change: sources would need to be user-configurable with an onboarding flow ("paste a YouTube channel or RSS feed"). The email template works on mobile but would need a web-based reading experience for search, bookmarking, and feedback. And the tier calibration rules would need to learn from user behavior — if someone consistently clicks through "summary sufficient" items from a particular source, maybe that source deserves a higher tier baseline.

The interesting product question is whether the *curation layer* (what makes the cut, how it's ordered, how it's presented) matters more than the *summarization layer* (how well each summary reads). My bet after building this: curation is 70% of the value.

## How It Was Built

This project was built using [Claude Code](https://claude.ai/claude-code) over 10 sessions. I'm a product manager — the product thinking, system design, prompt engineering, and editorial voice are mine. Claude wrote the code.

The collaboration pattern was always the same: I'd describe a product problem ("the summaries all sound the same"), explain what good looked like ("Matt Levine doesn't start every paragraph the same way"), and Claude would implement the solution. When the solution didn't work — which happened constantly — I'd describe what was wrong with the *output*, not the code, and we'd iterate.

**What V1 looked like vs. V10:**

Session 1 produced a working pipeline that fetched 10 videos and summarized them. The summaries were generic. Every one started with "[Person] discusses the importance of..." The tier assignments were useless — everything was "worth a look." There was no blacklist, no calibration, no source diversity. The email was a wall of text.

By session 5, the summaries had voice. The blacklist caught LLM slop. Tier calibration actually differentiated content. But the system could only handle 15 videos at a time because of rate limits, and the email looked bad on mobile.

By session 8, the full backlog of 868 items was processed. Concurrent dual-provider processing cleared it in 30 minutes. The email was a two-layer design with topic tag pills and editorial intros. But I still had to run 4 commands in a terminal every morning.

Session 10 made it disappear. Gmail SMTP replaced the sandbox email provider. A scheduler runs the pipeline at 7 AM. The briefing arrives without me doing anything. The tool went from "something I built" to "something I use."

**The biggest wrong assumption:** I thought the hard problem would be summarization quality. It wasn't. The hard problem was *curation* — deciding what makes the cut, how it's ordered, and how it's presented. A mediocre summary of the right 15 items beats a perfect summary of the wrong 15. I spent more time on the composition algorithm (source diversity, tier caps, backlog mixing, display ordering) than on the prompt engineering. That's the part that makes the morning email feel curated instead of generated.

**What building with AI actually looks like:** It's not "describe the app and it appears." It's 10 sessions of describing problems, reading output, finding what's wrong, and describing the problem again. The advantage isn't speed — it's scope. A product manager building alone can't write a concurrent async processing pipeline, a multi-provider LLM integration with fallback, and an inline-styled HTML email renderer. With Claude Code, I could describe what each of those needed to *do*, and focus entirely on whether the output was right. The iteration loop was: product judgment in, code out, test against real data, repeat.

Ten sessions. Fully automated daily email in production.
