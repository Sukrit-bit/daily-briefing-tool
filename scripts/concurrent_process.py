#!/usr/bin/env python3
"""
Concurrent LLM processing script — processes pending content items through
Gemini and OpenAI simultaneously using asyncio.

Fires multiple API calls in parallel (controlled by semaphores) and serializes
all DB writes through a single asyncio.Queue consumer to avoid SQLite lock
contention.

Usage:
    source venv/bin/activate

    # Dry run (show what would be processed):
    python scripts/concurrent_process.py --dry-run

    # Small test batch:
    python scripts/concurrent_process.py --limit 10 --gemini-concurrency 2 --openai-concurrency 2

    # Full run with both providers:
    python scripts/concurrent_process.py

    # Gemini only:
    python scripts/concurrent_process.py --gemini-share 1.0

    # OpenAI only:
    python scripts/concurrent_process.py --gemini-share 0.0
"""
from __future__ import annotations

import asyncio
import argparse
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from src.storage.database import Database
from src.storage.models import ContentItem, ProcessedContent
from src.processors.summarizer import Summarizer, MIN_WORD_COUNT
from src.processors.prompts import build_summarization_prompt, PROMPT_VERSION
from src.fetchers.rss import _is_paywall_content


# ==============================================================================
# Async LLM Callers
# ==============================================================================

