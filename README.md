# Daily Briefing Tool

A personal content aggregation and summarization system that fetches YouTube videos and RSS articles from curated sources, processes them through LLMs (Gemini primary, OpenAI fallback), composes daily briefings with tier-based prioritization, and delivers them via email.

## How It Works

```
fetch → process → compose → send-briefing
  │         │          │          │
  │         │          │          └── Email via Resend + LLM editorial intro
  │         │          └── Selection, diversity caps, tier ordering
  │         └── LLM summarization → blacklist → tier calibration
  └── YouTube Data API / RSS → transcripts → SQLite
```

1. **Fetch** — Pull videos and articles from configured sources, extract transcripts
2. **Process** — Send content through Gemini/OpenAI for summarization, tagging, and tiering
3. **Compose** — Select items for a daily briefing (source diversity, deep dive caps, priority ordering)
4. **Send** — Generate an HTML email with a headline index + detail cards, deliver via Resend

## Tier System

| Tier | Meaning | Detail in email |
|------|---------|-----------------|
| Deep Dive | Worth consuming in full — summary captures <50% of value | Full card: summary + insights + so-what + link |
| Worth a Look | Solid content — summary captures 60-80% | Medium card: summary + insights + link |
| Summary Sufficient | You've got the gist — summary captures 90%+ | Compact: summary + inline take |

## Setup

### Prerequisites

- Python 3.9+
- API keys for Gemini, OpenAI (optional fallback), Resend (email), YouTube Data API v3 (optional)

### Install

```bash
git clone https://github.com/YOUR_USERNAME/daily-briefing-tool.git
cd daily-briefing-tool

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Edit .env with your API keys
```

See `.env.example` for all required and optional keys.

### Initialize

```bash
python -m src.cli init-db
python -m src.cli sources  # verify configured sources
```

## Usage

### Daily workflow

```bash
# Fetch new content from all sources
python -m src.cli fetch --all

# Process pending items through LLM
python -m src.cli process --all --delay 5

# Preview the briefing in your browser
python -m src.cli compose --preview

# Send the briefing email
python -m src.cli send-briefing
```

### CLI Commands

| Command | Example | Description |
|---------|---------|-------------|
| `fetch` | `fetch --all --since 2025-02-01` | Fetch content from sources |
| `fetch` | `fetch --source dwarkesh-patel --limit 5` | Fetch from one source |
| `process` | `process --all --limit 10 --delay 5` | Process pending items through LLM |
| `process` | `process --all --provider openai` | Force a specific LLM provider |
| `compose` | `compose --preview` | Preview briefing in browser |
| `compose` | `compose --save-html` | Save briefing HTML to `data/` |
| `send-briefing` | `send-briefing` | Compose + send email + mark delivered |
| `send-briefing` | `send-briefing --no-email` | Compose + save without sending |
| `retry-transcripts` | `retry-transcripts --source bg2-pod --delay 3` | Retry failed transcript fetches |
| `enrich-durations` | `enrich-durations` | Backfill missing video durations via yt-dlp |
| `list` | `list --status pending` | List content items |
| `show` | `show <content_id> --full` | Show item details + transcript |
| `stats` | `stats` | Database statistics |
| `sources` | `sources` | List configured sources |
| `init-db` | `init-db` | Initialize database schema |

### Bulk Processing

For large backlogs, use the concurrent processing script:

```bash
# Preview what would be processed
python scripts/concurrent_process.py --dry-run

# Process with conservative concurrency (recommended)
python scripts/concurrent_process.py --gemini-concurrency 5 --openai-concurrency 3

# Gemini only
python scripts/concurrent_process.py --gemini-share 1.0
```

## Sources

The tool ships with 8 curated sources (7 YouTube + 1 RSS) in `config/sources.yaml`:

| Source | Type | Focus |
|--------|------|-------|
| Nate B Jones | YouTube | AI news & strategy |
| Greg Isenberg | YouTube | Startups, strategy |
| Y Combinator | YouTube | Startups |
| Dwarkesh Patel | YouTube | AI, strategy (deep interviews) |
| Lenny's Podcast | YouTube | Startups, product, strategy |
| 20VC (Harry Stebbings) | YouTube | Startups, finance |
| BG2 Pod | YouTube | Finance, AI, strategy |
| Stratechery (Ben Thompson) | RSS | Strategy, AI (free articles only) |

Add or remove sources by editing `config/sources.yaml`.

## Project Structure

```
daily-briefing-tool/
├── config/
│   └── sources.yaml              # Content source definitions
├── src/
│   ├── cli.py                    # CLI commands (Click framework)
│   ├── fetchers/
│   │   ├── base.py               # Abstract base fetcher
│   │   ├── youtube.py            # YouTube Data API v3 + transcripts + yt-dlp
│   │   └── rss.py                # RSS feeds + paywall detection + pagination
│   ├── processors/
│   │   ├── prompts.py            # LLM prompt templates (versioned)
│   │   ├── summarizer.py         # Orchestrator: process → parse → blacklist → calibrate
│   │   ├── llm_client.py         # Unified LLM interface with auto-fallback
│   │   ├── gemini_client.py      # Gemini wrapper (google.genai SDK)
│   │   └── openai_client.py      # OpenAI wrapper (GPT-4o)
│   ├── briefing/
│   │   ├── composer.py           # Item selection, diversity, caps, ordering
│   │   └── emailer.py            # HTML email generation + Resend delivery
│   ├── storage/
│   │   ├── database.py           # SQLite operations
│   │   └── models.py             # Data models (dataclasses)
│   └── web/                      # Web UI (planned, not yet implemented)
├── scripts/
│   ├── full_fetch.py             # Batch historical fetch (sequential)
│   └── concurrent_process.py     # Async bulk LLM processing (concurrent)
├── data/                         # SQLite DB + HTML briefing backups (gitignored)
├── .env.example                  # Environment variable template
├── requirements.txt              # Python dependencies
└── PRD.md                        # Product requirements document
```

## Architecture

### LLM Processing

Each content item is processed through:

1. **Prompt construction** — metadata + full transcript sent to LLM
2. **JSON response parsing** — structured output with summary, insights, tier, tags
3. **Blacklist enforcement** — regex-based post-processing catches phrases LLMs ignore ~20% of the time
4. **Tier calibration** — word count thresholds auto-promote/demote tiers (e.g., 18K+ words → deep dive)

The system uses Gemini as the primary provider with automatic fallback to OpenAI when rate-limited.

### Briefing Composition

The composer selects items with:

- **Source diversity caps** — max 2-3 items per source
- **Deep dive cap** — max 3 per briefing
- **Priority ordering** — deep dives first, then worth-a-look, then summary-sufficient
- **Fresh/backlog mix** — adjusts based on daily volume

### Email Design

Two-layer email optimized for a 5-10 minute morning scan:

- **Layer 1 (Headline Index)** — glanceable list with tier emoji, title, source, length, topic tags
- **Layer 2 (Detail Cards)** — tier-appropriate summary cards with insights and so-what analysis

## Project Status

| Phase | Status |
|-------|--------|
| 1 — Content Fetching | Complete |
| 2 — LLM Processing | Complete |
| 3 — Briefing + Email | Complete |
| 4 — Web UI | Not started |
| 5 — Automation (launchd) | Not started |

## License

MIT
