#!/usr/bin/env python3
"""
Full historical fetch script — fetches all content from all sources since Jan 2025.

Runs each source sequentially with cooldown periods between sources
to avoid YouTube rate limiting. Saves progress after each item,
so it's safe to interrupt and resume (existing items are skipped).

Usage:
    source venv/bin/activate
    python scripts/full_fetch.py

    # Or with custom transcript delay:
    python scripts/full_fetch.py --delay 5

    # Dry run (discover videos without fetching transcripts):
    python scripts/full_fetch.py --no-transcripts
"""
from __future__ import annotations

import os
import sys
import time
import argparse
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from src.storage.database import Database
from src.storage.models import Source
from src.fetchers import get_fetcher


def load_sources() -> list[Source]:
    """Load source configurations from YAML."""
    import yaml
    config_path = project_root / "config" / "sources.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return [Source.from_yaml(s) for s in config.get('sources', []) if s.get('active', True)]


def fetch_source(db: Database, source: Source, transcript_delay: float,
                 include_transcripts: bool) -> dict:
    """Fetch all content from a single source. Returns stats dict."""
    fetcher = get_fetcher(source)
    stats = {"new": 0, "skipped": 0, "no_transcript": 0, "errors": 0}

    try:
        for item in fetcher.fetch_all(
            since=source.fetch_since,
            limit=1000,  # High limit to get full history
            include_transcripts=include_transcripts,
            transcript_delay=transcript_delay,
        ):
            if db.save_content(item):
                stats["new"] += 1
                if item.transcript:
                    status_icon = "✓"
                    wc = f" ({item.word_count:,} words)"
                elif item.status == "no_transcript":
                    status_icon = "○"
                    wc = ""
                    stats["no_transcript"] += 1
                else:
                    status_icon = "·"
                    wc = ""
                print(f"  {status_icon} {item.title[:65]}{wc}")
            else:
                stats["skipped"] += 1

    except Exception as e:
        print(f"  ERROR: {e}")
        stats["errors"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Full historical content fetch")
    parser.add_argument("--delay", type=float, default=3.0,
                        help="Seconds between transcript fetches (default: 3)")
    parser.add_argument("--cooldown", type=float, default=60.0,
                        help="Seconds to wait between sources (default: 60)")
    parser.add_argument("--no-transcripts", action="store_true",
                        help="Skip transcript fetching (discovery only)")
    parser.add_argument("--source", type=str, default=None,
                        help="Only fetch a specific source ID")
    args = parser.parse_args()

    db = Database()
    sources = load_sources()

    if args.source:
        sources = [s for s in sources if s.id == args.source]
        if not sources:
            print(f"Source not found: {args.source}")
            sys.exit(1)

    print(f"{'='*60}")
    print(f"FULL HISTORICAL FETCH")
    print(f"  Sources: {len(sources)}")
    print(f"  Transcript delay: {args.delay}s")
    print(f"  Cooldown between sources: {args.cooldown}s")
    print(f"  Transcripts: {'SKIP' if args.no_transcripts else 'YES'}")
    print(f"  Started: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")

    total_stats = {"new": 0, "skipped": 0, "no_transcript": 0, "errors": 0}
    source_results = []

    for i, source in enumerate(sources):
        # Cooldown between sources (not before the first one)
        if i > 0 and args.cooldown > 0:
            print(f"\n  ⏳ Cooling down {args.cooldown:.0f}s before next source...")
            time.sleep(args.cooldown)

        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(sources)}] {source.name}")
        print(f"  Type: {source.source_type}")
        print(f"  Since: {source.fetch_since}")
        print(f"  Started: {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*60}")

        start = time.time()
        stats = fetch_source(db, source, args.delay, not args.no_transcripts)
        elapsed = time.time() - start

        source_results.append({
            "source": source.name,
            "source_id": source.id,
            **stats,
            "elapsed": elapsed,
        })

        for k in total_stats:
            total_stats[k] += stats[k]

        print(f"\n  Summary: {stats['new']} new, {stats['skipped']} existing, "
              f"{stats['no_transcript']} no transcript, {stats['errors']} errors "
              f"({elapsed:.0f}s)")

    # Final report
    print(f"\n{'='*60}")
    print(f"FETCH COMPLETE — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")

    print(f"\n{'Source':<25} {'New':>5} {'Skip':>5} {'NoTx':>5} {'Err':>4} {'Time':>6}")
    print(f"{'-'*52}")
    for r in source_results:
        print(f"{r['source']:<25} {r['new']:>5} {r['skipped']:>5} "
              f"{r['no_transcript']:>5} {r['errors']:>4} {r['elapsed']:>5.0f}s")
    print(f"{'-'*52}")
    print(f"{'TOTAL':<25} {total_stats['new']:>5} {total_stats['skipped']:>5} "
          f"{total_stats['no_transcript']:>5} {total_stats['errors']:>4}")

    # DB stats
    status_counts = db.count_content_by_status()
    total_items = sum(status_counts.values())
    print(f"\n  Database: {total_items} total items")
    for status, count in sorted(status_counts.items()):
        print(f"    {status}: {count}")

    if total_stats["no_transcript"] > 0:
        print(f"\n  ⚠ {total_stats['no_transcript']} items had no transcript.")
        print(f"  Run: python -m src.cli retry-transcripts --delay 5")

    pending = status_counts.get("pending", 0)
    if pending > 0:
        print(f"\n  Next step: python -m src.cli process --all --delay 10")


if __name__ == "__main__":
    main()