class AsyncGeminiCaller:
    """
    Native async Gemini caller using google.genai aio interface.
    Mirrors the retry logic from GeminiClient.generate().
    """

    MAX_INPUT_TOKENS = 900_000

    def __init__(self):
        from google import genai
        from google.genai import types
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.model_name = "gemini-2.5-flash"
        self._types = types

    async def generate(self, prompt: str, max_retries: int = 3) -> Optional[dict]:
        """Send a prompt to Gemini async and return parsed JSON, or None on failure."""
        for attempt in range(max_retries):
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=self._types.GenerateContentConfig(
                        temperature=0.3,
                        max_output_tokens=4096,
                        response_mime_type="application/json",
                    ),
                )

                text = response.text.strip()

                # Strip markdown code blocks (Gemini sometimes wraps JSON)
                if text.startswith("```json"):
                    text = text[7:]
                if text.startswith("```"):
                    text = text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

                return json.loads(text)

            except json.JSONDecodeError as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

            except Exception as e:
                error_str = str(e).lower()

                if "429" in error_str or "rate" in error_str or "quota" in error_str:
                    # Daily quota exhaustion — no point retrying
                    if "free_tier" in error_str and "limit: 0" in error_str:
                        print(f"  [Gemini] FREE TIER QUOTA EXHAUSTED — cannot retry")
                        return None
                    wait_time = 30 * (attempt + 1)
                    print(f"  [Gemini] Rate limited, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait_time)

                elif "500" in error_str or "503" in error_str:
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)

                else:
                    print(f"  [Gemini] API error (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)

        return None

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return len(text) // 4

    @staticmethod
    def truncate_for_context(text: str, max_tokens: int) -> str:
        max_chars = max_tokens * 4
        truncated = text[:max_chars]
        last_period = truncated.rfind('. ')
        if last_period > max_chars * 0.8:
            truncated = truncated[:last_period + 1]
        return truncated + "\n\n[Content truncated due to length]"


class AsyncOpenAICaller:
    """
    Native async OpenAI caller using AsyncOpenAI.
    Mirrors the retry logic from OpenAIClient.generate().
    """

    MAX_INPUT_TOKENS = 120_000

    def __init__(self):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model_name = "gpt-4o"

    async def generate(self, prompt: str, max_retries: int = 3) -> Optional[dict]:
        """Send a prompt to OpenAI async and return parsed JSON, or None on failure."""
        for attempt in range(max_retries):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a sharp tech/business analyst. Always respond with valid JSON only, no markdown formatting."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0.3,
                    max_tokens=4096,
                    response_format={"type": "json_object"},
                )

                text = response.choices[0].message.content.strip()

                # Strip markdown code blocks
                if text.startswith("```json"):
                    text = text[7:]
                if text.startswith("```"):
                    text = text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

                return json.loads(text)

            except json.JSONDecodeError as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

            except Exception as e:
                error_str = str(e).lower()

                if "429" in error_str or "rate" in error_str:
                    wait_time = 30 * (attempt + 1)
                    print(f"  [OpenAI] Rate limited, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait_time)

                elif "500" in error_str or "503" in error_str:
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)

                else:
                    print(f"  [OpenAI] API error (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)

        return None

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return len(text) // 4

    @staticmethod
    def truncate_for_context(text: str, max_tokens: int) -> str:
        max_chars = max_tokens * 4
        truncated = text[:max_chars]
        last_period = truncated.rfind('. ')
        if last_period > max_chars * 0.8:
            truncated = truncated[:last_period + 1]
        return truncated + "\n\n[Content truncated due to length]"


# ==============================================================================
# Core Processing Logic
# ==============================================================================

async def process_one(
    item: ContentItem,
    caller,
    semaphore: asyncio.Semaphore,
    db_queue: asyncio.Queue,
    summarizer: Summarizer,
    stats: dict,
    provider_name: str,
):
    """Process a single content item through the LLM and enqueue the DB write."""
    async with semaphore:
        try:
            # 1. Build prompt
            prompt = build_summarization_prompt(item)

            # 2. Truncate if needed
            estimated_tokens = caller.estimate_tokens(prompt)
            if estimated_tokens > caller.MAX_INPUT_TOKENS:
                prompt_without_transcript = prompt.replace(item.transcript, "")
                max_transcript_tokens = caller.MAX_INPUT_TOKENS - caller.estimate_tokens(
                    prompt_without_transcript
                )
                truncated_transcript = caller.truncate_for_context(
                    item.transcript, max_transcript_tokens
                )
                original_transcript = item.transcript
                item.transcript = truncated_transcript
                prompt = build_summarization_prompt(item)
                item.transcript = original_transcript  # Restore original

            # 3. Call LLM (this is the async I/O we're parallelizing)
            result = await caller.generate(prompt)

            # 4. Parse response using existing Summarizer logic
            processed = None
            if result is not None:
                processed = summarizer._parse_response(item, result)
                if processed:
                    processed.model_used = caller.model_name

            # 5. Enqueue DB write
            await db_queue.put(("result", item, processed, provider_name))

        except Exception as e:
            print(f"  ERROR [{provider_name}] {item.title[:45]}: {e}")
            await db_queue.put(("result", item, None, provider_name))


async def db_writer(db_queue: asyncio.Queue, db: Database, stats: dict):
    """
    Single coroutine that serializes all DB writes.
    Since asyncio is single-threaded, this avoids SQLite lock contention.
    """
    while True:
        msg = await db_queue.get()

        # Sentinel to stop
        if msg is None:
            db_queue.task_done()
            break

        _, item, processed, provider_name = msg

        try:
            if processed is not None:
                db.save_processed(processed)
                db.update_content_status(item.id, "processed")
                stats["processed"] += 1
                stats[f"{provider_name}_ok"] += 1
            else:
                db.update_content_status(item.id, "failed")
                stats["failed"] += 1
                stats[f"{provider_name}_fail"] += 1
        except Exception as e:
            print(f"  DB ERROR for {item.id}: {e}")
            stats["db_errors"] += 1
        finally:
            db_queue.task_done()


async def progress_reporter(stats: dict, total: int, interval: float = 10):
    """Print processing progress every `interval` seconds."""
    start = time.time()
    while not stats.get("done"):
        await asyncio.sleep(interval)
        elapsed = time.time() - start
        completed = stats["processed"] + stats["failed"]
        rate = completed / elapsed if elapsed > 0 else 0
        remaining = total - completed
        eta = remaining / rate if rate > 0 else 0

        gemini_total = stats["gemini_ok"] + stats["gemini_fail"]
        openai_total = stats["openai_ok"] + stats["openai_fail"]

        print(
            f"  [{elapsed:>5.0f}s] {completed:>4}/{total} done "
            f"({stats['processed']} ok, {stats['failed']} fail) | "
            f"{rate:.1f}/s | ETA {eta:.0f}s | "
            f"Gemini: {stats['gemini_ok']}/{gemini_total} | "
            f"OpenAI: {stats['openai_ok']}/{openai_total}"
        )


# ==============================================================================
# Main Orchestrator
# ==============================================================================

async def run(args):
    """Main async entry point."""
    db = Database()

    # ---- 1. Load and pre-filter ----
    pending = db.get_pending_content(limit=args.limit)
    print(f"\nLoaded {len(pending)} pending items")

    stats = {
        "processed": 0, "failed": 0, "skipped": 0,
        "gemini_ok": 0, "gemini_fail": 0,
        "openai_ok": 0, "openai_fail": 0,
        "db_errors": 0, "done": False,
    }

    processable = []
    skip_reasons = {"no_transcript": 0, "paywall": 0, "too_short": 0}

    for item in pending:
        if not item.transcript:
            db.update_content_status(item.id, "no_transcript")
            stats["skipped"] += 1
            skip_reasons["no_transcript"] += 1
        elif _is_paywall_content(item.transcript):
            db.update_content_status(item.id, "paywall")
            stats["skipped"] += 1
            skip_reasons["paywall"] += 1
        elif item.word_count < MIN_WORD_COUNT:
            db.update_content_status(item.id, "skipped")
            stats["skipped"] += 1
            skip_reasons["too_short"] += 1
        else:
            processable.append(item)

    print(f"Processable: {len(processable)} | Skipped: {stats['skipped']}")
    if stats["skipped"] > 0:
        for reason, count in skip_reasons.items():
            if count > 0:
                print(f"  - {reason}: {count}")

    if not processable:
        print("Nothing to process!")
        return stats

    # ---- 2. Dry run ----
    if args.dry_run:
        print(f"\n[DRY RUN] Would process {len(processable)} items:")
        # Show source breakdown
        from collections import Counter
        source_counts = Counter(item.source_id for item in processable)
        for source_id, count in source_counts.most_common():
            print(f"  {source_id}: {count}")

        avg_words = sum(item.word_count for item in processable) // len(processable)
        print(f"\n  Avg word count: {avg_words:,}")
        print(f"  Gemini batch: {int(len(processable) * args.gemini_share)}")
        print(f"  OpenAI batch: {len(processable) - int(len(processable) * args.gemini_share)}")
        return stats

    # ---- 3. Initialize providers ----
    gemini_caller = None
    openai_caller = None

    if os.getenv("GEMINI_API_KEY") and args.gemini_share > 0:
        try:
            gemini_caller = AsyncGeminiCaller()
            print(f"  Gemini: {gemini_caller.model_name} (concurrency: {args.gemini_concurrency})")
        except Exception as e:
            print(f"  WARNING: Gemini init failed: {e}")

    if os.getenv("OPENAI_API_KEY") and args.gemini_share < 1.0:
        try:
            openai_caller = AsyncOpenAICaller()
            print(f"  OpenAI: {openai_caller.model_name} (concurrency: {args.openai_concurrency})")
        except Exception as e:
            print(f"  WARNING: OpenAI init failed: {e}")

    if not gemini_caller and not openai_caller:
        print("ERROR: No LLM providers available. Check API keys in .env")
        return stats

    # If one provider failed to init, send everything to the other
    if not gemini_caller:
        args.gemini_share = 0.0
        print("  → All items routed to OpenAI (Gemini unavailable)")
    elif not openai_caller:
        args.gemini_share = 1.0
        print("  → All items routed to Gemini (OpenAI unavailable)")

    # ---- 4. Partition items ----
    random.shuffle(processable)  # Avoid source clustering

    split_idx = int(len(processable) * args.gemini_share)
    gemini_items = processable[:split_idx] if gemini_caller else []
    openai_items = processable[split_idx:] if openai_caller else processable

    # If one provider is missing, route all to the other
    if not gemini_caller:
        openai_items = processable
        gemini_items = []
    elif not openai_caller:
        gemini_items = processable
        openai_items = []

    print(f"\n  Gemini batch: {len(gemini_items)} items")
    print(f"  OpenAI batch: {len(openai_items)} items")

    # ---- 5. Setup async infrastructure ----
    # Summarizer instance for _parse_response() reuse (CPU-only, safe in asyncio)
    summarizer = Summarizer(db=db)

    db_queue = asyncio.Queue()
    gemini_sem = asyncio.Semaphore(args.gemini_concurrency)
    openai_sem = asyncio.Semaphore(args.openai_concurrency)

    # ---- 6. Launch ----
    total_processable = len(processable)
    start_time = time.time()

    print(f"\n{'='*60}")
    print(f"PROCESSING {total_processable} ITEMS")
    print(f"  Started: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")

    # Start the DB writer and progress reporter
    writer_task = asyncio.create_task(db_writer(db_queue, db, stats))
    reporter_task = asyncio.create_task(
        progress_reporter(stats, total_processable, args.progress_interval)
    )

    # Create all processing tasks
    gemini_tasks = [
        process_one(item, gemini_caller, gemini_sem, db_queue, summarizer, stats, "gemini")
        for item in gemini_items
    ] if gemini_caller else []

    openai_tasks = [
        process_one(item, openai_caller, openai_sem, db_queue, summarizer, stats, "openai")
        for item in openai_items
    ] if openai_caller else []

    # Run all tasks concurrently
    results = await asyncio.gather(
        *gemini_tasks, *openai_tasks,
        return_exceptions=True
    )

    # Check for unexpected exceptions
    exceptions = [r for r in results if isinstance(r, Exception)]
    if exceptions:
        print(f"\n  ⚠ {len(exceptions)} unexpected exceptions during processing:")
        for exc in exceptions[:5]:
            print(f"    {type(exc).__name__}: {exc}")
        if len(exceptions) > 5:
            print(f"    ... and {len(exceptions) - 5} more")

    # ---- 7. Drain queue and cleanup ----
    await db_queue.join()  # Wait for all DB writes to complete
    await db_queue.put(None)  # Sentinel to stop writer
    await writer_task

    stats["done"] = True
    reporter_task.cancel()
    try:
        await reporter_task
    except asyncio.CancelledError:
        pass

    elapsed = time.time() - start_time

    # ---- 8. Final report ----
    print(f"\n{'='*60}")
    print(f"PROCESSING COMPLETE — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")
    print(f"  Total time: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print(f"  Rate: {(stats['processed'] + stats['failed']) / elapsed:.1f} items/s")
    print(f"\n  Processed: {stats['processed']}")
    print(f"  Failed:    {stats['failed']}")
    print(f"  Skipped:   {stats['skipped']}")
    print(f"  DB errors: {stats['db_errors']}")
    print(f"\n  Gemini: {stats['gemini_ok']} ok / {stats['gemini_fail']} fail")
    print(f"  OpenAI: {stats['openai_ok']} ok / {stats['openai_fail']} fail")

    # Tier distribution
    cursor = db.conn.cursor()
    cursor.execute("SELECT tier, COUNT(*) FROM processed_content GROUP BY tier")
    tier_dist = cursor.fetchall()
    if tier_dist:
        print(f"\n  Tier distribution:")
        for tier, count in sorted(tier_dist, key=lambda x: x[1], reverse=True):
            print(f"    {tier}: {count}")

    # DB status summary
    status_counts = db.count_content_by_status()
    total_items = sum(status_counts.values())
    print(f"\n  Database: {total_items} total items")
    for status, count in sorted(status_counts.items()):
        print(f"    {status}: {count}")

    if stats["failed"] > 0:
        print(f"\n  ⚠ {stats['failed']} items failed. To retry:")
        print(f"    python scripts/concurrent_process.py --limit {stats['failed']}")

    if stats["processed"] > 0:
        print(f"\n  Next step: python -m src.cli compose --preview")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Concurrent LLM processing for bulk content backlog",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Dry run:
    python scripts/concurrent_process.py --dry-run

    # Small test:
    python scripts/concurrent_process.py --limit 10

    # Full run (both providers):
    python scripts/concurrent_process.py

    # Gemini only:
    python scripts/concurrent_process.py --gemini-share 1.0

    # OpenAI only:
    python scripts/concurrent_process.py --gemini-share 0.0
        """
    )
    parser.add_argument(
        "--gemini-concurrency", type=int, default=5,
        help="Max concurrent Gemini API calls (default: 5)"
    )
    parser.add_argument(
        "--openai-concurrency", type=int, default=3,
        help="Max concurrent OpenAI API calls (default: 3)"
    )
    parser.add_argument(
        "--gemini-share", type=float, default=0.7,
        help="Fraction of items to send to Gemini, rest go to OpenAI (default: 0.7)"
    )
    parser.add_argument(
        "--limit", "-n", type=int, default=None,
        help="Maximum items to process (default: all pending)"
    )
    parser.add_argument(
        "--progress-interval", type=float, default=10,
        help="Seconds between progress reports (default: 10)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be processed without calling APIs"
    )
    args = parser.parse_args()

    # Validate gemini-share
    if not 0.0 <= args.gemini_share <= 1.0:
        print("ERROR: --gemini-share must be between 0.0 and 1.0")
        sys.exit(1)

    print(f"{'='*60}")
    print(f"CONCURRENT LLM PROCESSING")
    print(f"  Gemini concurrency: {args.gemini_concurrency}")
    print(f"  OpenAI concurrency: {args.openai_concurrency}")
    print(f"  Gemini share: {args.gemini_share:.0%}")
    print(f"  Limit: {args.limit or 'all'}")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    try:
        stats = asyncio.run(run(args))
    except KeyboardInterrupt:
        print(f"\n\n{'='*60}")
        print("INTERRUPTED — items already saved to DB are safe.")
        print("Rerun to continue processing remaining pending items.")
        print(f"{'='*60}")
        sys.exit(1)


if __name__ == "__main__":
    main()
