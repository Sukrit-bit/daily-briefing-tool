# Daily Briefing Tool — Product Requirements Document

**Version:** 1.0  
**Created:** February 2025  
**Author:** Built with Claude
**Execution Mode:** Claude Code (Mac App)

---

## 1. Context & Problem Statement

### The Problem
The target user is drowning in valuable content across Finance, Startups, Strategy, and AI domains. There's too much to keep up with, and 6-12 months of backlog has accumulated. They need a system that:
1. Surfaces the most relevant content daily
2. Helps him catch up on the backlog systematically
3. Translates technical concepts into accessible insights
4. Respects his time constraints (5 min email scan + 30-60 min deep dive)

### The Solution
A daily briefing system that:
- Fetches content from 8 curated sources (YouTube + blogs)
- Processes via LLM to summarize, tag, and prioritize
- Delivers a morning email briefing (8 AM)
- Provides a web UI for deeper exploration
- Intelligently mixes fresh content with relevant backlog
- Clears the backlog within 2-3 months

---

## 2. Key Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **LLM** | Gemini 3 Flash | Quality matters; ~$5/month is acceptable |
| **Transcripts** | youtube-transcript-api | Free, sufficient quality, no API quota |
| **Email** | Resend | Free tier (3K/month), simple API, real inbox delivery |
| **Database** | SQLite | Simple, no server, local-first |
| **Web Framework** | FastAPI | Lightweight, good for APIs |
| **Hosting** | Local (Mac) | Run via launchd scheduler; deploy later |
| **Content Mix** | 50-70% fresh / 30-50% backlog | Intelligent mixing based on daily volume |
| **Backlog Cutoff** | January 2025 | Don't go further back |
| **Daily Volume** | Soft cap at 18 items | Overflow defers to next day |
| **Backlog Priority** | 🔴 → 🟡 → 🟢 | Best content surfaces first |
| **Domains** | Finance, Startups, Strategy, AI | Config-driven; easy to add more |
| **Stratechery** | Free articles only | Paywalled content excluded for now |

---

## 3. Sources (Initial)

```yaml
sources:
  - id: nate-b-jones
    name: "Nate B Jones (AI News & Strategy Daily)"
    type: youtube_channel
    channel_url: "https://www.youtube.com/@NateBJones"
    fetch_since: "2025-01-01"
    
  - id: greg-isenberg
    name: "Greg Isenberg"
    type: youtube_channel
    channel_url: "https://www.youtube.com/@GregIsenberg"
    fetch_since: "2025-01-01"
    
  - id: y-combinator
    name: "Y Combinator"
    type: youtube_channel
    channel_url: "https://www.youtube.com/@ycombinator"
    fetch_since: "2025-01-01"
    
  - id: dwarkesh-patel
    name: "Dwarkesh Patel"
    type: youtube_channel
    channel_url: "https://www.youtube.com/@DwarkeshPatel"
    fetch_since: "2025-01-01"
    
  - id: lennys-podcast
    name: "Lenny's Podcast"
    type: youtube_channel
    channel_url: "https://www.youtube.com/@LennysPodcast"
    fetch_since: "2025-01-01"
    
  - id: 20vc
    name: "20VC with Harry Stebbings"
    type: youtube_channel
    channel_url: "https://www.youtube.com/@20VC"
    fetch_since: "2025-01-01"
    
  - id: bg2-pod
    name: "BG2 Pod"
    type: youtube_channel
    channel_url: "https://www.youtube.com/@Bg2Pod"
    fetch_since: "2025-01-01"
    
  - id: stratechery
    name: "Stratechery (Ben Thompson)"
    type: rss
    feed_url: "https://stratechery.com/feed/"
    fetch_since: "2025-01-01"
    notes: "Free articles only; paywalled content excluded"
```

---

