# Technical Decisions

This document covers the engineering decisions behind the Daily Briefing Tool — why things are built the way they are, what broke along the way, and what the tradeoffs look like in practice. For the product story, see [PRD.md](PRD.md). For setup and overview, see [README.md](README.md).

The system was built on Python 3.9.6 (macOS system Python), which imposed one recurring constraint: modern type hints like `list[str]` and `dict[str, str]` aren't natively supported at runtime. Every file needs `from __future__ import annotations` at the top to make these work (it defers type annotation evaluation). Dataclass field ordering also matters in Python 3.9 — fields with defaults must come after fields without, and getting this wrong produces a `TypeError` that doesn't obviously point to the field ordering issue. These are small things, but they caused several debugging sessions before becoming a standing project rule.

The project uses Click for CLI commands, SQLite for persistence, Gmail SMTP (Python's stdlib smtplib) for email delivery, the google.genai SDK for Gemini, the openai SDK for GPT-4o, youtube-transcript-api for transcripts, yt-dlp for video metadata, feedparser for RSS, and requests for HTTP. There are no web frameworks yet — the planned Phase 4 web UI would add FastAPI and Jinja2. Dependencies are pinned in requirements.txt.

---

## LLM Pipeline

The system uses a dual-provider architecture: Gemini 2.5 Flash as the primary model, OpenAI GPT-4o as the automatic fallback.

The interesting decision is the fallback behavior. When Gemini rate-limits mid-batch (which it does, more on that later), the system detects the failure, switches to OpenAI for the current item, and then *swaps the providers* — OpenAI becomes the primary for the rest of the batch. This avoids hammering a rate-limited provider repeatedly while still completing the run. The swap is in-memory only; the next session starts fresh with Gemini as primary.

The initialization is also graceful. On startup, the system tries to initialize both providers. If one fails (missing API key, bad credentials), it silently falls back to the other. If both fail, it raises an error. This means you can run the system with just a Gemini key or just an OpenAI key — the dual-provider setup is the ideal, not a requirement.

Both providers run at temperature 0.3. Low enough for consistency across summaries, high enough to avoid the robotic sameness you get at 0. The response format is enforced as JSON via Gemini's native `response_mime_type` parameter. OpenAI uses the same JSON constraint through its system prompt.

Context windows differ significantly: Gemini gets 900K usable tokens (out of a 1M window, with margin for the prompt template and output), while OpenAI gets 120K. Token estimation is rough — one token per four characters — but it only needs to be conservative, not precise. When a transcript exceeds the context window, the system calculates how much room remains after the prompt template, truncates just the transcript portion to fit, and rebuilds the prompt. Truncation happens at a sentence boundary (searching backward for ". "), so the LLM receives coherent input rather than a mid-sentence cutoff. The original transcript is preserved in memory and restored after prompt construction, so no data is lost.

In practice, the 900K token Gemini window means transcripts up to roughly 3.6 million characters fit without truncation. Only one source (Dwarkesh Patel, whose interviews regularly produce 40,000+ word transcripts) comes close to needing truncation.

Retry strategy varies by error type. Rate limits get escalating backoff: 30 seconds, then 60, then 90. JSON parse errors (which happen when Gemini wraps its response in markdown code blocks despite being told not to) get shorter exponential backoff at 1, 2, and 4 seconds. Server errors (5xx) get exponential backoff at 1, 2, and 4 seconds. The code also strips markdown fences before parsing, because Gemini does this about 5% of the time regardless of the JSON response format flag.

One migration note: the Gemini client was originally built on `google.generativeai` (the older Python SDK), which used a module-level `genai.configure()` call and a `GenerativeModel` class. In V7, this was migrated to `google.genai` (the current SDK), which uses an explicit `genai.Client()` constructor and `client.models.generate_content()`. The async variant for concurrent processing uses `client.aio.models.generate_content()`. The migration was necessary because the old SDK was deprecated, but the two SDKs have completely different initialization patterns and import paths — they're not backward-compatible. The migration touched every file that imported the Gemini module and required changing how configuration (API key, model selection) was passed.

The maximum output token limit is set to 4,096 for both providers. This is generous for the expected output (a JSON blob with a few paragraphs of text, 3-5 bullet points, and some metadata), but leaving headroom avoids truncated JSON responses that fail to parse. A truncated JSON response is worse than a slow one — it wastes the input tokens and produces no usable output.

---

## Prompt Engineering

Every processed summary records which prompt version produced it (currently v5.0). This matters because when you change the prompt, you need to know whether the new version is actually better. Storing the version per item means you can compare summaries from v4.0 and v5.0 side by side for the same source. Over 8 development sessions, the prompt went through 5 major versions — each one shaped by reading the output and finding specific patterns that needed fixing.

The voice is defined as "a sharp analyst who writes like Matt Levine or Ben Thompson — direct, specific, with an edge." This single line does more work than any other instruction in the prompt. Without it, every summary reads like a press release.

The prompt also includes two fully worked examples: a 19,000-word podcast transcript (deep dive) and a 725-word newsletter (summary sufficient). These aren't aspirational — they're the exact quality bar. LLMs respond much better to concrete examples than to abstract instructions. Telling an LLM "be concise" is vague. Showing it a 2-sentence summary of a 725-word article that ends with a specific stock ticker is concrete.

But voice alone doesn't prevent monotony when summaries are read back-to-back in a briefing. The prompt mandates rotation through 6 opener styles: lead with a number, a contrast, a bold claim, a quote, a one-word reaction, or a question. The same structure applies to the "so what" opinion boxes: direct imperative, market signal, contrarian take, investment angle, time-sensitive urgency, or strategic implication. The prompt explicitly lists all 12 styles with examples of each.

One pattern got explicitly banned: "If you're building X, you're doing it wrong." This showed up in roughly 40% of "so what" boxes before the ban. It's the LLM equivalent of a nervous tic — a safe, vaguely provocative structure that requires zero actual thinking. The ban doesn't just target that exact phrasing — it bans the entire "If you're..." / "If your..." conditional sentence structure in so_what fields. Cutting off the whole pattern family was necessary because the LLM would otherwise just rephrase it slightly.

Similarly, the prompt bans the opener pattern "[Subject] is [transforming/redefining/revolutionizing]..." — the single most common AI-generated opening line. The alternative isn't specified beyond the 6 rotation styles; forcing variety turns out to produce better results than prescribing replacements.

The biggest prompt change between v4.0 and v5.0 was replacing fixed domain categories with dynamic topic tags. Early versions tagged everything with buckets like "AI," "Finance," "Startups," and "Strategy." Every item got 2-3 of these, and they added zero information. The current prompt asks for specific, concrete tags — things like "vibe-coding," "GPU-capex," "MSFT," "churn-metrics." The prompt includes explicit good/bad examples to calibrate: "GOOD: vibe-coding, GPU-capex, MSFT. BAD: ai, strategy, startups, technology." These actually help during the morning scan because you can tell at a glance whether an item is about something you're currently thinking about.

The LLM's JSON response includes a `content_type` field with 7 valid values (market call, news analysis, industry trend, framework, tutorial, interview, commentary) and a `freshness` field (fresh, evergreen, stale). Both are validated during parsing — invalid values get mapped to sensible defaults (commentary and fresh, respectively) rather than failing the entire item. This defensive parsing matters because LLMs occasionally return creative interpretations like "deep_analysis" or "timely" that aren't in the valid set. The same defensive approach applies to topic tags (normalized to lowercase, capped at 3, with a "general" fallback), key insights (coerced to a list if the LLM returns a string), and concept explanations (skipped silently if malformed). The goal is: never fail an item due to a parse error if the core summary is present.

---

## Blacklist Enforcement

LLMs ignore prompt-level instructions about 20% of the time. Tell them never to write "game-changer" and one in five summaries will include it anyway.

The fix is a two-layer system. Layer one is the prompt itself: explicit instructions listing 12 banned phrases and structural patterns (like never starting a summary with "[Subject] is [verb]ing"). Layer two is post-processing: a regex-based find-and-replace that runs on every text field of the LLM's output before it gets saved to the database. The regex is case-insensitive, so "Game-Changer," "GAME-CHANGER," and "game-changer" all get caught. The post-processing runs on summaries, insights, so_what boxes, concept explanations, and tier rationales — every text field the LLM generates.

The replacements are specific. "Game-changer" becomes "significant shift." "The landscape" becomes "the market." "Leveraging AI" becomes "using AI." Some phrases just get removed entirely — "the message is clear" and "in today's rapidly" add nothing and get deleted. Removal leaves artifacts: double spaces and orphaned punctuation like "; ;" or ", ,". The cleanup logic collapses multiple spaces and normalizes orphaned punctuation in a second pass.

The same layer also catches known entity misspellings. LLMs consistently misspell "Anthropic" as "Enthropic" or "Antrhropic." These get corrected automatically.

Adding a new banned phrase means updating two places: the replacement dictionary (for post-processing) and the prompt text (for first-line-of-defense). This redundancy is intentional. The prompt catches it 80% of the time, the regex catches the rest. Combined: 100% enforcement rate.

The current blacklist has 12 entries, curated from reviewing early batches of LLM output. The goal isn't to ban all AI-sounding language — that would be an arms race. It's to catch the specific phrases that are both recognizably LLM-generated and content-free. "Game-changer" says nothing. "Significant shift" at least implies a specific direction. "The landscape of AI" is pure filler. "The market" at least refers to something concrete. Each replacement was chosen to carry at least some informational content, or to simply remove the phrase and let the surrounding context stand on its own.

---

## Tier Calibration

The tier system has three levels: deep dive (summary captures less than 50% of the value — go watch the original), worth a look (summary captures 60-80%), and summary sufficient (summary captures 90%+ — you've got the gist).

The problem: LLMs are conflict-averse. Ask them to assign tiers and they'll rate almost everything "worth a look." It's the four-star restaurant review problem — everything is good, nothing is great, nothing is bad.

The solution is a calibration layer that overrides the LLM's tier assignment based on objective content signals:

- 18,000+ words automatically becomes a deep dive, regardless of what the LLM said. That's a 3-hour interview. The summary cannot possibly capture it.
- 12,000+ words from a known deep source (Dwarkesh Patel, Lenny's Podcast, Stratechery) automatically becomes a deep dive. These sources have consistently high insight density.
- 12,000+ words flagged as an interview type, or with 5+ key insights extracted, also promotes to deep dive.
- Under 1,500 words automatically demotes to summary sufficient. At that length, the summary *is* the content.
- Stale content rated deep dive gets demoted to worth a look. A great interview from six weeks ago isn't worth the same urgency as today's news.

Greg Isenberg is intentionally excluded from the "deep source" list despite having long-form content. His videos are tutorials and walkthroughs — the summary captures the key frameworks without needing the original. This is a product judgment, not a quality judgment. Tutorials lose less in summarization than interviews, where the back-and-forth, the tangents, and the guest's specific phrasing often contain the real value.

The calibration layer validates the LLM's tier against the content type too. A 12,000-word piece flagged as an "interview" promotes to deep dive automatically — interviews at that length involve substantive back-and-forth that summaries flatten. But a 12,000-word "tutorial" from a non-deep source would need either 5+ extracted insights or 18,000+ words to auto-promote. The bar is higher for content types where the structure is more linear and the summary captures more.

When calibration overrides the LLM's tier, the reason is appended to the tier rationale field (e.g., "[Calibrated: 22,400-word interview]"). This makes debugging easy — you can always see whether a tier was the LLM's judgment or a signal-based override.

The resulting distribution across 868 processed items: 257 deep dive (30%), 501 worth a look (58%), 110 summary sufficient (12%). Without calibration, worth a look would be closer to 80%. The 30% deep dive rate is arguably too high for daily briefings (where only 3 deep dives make the cut per email), but it's appropriate for the full corpus — it means roughly a third of all content from these 8 sources genuinely rewards consuming the original.

One subtlety: calibration only promotes or demotes — it never invents a tier from scratch. The LLM always makes the initial call, and calibration overrides it based on signals the LLM might not weigh correctly (word count thresholds, source reputation). This preserves the LLM's judgment for content where the signals are ambiguous (e.g., a 10,000-word post from a source not in the deep source list).

---

## Content Discovery

YouTube video discovery uses three strategies, tried in priority order.

Strategy one is the YouTube Data API v3. Given an API key, it resolves a channel handle (like @DwarkeshPatel) to a canonical channel ID, derives the uploads playlist ID by swapping the UC prefix to UU, then paginates through the playlist to collect every video. It batch-fetches durations 50 at a time to filter out Shorts before any transcript work happens. The quota cost is modest: about 9 API units for 200 videos, against a daily free quota of 10,000 units.

Strategy two is the YouTube RSS feed, which returns roughly the 15 most recent videos. Fast and reliable, but useless for backfilling history.

Strategy three is page scraping — parsing the `ytInitialData` JSON blob from the channel page. This gets about 30 videos and is fragile. YouTube changes this structure without warning.

The API path is strongly preferred. For the initial backfill of 905 items across 7 YouTube channels going back to January 2025, the API was the only practical option. RSS would have found about 105 videos (15 per channel). Scraping would have found about 210 (30 per channel). The API returned the full upload history.

Sources are defined in a YAML configuration file: each entry has an ID, name, URL, type (youtube or rss), a `fetch_since` date, and optional category filters. Adding a new source is a YAML edit and a fetch command — no code changes needed. The fetcher factory reads the source type and returns the appropriate fetcher class.

Channel ID resolution has its own fallback chain: try the `forHandle` API parameter first, then `forUsername`, and if both fail, the system can derive the uploads playlist from a known channel ID by swapping the UC prefix to UU (YouTube's convention: UC = user channel, UU = user uploads). This matters because YouTube's handle system is inconsistent — some channels have @handles, some have /c/ custom URLs, some have /user/ legacy URLs, and the API treats each format differently. The resolution logic is called once per channel and the result is used for all subsequent playlist pagination.

**The Shorts problem.** YouTube Shorts are videos under about 60 seconds. They waste transcript API calls (the transcripts are trivially short) and always fail the 500-word minimum content threshold during processing. Before adding filters, 23 out of 80 fetched items from one source were Shorts — nearly 30% waste.

The fix uses three layers. First, the API returns video durations via a batch call (50 IDs per request to the videos.list endpoint), and anything under 120 seconds gets filtered at fetch time. Second, URLs containing `/shorts/` are filtered before any API calls — this catches Shorts even before duration data is available. Third, for the scraping fallback path where the API isn't used, yt-dlp enriches missing durations by querying video metadata without downloading the actual video. A second filter pass then catches anything under 120 seconds that the URL pattern missed.

No single layer catches everything. The API duration path only works when a YouTube API key is configured. The URL pattern misses some Shorts that use standard `/watch?v=` URLs. The yt-dlp enrichment is slow (one HTTP request per video) and only runs on the scraping fallback path. Together, the three layers are comprehensive.

yt-dlp is used as a Python library, not as a CLI tool. This is a deliberate choice — calling it as a subprocess would require it to be installed system-wide and on the PATH, which is fragile. Importing it as a library means it's managed by pip like any other dependency. The extraction uses `download=False` to fetch only metadata, making it fast (a few hundred milliseconds per video rather than minutes for a full download).

**RSS fetching** handles Stratechery (the one non-YouTube source) with WordPress pagination using `?paged=N` and a 1.0-second delay between page fetches. Category filtering restricts Stratechery to "Articles" only, skipping paid Daily Updates that would just hit the paywall detector downstream. Content extraction from RSS entries follows a priority chain: prefer `content[text/html]` (full article body), fall back to `summary`, then `description`, and as a last resort fetch the full page via HTTP. This matters because RSS feeds are inconsistent about how much content they include.

Paywall detection itself looks for 2+ paywall signature patterns in content that's under 1,000 words — short content with paywall markers means the full article is locked. The detector runs at two stages: once during fetching (to flag items early) and once during processing (to catch stubs that slipped through the first pass, for example if the RSS feed included a longer excerpt but the processing input was truncated). Running detection twice with the same logic is cheap — it's a few regex matches — and catches cases where content looks different at different pipeline stages. Of 906 total items, 7 were flagged as paywalled, all from Stratechery's paid tier.

---

## Transcript Fetching and Rate Limiting

The youtube-transcript-api library was rewritten between v0.x and v1.x with a completely different API. The old pattern (a static class method call) doesn't work anymore. The new API requires instantiating a client, calling `.list()` to discover available transcripts, finding a generated English transcript, calling `.fetch()` on it, and then extracting text from `.snippets`. This broke the initial implementation and took a session to debug.

Transcript preference follows a priority chain: manually created English transcripts first (higher quality), then auto-generated English transcripts, then a direct fetch as a last resort (which grabs whatever the default is). After fetching, the raw transcript gets cleaned: multiple spaces collapsed, `[Music]` and `[Applause]` annotations stripped, newlines removed. The result is a single continuous text block suitable for LLM processing.

Content below 500 words after transcript extraction gets skipped entirely. This threshold catches YouTube Shorts that slipped through the duration filter, teaser clips, and videos where the transcript is mostly non-verbal annotations. Of 906 total items, 31 were skipped at this threshold.

The harder lesson was about rate limiting. YouTube doesn't document transcript rate limits, and the API doesn't return explicit rate-limit errors. Instead, when you fetch too many transcripts too quickly, later requests silently return empty results. The item gets saved with a null transcript and a "pending" status, processing skips it (no transcript = nothing to summarize), and you don't notice the failure until you check completion rates and find 844 items with no transcripts.

The fix was a mandatory 2.0-second delay between transcript fetches, baked into the base fetcher class. This is slow — 844 transcripts at 2 seconds each takes about 28 minutes — but it's reliable. Zero failures across the full recovery run.

Recovery required a separate CLI command (`retry-transcripts`) that re-fetches transcripts for items that failed. This had its own bug: the initial query only matched items with `status = 'no_transcript'`, but the bulk discovery command (run with a `--no-transcripts` flag for fast initial discovery) saved items as `status = 'pending'` with null transcripts. Same symptom — no transcript — but a different status value. The recovery command found 0 items. The fix was a compound SQL query matching both `status = 'no_transcript'` and `status = 'pending' AND transcript IS NULL`. A small change, but it blocked the entire 844-item backlog recovery until it was diagnosed.

The broader lesson: any bulk operation hitting an external API needs configurable throttling with conservative defaults. YouTube, Gemini, and OpenAI all rate-limit in ways that don't match their documentation. The default should always be "slower than you think you need." This principle is codified as a project rule: every new API integration must have a configurable delay parameter with a conservative default (2-3 seconds between calls, 60 seconds between source batches).

---

## Concurrent Processing

With 868 items pending and sequential processing at a 5-second delay taking 3+ hours, the backlog needed a concurrent solution.

The architecture uses asyncio with per-provider semaphores. Gemini and OpenAI each have their own concurrency limit, enforced by separate semaphores. Items are pre-partitioned between providers (default: 70% Gemini, 30% OpenAI) and shuffled before processing to distribute load evenly across time rather than sending all Gemini requests first.

The critical design choice: all database writes go through a single asyncio Queue with one consumer coroutine. SQLite doesn't handle concurrent writes well — you'll get "database is locked" errors under load. The solution is to let API calls run in parallel (they're I/O-bound anyway) but funnel all writes through a single serialized consumer. Each completed API response gets placed on the queue as a tuple of (item, result, provider_name), and the consumer processes them one at a time: parse the response, enforce the blacklist, calibrate the tier, save to DB, update status. The consumer reuses the same parsing logic as the sequential processor to avoid divergent behavior.

A progress reporter prints stats every 10 seconds — processed count, failure count, items per minute. This was added after the first run appeared to hang (see the stdout buffering issue below).

The first run used 20 Gemini concurrent and 10 OpenAI concurrent — based on what the documentation implied was safe. It was not safe. Gemini started throwing 429 errors on the tail end of batches. OpenAI was worse — 3 concurrent sustained requests triggered rate limits.

Four runs were needed to clear the backlog:

| Run | Config | Result |
|-----|--------|--------|
| 1 | 20 Gemini / 10 OpenAI | ~759 processed, many 429s on tail. Killed. |
| 2 | OpenAI only, 15 concurrent | ~27 processed, aggressive 429s. Killed. |
| 3 | 5 Gemini / 3 OpenAI | 77 processed, 5 OpenAI failures. Clean. |
| 4 | 5 Gemini only (remainder) | 5 processed, 0 failures. Clean. |

The initial time estimate was 3-5 minutes. Actual time: about 30 minutes. Off by 6-10x, entirely because of rate limiting.

The safe concurrency limits that emerged from testing: 5 concurrent for Gemini (with GCP credits), 3 concurrent for OpenAI. Gemini at 5 concurrent processed 659 items with zero failures. OpenAI at 3 concurrent still had occasional 429s but completed 209 items. For future bulk operations, the recommendation is to route 90%+ to Gemini.

For perspective: Gemini's documentation claims 2,000 requests per minute. OpenAI's documentation implies generous limits for paid tiers. In practice, 5 concurrent Gemini requests with ~10 second processing times means roughly 30 RPM — 1.5% of the documented limit — and that's the safe ceiling. Trust empirical limits, not documentation.

The processing script is designed for one-time backlog clearing, not daily use. For the daily workflow (typically 10-20 new items), the sequential `process --all --delay 5` command is simpler and reliable. The concurrent script exists because the initial backlog of 868 items made sequential processing impractical — 868 items at 5 seconds each would take over 72 minutes just in delay time, plus API processing time.

One debugging detour: the first processing run appeared to hang. Output stopped appearing after the initial setup log. The script was actually processing items normally — the issue was Python's stdout buffering in non-interactive mode. When running as a background task or piping output, Python switches from line-buffered to fully-buffered stdout. Print statements don't appear until the 8KB buffer fills or the process exits. The fix: set the `PYTHONUNBUFFERED` environment variable, or add `flush=True` to every print call. This is a known Python behavior, but it's deeply confusing when you're watching a terminal that shows nothing for 5 minutes while 200 API calls complete silently in the background.

The Gemini async client uses native async support via `client.aio.models.generate_content()` — not a thread pool wrapper around synchronous calls. OpenAI similarly provides `AsyncOpenAI` as a first-class async client. Both have identical retry logic to their synchronous counterparts (escalating backoff for rate limits, exponential backoff for parse errors).

---

## Briefing Composition

The composition algorithm selects roughly 15 items per briefing (18 hard cap) from the pool of undelivered processed content. Several constraints shape the selection.

**Source diversity** caps each source at 2 items per briefing, with an exception allowing a 3rd if it's rated deep dive. Without this, 20VC (which publishes daily) would take 4-5 slots every briefing. The cap forces variety and surfaces less frequent but high-quality sources like Dwarkesh Patel (who publishes every few weeks but whose interviews are consistently among the deepest in the pool). The overflow items aren't discarded — they stay in the undelivered pool and surface in future briefings.

**Deep dive ceiling** limits deep dives to 3 per briefing. The rationale: when everything is flagged as special, nothing feels special. When more than 3 deep dives qualify, the excess get demoted to worth a look, keeping the ones with the highest word count (a proxy for depth).

This cap had a critical bug. The demotion happened in memory — the code changed the tier attribute on the Python object — but the downstream email generation re-read items from the database, where the tier was still "deep_dive." The fix was to persist tier changes to the database at the same time as the in-memory mutation. A one-line addition, but the bug was invisible until a briefing shipped with 5 deep dives instead of 3.

**Backlog clearing** uses adaptive allocation. The system checks how many fresh items (published within 6 weeks, not yet delivered) are available, then allocates backlog slots inversely: light day (0-3 fresh items) gets 8 backlog slots, heavy day (10+ fresh) gets 2. Backlog items are filtered to evergreen content only — stale news doesn't get a second chance. Over time, the backlog steadily clears without making any single briefing feel like a homework assignment.

**Display ordering** groups items by tier, then interleaves sources within each tier using round-robin. Within each tier, fresh items sort before backlog items. Then the round-robin distributes sources: sort source queues by item count (most items first for fair distribution), pop one item from each queue per round, repeat until all queues are empty. The result is that even if 20VC has 2 items in the worth-a-look tier, they appear separated by items from other sources rather than stacked together.

One operational constraint: a briefing can only be composed once per date (unique constraint on the date column). Recomposing requires deleting the existing briefing record first. This is intentional — it prevents accidentally re-sending a briefing and double-marking items as delivered. The delivered flag on processed items is set at send time, not compose time, so a composed-but-unsent briefing can be safely discarded.

---

## Email Design

The subject line is optimized for Outlook mobile, which shows roughly 75 characters in preview. The format is `"Feb 12: [title] (+N more)"`, where the prefix takes about 9 characters and the suffix about 12, leaving 54 characters for the lead title. Titles longer than 54 characters get truncated at a word boundary — the code searches backward for the last space before the limit to avoid mid-word cuts, with a floor of 20 characters to prevent overly aggressive truncation. Titles from RSS and YouTube feeds often contain HTML entities (like `&amp;`), so all titles are unescaped before rendering.

Read time is estimated as: number of items times 15 seconds (scanning overhead per item) plus total summary words divided by 200 words per minute. The minimum is clamped to 3 minutes. This is intentionally conservative — it's better to over-estimate than to set an expectation the reader can't meet.

The editorial intro is a separate LLM call that takes the day's item titles and summaries (first 150 characters each) and synthesizes a 1-2 sentence connecting thread. The prompt for this is explicit: "Don't say 'today covers a range of AI topics.' Say what the pattern IS." The intro is wrapped in a try/except so that if the LLM call fails (rate limit, timeout, bad response), the briefing still sends without it. A missing editorial intro is invisible to the reader; a failed send is not. This pattern — make optional enhancements non-fatal — applies broadly in the pipeline.

The email is built as inline-styled HTML (no CSS classes, no external stylesheets) because most email clients strip `<style>` blocks. Every visual element is styled with inline `style` attributes. The layout uses a single-column design capped at 600px width, which renders correctly on both desktop and mobile Outlook without responsive breakpoints.

The email renders three card styles by tier. Deep dives get a 3-sentence summary, 3 key insights, a "so what" opinion box (blue background, left border), and a Watch/Read link with duration. Worth a look gets the same structure with a 2-sentence summary. Summary sufficient gets 2 sentences and an inline take — no link, no insight bullets — because the summary *is* the value, and a link would imply the original is worth the time. The link text adapts to content type: "Watch (42m)" for videos with known duration, "Watch" for videos without duration data, "Read" for articles.

The email footer includes a backlog progress bar (rendered as nested divs with percentage-width backgrounds — the only reliable way to do progress bars in HTML email) and cumulative stats.

Email delivery went through two iterations. The original implementation used the Resend API, which had a sandbox limitation that cost debugging time: in sandbox mode, emails only arrive at the account owner's email address, regardless of what you set as the recipient. The API call succeeds and returns an ID, but the email never arrives. There's no error, no bounce — the send looks perfectly successful. Production Resend requires domain verification (no individual email verification like AWS SES), which was too heavy for a personal tool. The final implementation uses Gmail SMTP with App Passwords — Python's stdlib smtplib, no external dependency, multi-recipient support out of the box. The tradeoff: Gmail has sending limits (~500/day), but for a daily briefing to 3 recipients, that's irrelevant.

Every sent briefing also gets saved as a standalone HTML file in the data directory, named by date. This serves as a local archive and a debugging tool — you can open any past briefing in a browser to see exactly what was sent, without needing to find the email.

---

## Data Model

Content deduplication uses a hash of source ID plus URL, truncated to 16 characters. This means the same URL fetched twice from the same source produces the same content ID and hits the unique constraint, preventing duplicates across fetch runs. The hash includes the source ID (not just the URL) so that if two different sources reference the same video, both entries are kept — they may have different editorial contexts.

The schema has five tables. `content_items` holds raw fetched content with a URL unique constraint. `processed_content` holds LLM summaries with a foreign key to content_items. `daily_briefings` holds briefing records with a unique constraint on the date. `feedback` is ready for Phase 4 (web UI) but unused. `backlog_progress` is a single-row table (enforced by an id=1 constraint) that tracks cumulative backlog delivery stats.

The database column for tags is named `domains` but holds dynamic topic tags (since v5.0). The column name wasn't renamed because it would require a migration and every query that references it, and the semantic change is documented. The column stores a JSON array of strings like `["vibe-coding", "GPU-capex", "MSFT"]`. This is a pragmatic tradeoff: renaming the column would be cleaner, but the migration risk wasn't worth it for a single-user tool where the column meaning is clear from the data.

Backlog tracking uses a threshold of 14 days: content older than two weeks at processing time is classified as backlog. This flag is computed once and stored as a boolean on the processed content record, so it doesn't shift over time — an item that was fresh when processed stays marked as fresh even if it ages past the threshold. This matters for the briefing composition algorithm, which treats fresh and backlog items differently: fresh items get priority slots, while backlog items fill remaining capacity and must be evergreen (not stale) to qualify.

Every processed item stores its prompt version and the model that produced it. This enables two things: comparing summary quality across prompt iterations, and debugging why a particular summary reads differently (was it Gemini or OpenAI? was it v4.0 or v5.0?). Across the full corpus, 659 items were processed by Gemini and 209 by OpenAI — a natural experiment in model comparison, though no systematic quality analysis has been done yet.

The content status field acts as a state machine: `pending` (fetched, awaiting processing), `processed` (summary complete), `no_transcript` (transcript fetch failed), `skipped` (below 500-word minimum), `paywall` (paywall detected), and `failed` (LLM processing error). Each status implies a different recovery path: `no_transcript` items can be retried with `retry-transcripts`, `failed` items can be reprocessed by resetting to `pending`, while `skipped` and `paywall` items are terminal.

The database is SQLite, chosen because there's exactly one user and no concurrent writes during normal operation (the concurrent processing script serializes writes through a queue). SQLite's simplicity — a single file, no server process, zero configuration — is worth the tradeoff of no concurrent write support. If this were a multi-user product, PostgreSQL would be the obvious choice. For a personal tool, SQLite means the entire application state is a single 3MB file that you can copy, back up, or query with any SQLite client.

The CLI uses the Click framework and follows a consistent pattern: every command initializes a Database instance, performs its operation, and reports results with explicit counts. The "explicit failure surfacing" philosophy applies here too — if a fetch finds 50 items but 12 fail transcript extraction, it doesn't just report "50 items fetched." It reports "50 fetched, 38 with transcripts, 12 failed" and suggests the recovery command. Silent partial failures were a recurring problem in early versions that this approach was designed to eliminate.

---

## Closing

The system processes 912 content items through a four-stage pipeline — fetch, process, compose, send — and delivers a daily email. It was built over 10 sessions using Claude Code by a product manager. The architecture is straightforward: SQLite for state, two LLM providers with fallback, a composition algorithm with hard constraints, and HTML email as the only interface.

The pattern that kept recurring across every layer: the documented behavior of external services (YouTube, Gemini, OpenAI) doesn't match the actual behavior under load. Rate limits are lower than stated. APIs fail silently instead of returning errors. Sandbox modes have undocumented delivery restrictions. Libraries ship breaking API changes between minor versions.

The engineering response was the same every time: conservative defaults, explicit failure surfacing, and always having a recovery path. The 2-second transcript delay is slow but reliable. The 5-concurrent Gemini limit leaves headroom. The blacklist has two layers because one isn't enough. The editorial intro is non-fatal because optional features shouldn't take down required ones.

The development process itself shaped the architecture. This project was built over 10 sessions using Claude Code, each session picking up from a handover document that captured what was done, what broke, and what to do next. The iterative nature — build, test against real data, find the failure, fix it, repeat — is why so many layers have fallback behavior. The three-layer Shorts filter exists because each layer was added after discovering a gap in the previous one. The dual-layer blacklist exists because the first layer alone had a 20% miss rate. The compound SQL query for transcript recovery exists because the original query missed a status value. Every layer of defense started as a bug report.

The system works not because nothing goes wrong, but because every failure mode has been hit at least once and handled.