## 4. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        DAILY BRIEFING TOOL                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │   FETCHERS   │───▶│  PROCESSOR   │───▶│   STORAGE    │       │
│  │              │    │   (Gemini)   │    │   (SQLite)   │       │
│  │ • YouTube    │    │              │    │              │       │
│  │ • RSS        │    │ • Summarize  │    │ • Content    │       │
│  │ • (Twitter)  │    │ • Tag        │    │ • Summaries  │       │
│  └──────────────┘    │ • Score      │    │ • Flags      │       │
│                      └──────────────┘    └──────────────┘       │
│                                                 │                │
│                      ┌──────────────────────────┴───────┐       │
│                      │                                  │       │
│               ┌──────▼──────┐                  ┌────────▼────┐  │
│               │   EMAILER   │                  │   WEB UI    │  │
│               │  (Resend)   │                  │  (FastAPI)  │  │
│               │             │                  │             │  │
│               │ 8 AM Daily  │                  │ localhost   │  │
│               └─────────────┘                  └─────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Fetch** (runs daily, ~7 AM): Pull new content from all sources
2. **Process**: Send to Gemini 3 Flash for summarization + tagging
3. **Store**: Save processed content to SQLite
4. **Compose**: Select items for today's briefing (fresh + backlog)
5. **Email**: Generate HTML email, send via Resend at 8 AM
6. **Serve**: FastAPI serves web UI for deep exploration

---

## 5. File Structure

```
daily-briefing-tool/
├── README.md                    # Project overview
├── docs/                        # Documentation
├── PRD.md                       # This document
│
├── config/
│   ├── sources.yaml             # Source definitions
│   ├── domains.yaml             # Domain definitions
│   └── settings.yaml            # App settings (email time, caps, etc.)
│
├── src/
│   ├── __init__.py
│   │
│   ├── fetchers/                # Content fetchers
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract base fetcher
│   │   ├── youtube.py           # YouTube channel fetcher
│   │   ├── rss.py               # RSS feed fetcher
│   │   └── twitter.py           # (Future) Twitter fetcher
│   │
│   ├── processors/              # LLM processing
│   │   ├── __init__.py
│   │   ├── summarizer.py        # Main summarization logic
│   │   ├── prompts.py           # All prompts (versioned)
│   │   └── gemini_client.py     # Gemini API wrapper
│   │
│   ├── storage/                 # Database layer
│   │   ├── __init__.py
│   │   ├── database.py          # SQLite connection + queries
│   │   └── models.py            # Data models (dataclasses)
│   │
│   ├── briefing/                # Briefing composition
│   │   ├── __init__.py
│   │   ├── composer.py          # Select items for daily briefing
│   │   └── emailer.py           # Generate + send email
│   │
│   ├── web/                     # Web UI
│   │   ├── __init__.py
│   │   ├── app.py               # FastAPI application
│   │   ├── routes.py            # API routes
│   │   └── templates/           # HTML templates (Jinja2)
│   │       ├── base.html
│   │       ├── briefing.html
│   │       └── components/
│   │
│   └── cli.py                   # Command-line interface
│
├── scripts/
│   ├── run_daily.py             # Main daily job script
│   ├── backfill.py              # Initial backlog fetch
│   └── test_summary.py          # Test summarization quality
│
├── data/
│   └── briefing.db              # SQLite database (gitignored)
│
├── tests/
│   └── ...
│
├── requirements.txt
├── .env.example                 # Environment variables template
└── .gitignore
```

---

## 6. Data Models

### ContentItem (raw fetched content)

```python
@dataclass
class ContentItem:
    id: str                      # Unique ID (hash of source + url)
    source_id: str               # e.g., "dwarkesh-patel"
    source_name: str             # e.g., "Dwarkesh Patel"
    content_type: str            # "video" | "article"
    title: str
    url: str
    published_at: datetime
    fetched_at: datetime
    duration_seconds: int | None # For videos
    transcript: str | None       # Full transcript/article text
    word_count: int
    status: str                  # "pending" | "processed" | "failed" | "skipped"
```

### ProcessedContent (after LLM processing)

```python
@dataclass
class ProcessedContent:
    content_id: str              # FK to ContentItem
    
    # Summary components
    core_summary: str            # 3-5 sentences
    key_insights: list[str]      # Bullet points
    concepts_explained: list[dict]  # [{term, explanation}]
    so_what: str                 # Implications for reader
    
    # Classification
    domains: list[str]           # ["finance", "ai", "startups"]
    content_type: str            # "market_call" | "news_analysis" | "framework" | "tutorial" | etc.
    freshness: str               # "fresh" | "evergreen" | "stale"
    
    # Recommendation
    tier: str                    # "deep_dive" | "worth_a_look" | "summary_sufficient"
    tier_rationale: str          # Why this tier
    
    # Metadata
    processed_at: datetime
    prompt_version: str          # e.g., "v1.0"
    model_used: str              # e.g., "gemini-3-flash"
    
    # Backlog tracking
    is_backlog: bool             # True if from historical fetch
    delivered: bool              # True if included in a briefing
    delivered_at: datetime | None
```

### DailyBriefing

```python
@dataclass
class DailyBriefing:
    id: str
    date: date
    created_at: datetime
    
    # Content breakdown
    fresh_count: int
    backlog_count: int
    total_count: int
    
    # Items (ordered)
    items: list[str]             # List of content_ids in display order
    
    # Delivery
    email_sent: bool
    email_sent_at: datetime | None
```

### Feedback

```python
@dataclass
class Feedback:
    id: str
    content_id: str
    flagged_at: datetime
    reason: str                  # "too_shallow" | "missed_point" | "technical_unclear" | "wrong_tier" | "other"
    note: str | None             # Optional free-text
    original_summary: str        # Snapshot of summary at flag time
    prompt_version: str
```

### BacklogProgress

```python
@dataclass
class BacklogProgress:
    total_items: int             # Fixed on day 1
    delivered_items: int         # Increments as backlog surfaces
    percent_complete: float
    estimated_completion: date
    last_updated: datetime
```

---

## 7. Prompts

### Prompt v1.0: Main Summarization

```markdown
You are summarizing content for a reader with this profile:

**Reader Profile:**
- Former Director of Product, now building an AI startup
- Strong business/product background, NOT a technical engineer
- Deep interest in: Finance (stock investing), Startups (building companies), Strategy (business thinking), AI (staying current)
- Wants to understand implications and build knowledge, not just consume news
- Technical concepts must be explained with analogies and plain language

**Domains (tag all that apply):**
- finance: Stock investing, markets, macro, valuation
- startups: Building companies, fundraising, product, growth
- strategy: Business strategy, competitive dynamics, moats
- ai: AI technology, capabilities, implications, trends

**Content Types (choose one):**
- market_call: Specific trade/investment recommendation (short shelf life)
- news_analysis: Reaction to recent event (weeks shelf life)
- industry_trend: Broader trend analysis (months shelf life)
- framework: Mental model or way of thinking (evergreen)
- tutorial: How-to or educational content (evergreen)
- interview: Conversation with insights throughout (varies)
- commentary: Opinion or analysis (varies)

**Freshness Assessment:**
Given the publication date and content type, assess:
- fresh: Still highly relevant, worth reading now
- evergreen: Timeless content, always relevant
- stale: Time-sensitive content that's no longer actionable

**Your Task:**

Analyze this content and provide:

1. **CORE_SUMMARY** (3-5 sentences)
   What is this about? What's the main thesis or argument?

2. **KEY_INSIGHTS** (3-7 bullet points)
   The non-obvious takeaways. What would be lost if someone skipped this?

3. **CONCEPTS_EXPLAINED** (if technical content exists)
   Any technical terms or concepts, explained accessibly with analogies.
   Format: 
   - Term: [technical term]
     Explanation: [plain language explanation with analogy if helpful]
   
   Example:
   - Term: Inference compute
     Explanation: The cost of running an AI model after it's trained. Think of training as building a car, and inference as the fuel cost to drive it. Even if the car is built, you pay every time you drive.

4. **SO_WHAT** (2-3 sentences)
   Why does this matter for someone thinking about:
   - Investing decisions?
   - Building startups?
   - Understanding where AI/tech is going?

5. **RECOMMENDATION**
   Choose one:
   - deep_dive: This content is dense, unique, and worth consuming in full. The summary captures maybe 50% of the value.
   - worth_a_look: The summary captures most insights, but the original adds color/depth. Good for a skim.
   - summary_sufficient: The summary captures 90%+ of the value. Original is long, padded, or redundant.
   
   Provide a one-sentence rationale for your choice.

**Content Details:**
- Title: {title}
- Source: {source_name}
- Published: {published_date}
- Length: {duration_or_word_count}
- Type: {video_or_article}

**Content:**
{transcript_or_text}

---

Respond in this exact JSON format:
```json
{
  "core_summary": "...",
  "key_insights": ["...", "..."],
  "concepts_explained": [
    {"term": "...", "explanation": "..."}
  ],
  "so_what": "...",
  "domains": ["finance", "ai"],
  "content_type": "framework",
  "freshness": "evergreen",
  "tier": "deep_dive",
  "tier_rationale": "..."
}
```
```

---

## 8. Briefing Composition Logic

### Daily Selection Algorithm

```python
def compose_daily_briefing(date: date) -> DailyBriefing:
    """
    Compose the daily briefing with intelligent mixing of fresh and backlog content.
    
    Target: 12-18 items total
    Mix: 50-70% fresh, 30-50% backlog
    """
    
    # 1. Get all fresh content (not yet delivered, published in last 6 weeks, not stale)
    fresh_pool = get_fresh_content(
        max_age_weeks=6,
        freshness__in=["fresh", "evergreen"],
        delivered=False
    )
    
    # 2. Determine fresh count and backlog allocation
    fresh_count = len(fresh_pool)
    
    if fresh_count <= 3:
        backlog_target = 8      # Light day: heavy backlog
    elif fresh_count <= 6:
        backlog_target = 5      # Normal day
    elif fresh_count <= 9:
        backlog_target = 3      # Heavy day
    else:
        backlog_target = 2      # Very heavy day: minimum backlog
    
    # 3. Get backlog items (priority-first: deep_dive → worth_a_look → summary_sufficient)
    backlog_pool = get_backlog_content(
        delivered=False,
        freshness__in=["evergreen"],  # Only evergreen from backlog
        order_by=["tier_priority", "published_at"]  # Best first
    )[:backlog_target]
    
    # 4. Combine and enforce cap
    all_items = fresh_pool + backlog_pool
    
    if len(all_items) > 18:
        # Keep all deep_dive, then worth_a_look, then summary_sufficient
        all_items = prioritize_and_cap(all_items, cap=18)
        # Overflow items remain in pool for tomorrow
    
    # 5. Order for display
    # deep_dive first, then worth_a_look, then summary_sufficient
    # Within each tier, fresh before backlog
    ordered_items = order_for_display(all_items)
    
    # 6. Mark as delivered
    for item in ordered_items:
        mark_delivered(item.content_id, date)
    
    return DailyBriefing(
        date=date,
        items=[item.content_id for item in ordered_items],
        fresh_count=len([i for i in ordered_items if not i.is_backlog]),
        backlog_count=len([i for i in ordered_items if i.is_backlog]),
        total_count=len(ordered_items)
    )
```

### Tier Priority Mapping

```python
TIER_PRIORITY = {
    "deep_dive": 1,        # 🔴
    "worth_a_look": 2,     # 🟡
    "summary_sufficient": 3 # 🟢
}
```

---

## 9. Email Template Structure

### Subject Line
```
Your Daily Briefing — {date} | {count} items | {deep_dive_count} deep dives
```

### Email Body Structure

```html
<!-- Header -->
<h1>Daily Briefing</h1>
<p>{date} · {total_count} items · {fresh_count} fresh, {backlog_count} from backlog</p>

<!-- Quick Stats -->
<div class="stats">
  <span>🔴 {deep_dive_count} Deep Dives</span>
  <span>🟡 {worth_a_look_count} Worth a Look</span>
  <span>🟢 {summary_sufficient_count} Summaries</span>
</div>

<hr>

<!-- Deep Dives Section -->
<h2>🔴 Deep Dive</h2>
<p class="section-subtitle">Worth consuming in full</p>

<!-- For each deep_dive item: -->
<div class="item">
  <h3>{title}</h3>
  <p class="meta">{source} · {duration_or_length} · {relative_date}</p>
  <p class="domains">{domain_tags}</p>
  <p class="summary">{core_summary}</p>
  <a href="{url}">Read/Watch →</a>
</div>

<!-- Worth a Look Section -->
<h2>🟡 Worth a Look</h2>
<p class="section-subtitle">Summary is good; original adds depth</p>
<!-- Same item structure -->

<!-- Summary Sufficient Section -->
<h2>🟢 Summary Sufficient</h2>
<p class="section-subtitle">You've got the gist</p>
<!-- Compact: just title + one-line summary + source -->

<hr>

<!-- Footer -->
<p>Backlog Progress: {percent}% complete ({delivered}/{total})</p>
<p><a href="http://localhost:8000">Open full briefing in browser →</a></p>
```

---

## 10. Web UI Structure

### Routes

| Route | Description |
|-------|-------------|
| `GET /` | Redirect to today's briefing |
| `GET /briefing/{date}` | Briefing for specific date |
| `GET /briefing/today` | Today's briefing |
| `GET /content/{id}` | Full content detail view |
| `GET /backlog` | Backlog progress + remaining items |
| `POST /feedback` | Submit feedback flag |
| `GET /api/stats` | JSON stats for dashboard |

### Main UI Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Daily Briefing                              [Filter by Domain ▾]│
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐  ┌─────────────────┐                           │
│  │STAY CURRENT │  │ BUILD KNOWLEDGE │  Backlog: 67% complete    │
│  │ (active)    │  │                 │  ████████████░░░ 134/200  │
│  └─────────────┘  └─────────────────┘                           │
│                                                                  │
│  February 15, 2025 · 14 items · 9 fresh, 5 backlog              │
│                                                                  │
│  ════════════════════════════════════════════════════════════   │
│                                                                  │
│  🔴 DEEP DIVE (3)                                               │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ How AI is Reshaping SaaS Unit Economics                    │ │
│  │ Stratechery · 14 min read · 2 days ago                     │ │
│  │ #finance #ai #startups                                     │ │
│  │                                                            │ │
│  │ ▼ Summary                                                  │ │
│  │ Ben Thompson argues that AI is fundamentally changing the  │ │
│  │ unit economics of SaaS businesses by reducing marginal     │ │
│  │ costs of service delivery...                               │ │
│  │                                                            │ │
│  │ 💡 Key Insight: The shift from seat-based to usage-based   │ │
│  │ pricing is inevitable as AI handles more of what humans... │ │
│  │                                                            │ │
│  │ [Read Original →]                    [👎 Flag Summary]     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  🟡 WORTH A LOOK (5)                                            │
│  ...                                                            │
│                                                                  │
│  🟢 SUMMARY SUFFICIENT (6)                                      │
│  ...                                                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Expanded Content View

When clicking "▼ Summary", shows:
- Core summary
- Key insights (bullets)
- Concepts explained (if any)
- "So What?" section
- Link to original
- Flag button

---

## 11. Configuration Files

### config/settings.yaml

```yaml
# Daily briefing settings
briefing:
  target_items: 15           # Ideal number of items per day
  min_items: 8               # Minimum (light day)
  max_items: 18              # Hard cap
  email_time: "08:00"        # Local time
  timezone: "Asia/Kolkata"   # Or appropriate timezone
  
# Content freshness windows (in days)
freshness:
  market_call: 14            # 2 weeks
  news_analysis: 28          # 4 weeks
  industry_trend: 56         # 8 weeks
  framework: 365             # Effectively evergreen
  tutorial: 365              # Effectively evergreen
  interview: 42              # 6 weeks
  commentary: 28             # 4 weeks

# Backlog settings
backlog:
  cutoff_date: "2025-01-01"  # Don't fetch before this
  target_completion_days: 75 # ~2.5 months

# Content mix
mix:
  fresh_min_percent: 50
  fresh_max_percent: 70
  backlog_min_items: 2
  backlog_max_items: 8

# LLM settings
llm:
  provider: "gemini"
  model: "gemini-3-flash"
  max_tokens: 4096
  temperature: 0.3           # Lower for consistency
```

### config/domains.yaml

```yaml
domains:
  - id: finance
    name: Finance
    description: Stock investing, markets, macro, valuation
    color: "#22c55e"         # Green
    
  - id: startups
    name: Startups
    description: Building companies, fundraising, product, growth
    color: "#3b82f6"         # Blue
    
  - id: strategy
    name: Strategy
    description: Business strategy, competitive dynamics, moats
    color: "#a855f7"         # Purple
    
  - id: ai
    name: AI
    description: AI technology, capabilities, implications, trends
    color: "#f97316"         # Orange
```

### .env.example

```bash
# Gemini API
GEMINI_API_KEY=your_gemini_api_key_here

# Resend (email)
RESEND_API_KEY=your_resend_api_key_here
EMAIL_TO=your.email@example.com
EMAIL_FROM=briefing@yourdomain.com  # Or use Resend's default

# Optional: YouTube API (for quota-heavy operations)
# YOUTUBE_API_KEY=your_youtube_api_key_here

# Database
DATABASE_PATH=./data/briefing.db
```

---

## 12. Execution Phases

### Phase 1: Project Setup + Content Fetching

**Goal:** Fetch content from all sources and store raw data.

**Build:**
1. Project structure (folders, config files)
2. YouTube fetcher (channel → video list → transcripts)
3. RSS fetcher (Stratechery feed → articles)
4. SQLite database schema
5. CLI command: `python -m src.cli fetch`

**Verify:**
```bash
# Should fetch and store content from all sources
python -m src.cli fetch --source nate-b-jones --limit 5
python -m src.cli fetch --all --since 2025-02-01

# Should show stored content
python -m src.cli list --status pending
```

**Success Criteria:**
- [ ] Can fetch videos from all 7 YouTube channels
- [ ] Can extract transcripts via youtube-transcript-api
- [ ] Can fetch articles from Stratechery RSS
- [ ] All content stored in SQLite with status="pending"

---

### Phase 2: LLM Processing

**Goal:** Process content through Gemini 3 Flash for summarization and tagging.

**Build:**
1. Gemini API client wrapper
2. Prompt templates (versioned)
3. Summarizer that processes pending content
4. Error handling (retry, rate limits)
5. CLI command: `python -m src.cli process`

**Verify:**
```bash
# Process a single item
python -m src.cli process --id abc123

# Process all pending
python -m src.cli process --all

# Inspect processed content
python -m src.cli show --id abc123
```

**Success Criteria:**
- [ ] Can send content to Gemini and get structured JSON response
- [ ] Response correctly parsed into ProcessedContent
- [ ] Domains, tier, freshness all populated
- [ ] Handles long transcripts (chunking if needed)
- [ ] Rate limit handling works

---

### Phase 3: Briefing Composition + Email

**Goal:** Select daily items and send email briefing.

**Build:**
1. Briefing composer (fresh + backlog selection logic)
2. Backlog progress tracking
3. Email HTML template
4. Resend integration
5. CLI command: `python -m src.cli send-briefing`

**Verify:**
```bash
# Preview briefing without sending
python -m src.cli compose --date 2025-02-15 --preview

# Send briefing
python -m src.cli send-briefing --date 2025-02-15

# Check backlog progress
python -m src.cli backlog-status
```

**Success Criteria:**
- [ ] Briefing correctly mixes fresh + backlog
- [ ] Items ordered by tier
- [ ] Email renders correctly
- [ ] Email received in inbox
- [ ] Backlog progress updates after each briefing

---

### Phase 4: Web UI

**Goal:** Build explorable web interface.

**Build:**
1. FastAPI application
2. HTML templates (Jinja2)
3. Routes: today's briefing, historical, backlog view
4. Expand/collapse summaries
5. Feedback flagging UI
6. Domain filtering

**Verify:**
```bash
# Start server
python -m src.cli serve

# Open http://localhost:8000
# - Should see today's briefing
# - Can expand summaries
# - Can filter by domain
# - Can switch to backlog view
# - Can flag summaries
```

**Success Criteria:**
- [ ] UI matches design in this doc
- [ ] All interactions work
- [ ] Feedback stored in database

---

### Phase 5: Automation + Polish

**Goal:** Run automatically every day.

**Build:**
1. launchd plist for Mac scheduling
2. Logging (daily run logs)
3. Error notifications (optional: email on failure)
4. Documentation

**Verify:**
```bash
# Install scheduler
./scripts/install_scheduler.sh

# Check it's registered
launchctl list | grep briefing

# Manually trigger
launchctl start com.dailybriefing.tool
```

**Success Criteria:**
- [ ] Runs automatically at 7:50 AM (10 min before email time)
- [ ] Email arrives by 8 AM
- [ ] Logs capture run history
- [ ] Handles Mac sleep/wake correctly

---

## 13. Edge Cases & Error Handling

| Scenario | Handling |
|----------|----------|
| YouTube transcript unavailable | Log warning, skip item, mark status="no_transcript" |
| Gemini API rate limit | Exponential backoff, max 3 retries |
| Gemini API error | Log error, mark status="failed", continue with others |
| Very long transcript (>100K tokens) | Chunk into sections, summarize each, then synthesize |
| Zero fresh content today | Increase backlog items (up to 8) |
| Backlog exhausted | Show only fresh content, hide backlog section |
| Resend email fails | Retry 3x, log error, save HTML locally as backup |
| RSS feed down | Use cached content, log warning |
| Source publishes duplicate | Dedupe by URL before storing |
| Mac was asleep at run time | launchd runs job when Mac wakes |

---

## 14. Future Extensibility (Noted, Not Built)

### Adding New Domains
1. Add entry to `config/domains.yaml`
2. Update prompt to include new domain
3. No code changes required

### Adding Twitter Source
1. Create `src/fetchers/twitter.py` implementing BaseFetcher
2. Add Twitter source entries to `config/sources.yaml`
3. Handle thread stitching in fetcher
4. Note: Twitter API costs ~$100/month for Basic tier

### Adding Search/Archive
1. Add SQLite full-text search index
2. Add `/search` route
3. Add search UI component

---

## 15. Success Metrics

After 2 weeks of use:
- [ ] Email arrives reliably every day at 8 AM
- [ ] Spending 30-60 min in UI feels productive, not overwhelming
- [ ] Technical concepts from Dwarkesh interviews are understandable
- [ ] Flag rate is <10% (summaries are mostly good)
- [ ] Backlog meter is visibly progressing

After 2-3 months:
- [ ] Backlog is fully cleared
- [ ] Can articulate key AI developments from past 6 months
- [ ] System has become part of daily routine

---

## 16. Open Items for Build Phase

1. **Gemini API key**: Need to set up Google AI Studio account
2. **Resend API key**: Need to create Resend account + verify domain
3. **Test run**: Before full backfill, test with 5-10 items to validate quality
4. **Prompt tuning**: First version of prompts will need iteration

---

*Document complete. Ready for Phase 1 execution.*
