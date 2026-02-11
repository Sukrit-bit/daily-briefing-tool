"""
Command-line interface for the Daily Briefing Tool.

Usage:
    python -m src.cli fetch --source nate-b-jones --limit 5
    python -m src.cli fetch --all --since 2025-02-01
    python -m src.cli list --status pending
    python -m src.cli show --id abc123
    python -m src.cli stats
"""

import os
import sys
from datetime import datetime, date
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.storage.database import Database
from src.storage.models import Source, ContentItem
from src.fetchers import get_fetcher
from src.processors import Summarizer, GeminiClient, LLMClient
from src.briefing import BriefingComposer, Emailer


# Load environment variables
load_dotenv()


def load_sources() -> list[Source]:
    """Load source configurations from YAML."""
    config_path = project_root / "config" / "sources.yaml"
    if not config_path.exists():
        click.echo(f"Error: Config file not found: {config_path}", err=True)
        sys.exit(1)
    
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    sources = []
    for source_data in config.get('sources', []):
        if source_data.get('active', True):
            sources.append(Source.from_yaml(source_data))
    
    return sources


def get_source_by_id(source_id: str) -> Source:
    """Get a specific source by ID."""
    sources = load_sources()
    for source in sources:
        if source.id == source_id:
            return source
    click.echo(f"Error: Source not found: {source_id}", err=True)
    click.echo(f"Available sources: {', '.join(s.id for s in sources)}")
    sys.exit(1)


@click.group()
@click.option('--db-path', default=None, help='Path to database file')
@click.pass_context
def cli(ctx, db_path):
    """Daily Briefing Tool - Content aggregation and summarization."""
    ctx.ensure_object(dict)
    ctx.obj['db'] = Database(db_path)


@cli.command()
@click.option('--source', '-s', help='Source ID to fetch (e.g., nate-b-jones)')
@click.option('--all', 'fetch_all', is_flag=True, help='Fetch from all sources')
@click.option('--since', type=click.DateTime(formats=['%Y-%m-%d']), help='Fetch content since date (YYYY-MM-DD)')
@click.option('--limit', '-n', type=int, default=500, help='Maximum items to fetch per source')
@click.option('--no-transcripts', is_flag=True, help='Skip transcript fetching (faster)')
@click.pass_context
def fetch(ctx, source, fetch_all, since, limit, no_transcripts):
    """
    Fetch content from sources.
    
    Examples:
        python -m src.cli fetch --source nate-b-jones --limit 5
        python -m src.cli fetch --all --since 2025-02-01
    """
    db = ctx.obj['db']
    
    if not source and not fetch_all:
        click.echo("Error: Specify --source or --all", err=True)
        sys.exit(1)
    
    # Determine which sources to fetch
    if fetch_all:
        sources = load_sources()
    else:
        sources = [get_source_by_id(source)]
    
    # Convert datetime to date if provided
    since_date = since.date() if since else None
    
    total_new = 0
    total_skipped = 0
    
    for src in sources:
        click.echo(f"\n{'='*50}")
        click.echo(f"Fetching from: {src.name}")
        click.echo(f"Type: {src.source_type}")
        click.echo(f"Since: {since_date or src.fetch_since}")
        click.echo('='*50)
        
        try:
            fetcher = get_fetcher(src)
            
            new_count = 0
            skip_count = 0
            
            for item in fetcher.fetch_all(
                since=since_date or src.fetch_since,
                limit=limit,
                include_transcripts=not no_transcripts
            ):
                # Try to save (will fail silently if duplicate)
                if db.save_content(item):
                    new_count += 1
                    status_icon = "✓" if item.transcript else "○"
                    click.echo(f"  {status_icon} {item.title[:60]}...")
                    if item.transcript:
                        click.echo(f"      Words: {item.word_count:,}")
                else:
                    skip_count += 1
            
            click.echo(f"\n  New: {new_count} | Skipped (existing): {skip_count}")
            total_new += new_count
            total_skipped += skip_count
            
        except Exception as e:
            click.echo(f"  Error: {e}", err=True)
    
    click.echo(f"\n{'='*50}")
    click.echo(f"TOTAL: {total_new} new items | {total_skipped} skipped")
    click.echo('='*50)


@cli.command('list')
@click.option('--status', '-s', type=click.Choice(['pending', 'processed', 'failed', 'no_transcript']), 
              help='Filter by status')
@click.option('--source', help='Filter by source ID')
@click.option('--limit', '-n', type=int, default=20, help='Maximum items to show')
@click.pass_context
def list_content(ctx, status, source, limit):
    """
    List content items in the database.
    
    Examples:
        python -m src.cli list --status pending
        python -m src.cli list --source nate-b-jones
    """
    db = ctx.obj['db']
    
    # Get items based on filters
    if status:
        items = db.get_pending_content(limit=limit) if status == 'pending' else []
        # For other statuses, we need to add a query method
        if status != 'pending':
            cursor = db.conn.cursor()
            cursor.execute(
                "SELECT * FROM content_items WHERE status = ? ORDER BY published_at DESC LIMIT ?",
                (status, limit)
            )
            items = [db._row_to_content_item(row) for row in cursor.fetchall()]
    elif source:
        items = db.get_content_by_source(source)[:limit]
    else:
        cursor = db.conn.cursor()
        cursor.execute("SELECT * FROM content_items ORDER BY published_at DESC LIMIT ?", (limit,))
        items = [db._row_to_content_item(row) for row in cursor.fetchall()]
    
    if not items:
        click.echo("No items found.")
        return
    
    click.echo(f"\n{'ID':<18} {'Status':<12} {'Source':<20} {'Title':<40}")
    click.echo("-" * 90)
    
    for item in items:
        title = item.title[:38] + ".." if len(item.title) > 40 else item.title
        source_name = item.source_id[:18] + ".." if len(item.source_id) > 20 else item.source_id
        click.echo(f"{item.id:<18} {item.status:<12} {source_name:<20} {title:<40}")
    
    click.echo(f"\nTotal: {len(items)} items")


@cli.command()
@click.argument('content_id')
@click.option('--full', is_flag=True, help='Show full transcript')
@click.pass_context
def show(ctx, content_id, full):
    """
    Show details of a content item.
    
    Examples:
        python -m src.cli show abc123
        python -m src.cli show abc123 --full
    """
    db = ctx.obj['db']
    
    item = db.get_content(content_id)
    if not item:
        click.echo(f"Content not found: {content_id}", err=True)
        sys.exit(1)
    
    click.echo(f"\n{'='*60}")
    click.echo(f"ID:        {item.id}")
    click.echo(f"Title:     {item.title}")
    click.echo(f"Source:    {item.source_name}")
    click.echo(f"URL:       {item.url}")
    click.echo(f"Published: {item.published_at}")
    click.echo(f"Status:    {item.status}")
    click.echo(f"Words:     {item.word_count:,}")
    if item.duration_seconds:
        mins = item.duration_seconds // 60
        secs = item.duration_seconds % 60
        click.echo(f"Duration:  {mins}m {secs}s")
    click.echo('='*60)
    
    if item.transcript:
        if full:
            click.echo("\nFull Transcript:")
            click.echo("-" * 40)
            click.echo(item.transcript)
        else:
            preview = item.transcript[:500]
            if len(item.transcript) > 500:
                preview += "...\n\n[Use --full to see complete transcript]"
            click.echo("\nTranscript Preview:")
            click.echo("-" * 40)
            click.echo(preview)
    else:
        click.echo("\n[No transcript available]")
    
    # Show processed data if available
    processed = db.get_processed(content_id)
    if processed:
        click.echo(f"\n{'='*60}")
        click.echo("PROCESSED DATA")
        click.echo('='*60)
        click.echo(f"Tier:      {processed.tier_emoji} {processed.tier}")
        click.echo(f"Domains:   {', '.join(processed.domains)}")
        click.echo(f"Freshness: {processed.freshness}")
        click.echo(f"\nSummary:\n{processed.core_summary}")
        if processed.key_insights:
            click.echo("\nKey Insights:")
            for insight in processed.key_insights:
                click.echo(f"  • {insight}")


@cli.command()
@click.pass_context
def stats(ctx):
    """Show database statistics."""
    db = ctx.obj['db']
    
    status_counts = db.count_content_by_status()
    total = sum(status_counts.values())
    
    click.echo(f"\n{'='*40}")
    click.echo("DATABASE STATISTICS")
    click.echo('='*40)
    
    click.echo(f"\nContent by Status:")
    for status, count in sorted(status_counts.items()):
        pct = (count / total * 100) if total > 0 else 0
        bar = "█" * int(pct / 5)
        click.echo(f"  {status:<15} {count:>5} ({pct:>5.1f}%) {bar}")
    
    click.echo(f"\n  {'TOTAL':<15} {total:>5}")
    
    # Backlog progress
    progress = db.get_backlog_progress()
    if progress:
        click.echo(f"\nBacklog Progress:")
        click.echo(f"  {progress.percent_complete:.1f}% complete ({progress.delivered_items}/{progress.total_items})")
        est = progress.estimated_completion()
        if est:
            click.echo(f"  Estimated completion: {est}")


@cli.command()
@click.pass_context
def sources(ctx):
    """List all configured sources."""
    all_sources = load_sources()
    
    click.echo(f"\n{'='*70}")
    click.echo("CONFIGURED SOURCES")
    click.echo('='*70)
    
    for src in all_sources:
        status = "✓" if src.active else "○"
        click.echo(f"\n{status} {src.id}")
        click.echo(f"  Name: {src.name}")
        click.echo(f"  Type: {src.source_type}")
        click.echo(f"  URL:  {src.url}")
        click.echo(f"  Since: {src.fetch_since}")
        if src.primary_domains:
            click.echo(f"  Domains: {', '.join(src.primary_domains)}")


@cli.command()
@click.option('--id', 'content_id', help='Process a specific content item by ID')
@click.option('--all', 'process_all', is_flag=True, help='Process all pending items')
@click.option('--limit', '-n', type=int, default=None, help='Maximum items to process')
@click.option('--provider', type=click.Choice(['auto', 'gemini', 'openai']), default='auto',
              help='LLM provider: auto (Gemini + OpenAI fallback), gemini, or openai')
@click.option('--delay', type=int, default=0, help='Delay in seconds between API calls (helps with rate limits)')
@click.pass_context
def process(ctx, content_id, process_all, limit, provider, delay):
    """
    Process pending content through LLM for summarization.

    Uses Gemini by default with automatic OpenAI fallback on rate limits.

    Examples:
        python -m src.cli process --all
        python -m src.cli process --all --provider openai
        python -m src.cli process --all --limit 5 --delay 20
    """
    db = ctx.obj['db']

    if not content_id and not process_all:
        click.echo("Error: Specify --id or --all", err=True)
        sys.exit(1)

    try:
        client = LLMClient(provider=provider)
        click.echo(f"  LLM provider: {provider} (active: {client.model_name})")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    summarizer = Summarizer(db=db, client=client)

    if content_id:
        # Process a single item
        item = db.get_content(content_id)
        if not item:
            click.echo(f"Content not found: {content_id}", err=True)
            sys.exit(1)

        click.echo(f"\nProcessing: {item.title}")
        result = summarizer.process_item(item)

        if result:
            click.echo(f"\n  {result.tier_emoji} Tier: {result.tier}")
            click.echo(f"  Domains: {', '.join(result.domains)}")
            click.echo(f"  Freshness: {result.freshness}")
            click.echo(f"  Category: {result.content_category}")
            click.echo(f"\n  Summary: {result.core_summary[:200]}...")
            if result.key_insights:
                click.echo(f"\n  Key Insights:")
                for insight in result.key_insights[:3]:
                    click.echo(f"    - {insight[:100]}")
        else:
            click.echo("  Processing failed.")
    else:
        # Process all pending
        click.echo(f"\nProcessing pending content (provider: {provider}, delay: {delay}s)...")
        stats = summarizer.process_pending(limit=limit, delay=delay)
        click.echo(f"\n{'='*50}")
        click.echo(f"RESULTS")
        click.echo(f"  Processed: {stats['processed']}")
        click.echo(f"  Failed:    {stats['failed']}")
        click.echo(f"  Skipped:   {stats['skipped']}")
        click.echo(f"  Total:     {stats['total']}")
        click.echo('='*50)


@cli.command()
@click.option('--date', 'briefing_date', type=click.DateTime(formats=['%Y-%m-%d']),
              help='Date for the briefing (YYYY-MM-DD, defaults to today)')
@click.option('--preview', is_flag=True, help='Preview in browser without sending email')
@click.option('--save-html', is_flag=True, help='Save HTML to data/ directory')
@click.pass_context
def compose(ctx, briefing_date, preview, save_html):
    """
    Compose a daily briefing from processed content.

    Examples:
        python -m src.cli compose --preview
        python -m src.cli compose --date 2025-02-15 --save-html
    """
    db = ctx.obj['db']
    composer = BriefingComposer(db)

    target_date = briefing_date.date() if briefing_date else date.today()

    click.echo(f"\nComposing briefing for {target_date}...")
    briefing = composer.compose(target_date)

    if briefing.total_count == 0:
        click.echo("No content available for briefing. Fetch and process content first.")
        return

    items = composer.get_briefing_items(briefing)

    # Display summary
    click.echo(f"\n{'='*50}")
    click.echo(f"BRIEFING: {target_date}")
    click.echo(f"  Total:   {briefing.total_count} items")
    click.echo(f"  Fresh:   {briefing.fresh_count}")
    click.echo(f"  Backlog: {briefing.backlog_count}")
    click.echo(f"{'='*50}")

    for item in items:
        c = item["content"]
        p = item["processed"]
        backlog_tag = " [backlog]" if p.is_backlog else ""
        click.echo(f"  {p.tier_emoji} {c.title[:55]}{backlog_tag}")
        click.echo(f"     {c.source_name} | {', '.join(p.domains)}")

    if save_html or preview:
        emailer = Emailer.__new__(Emailer)  # Skip __init__ validation
        progress = db.get_backlog_progress()
        progress_dict = None
        if progress:
            progress_dict = {
                "total_items": progress.total_items,
                "delivered_items": progress.delivered_items,
                "percent_complete": progress.percent_complete,
            }

        path = f"data/briefing_{target_date}.html"
        from src.briefing.emailer import generate_briefing_html
        html = generate_briefing_html(briefing, items, progress_dict)

        os.makedirs("data", exist_ok=True)
        with open(path, "w") as f:
            f.write(html)
        click.echo(f"\n  HTML saved to: {path}")

        if preview:
            import webbrowser
            webbrowser.open(f"file://{os.path.abspath(path)}")
            click.echo("  Opened in browser.")

    click.echo(f"\n  (Use 'send-briefing' to send email and mark items delivered)")


@cli.command('send-briefing')
@click.option('--date', 'briefing_date', type=click.DateTime(formats=['%Y-%m-%d']),
              help='Date for the briefing (YYYY-MM-DD, defaults to today)')
@click.option('--no-email', is_flag=True, help='Skip sending email (just save and mark delivered)')
@click.pass_context
def send_briefing(ctx, briefing_date, no_email):
    """
    Compose, send, and save the daily briefing.

    Examples:
        python -m src.cli send-briefing
        python -m src.cli send-briefing --date 2025-02-15
        python -m src.cli send-briefing --no-email
    """
    db = ctx.obj['db']
    composer = BriefingComposer(db)

    target_date = briefing_date.date() if briefing_date else date.today()

    click.echo(f"\nComposing briefing for {target_date}...")
    briefing = composer.compose(target_date)

    if briefing.total_count == 0:
        click.echo("No content available for briefing.")
        return

    items = composer.get_briefing_items(briefing)

    click.echo(f"  {briefing.total_count} items ({briefing.fresh_count} fresh, {briefing.backlog_count} backlog)")

    # Get backlog progress for the email
    progress = db.get_backlog_progress()
    progress_dict = None
    if progress:
        progress_dict = {
            "total_items": progress.total_items,
            "delivered_items": progress.delivered_items,
            "percent_complete": progress.percent_complete,
        }

    # Gather footer stats
    footer_stats = {
        "briefing_count": db.get_briefing_count() + 1,  # +1 for this briefing (not saved yet)
        "total_delivered": db.get_total_items_delivered() + briefing.total_count,
    }

    # Generate editorial intro via LLM (non-fatal if it fails)
    editorial_intro = None
    if items:
        click.echo("\n  Generating editorial intro...")
        try:
            from src.processors.prompts import build_editorial_intro_prompt

            intro_client = LLMClient(provider="auto")
            item_summaries = [
                {
                    "title": item["content"].title,
                    "core_summary": item["processed"].core_summary,
                    "domains": item["processed"].domains,
                }
                for item in items
            ]
            intro_prompt = build_editorial_intro_prompt(item_summaries)
            result = intro_client.generate(intro_prompt)
            if result and isinstance(result, dict):
                editorial_intro = result.get("editorial_intro", "")
                if editorial_intro:
                    click.echo(f"  Editorial intro: {editorial_intro[:80]}...")
                else:
                    click.echo("  Editorial intro: empty response")
        except Exception as e:
            click.echo(f"  Editorial intro generation failed (non-fatal): {e}")

    email_sent = False
    if not no_email:
        click.echo("\nSending email...")
        try:
            emailer = Emailer()
            email_sent = emailer.send_briefing(briefing, items, progress_dict, footer_stats, editorial_intro)
        except ValueError as e:
            click.echo(f"  Email config error: {e}", err=True)
            click.echo("  Continuing without email...")

        # Save HTML backup regardless
        from src.briefing.emailer import generate_briefing_html
        email_html = generate_briefing_html(briefing, items, progress_dict, footer_stats, editorial_intro)
        backup_path = f"data/briefing_{target_date}.html"
        os.makedirs("data", exist_ok=True)
        with open(backup_path, "w") as f:
            f.write(email_html)
        click.echo(f"  HTML backup saved: {backup_path}")

    # Update briefing with email status and save
    if email_sent:
        briefing.email_sent = True
        briefing.email_sent_at = datetime.now()

    composer.save_and_deliver(briefing)
    click.echo(f"\n  Briefing saved. {briefing.total_count} items marked as delivered.")

    if email_sent:
        click.echo(f"  Email sent to: {os.getenv('EMAIL_TO', 'unknown')}")
    elif not no_email:
        click.echo("  Email was NOT sent (check config).")


@cli.command()
@click.pass_context
def init_db(ctx):
    """Initialize the database (creates tables if needed)."""
    db = ctx.obj['db']
    click.echo(f"Database initialized at: {db.db_path}")
    click.echo("Tables created successfully.")


@cli.command('enrich-durations')
@click.pass_context
def enrich_durations(ctx):
    """
    Backfill missing video durations using yt-dlp.

    Queries all video items with NULL duration_seconds and
    fetches the duration via yt-dlp metadata extraction.
    """
    import yt_dlp

    db = ctx.obj['db']
    cursor = db.conn.cursor()
    cursor.execute(
        "SELECT id, url, title FROM content_items "
        "WHERE content_type = 'video' AND duration_seconds IS NULL"
    )
    rows = cursor.fetchall()

    click.echo(f"\nFound {len(rows)} videos missing duration.")
    if not rows:
        return

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'socket_timeout': 10,
    }

    updated = 0
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for row in rows:
            content_id = row['id']
            url = row['url']
            title = row['title'][:50]

            try:
                info = ydl.extract_info(url, download=False)
                duration = info.get('duration')
                if duration:
                    duration = int(duration)
                    db.update_content_duration(content_id, duration)
                    mins = duration // 60
                    click.echo(f"  ✓ {title} → {mins}m")
                    updated += 1
                else:
                    click.echo(f"  ○ {title} → no duration available")
            except Exception as e:
                click.echo(f"  ✗ {title} → {e}")

    click.echo(f"\nUpdated {updated}/{len(rows)} videos.")


@cli.command('retry-transcripts')
@click.option('--source', '-s', help='Only retry for a specific source ID')
@click.option('--limit', '-n', type=int, default=None, help='Maximum items to retry')
@click.option('--delay', type=float, default=3.0, help='Seconds between transcript fetches (default 3)')
@click.pass_context
def retry_transcripts(ctx, source, limit, delay):
    """
    Retry fetching transcripts for items missing transcripts.

    Handles both 'no_transcript' status items and 'pending' items with
    null/empty transcripts (e.g., from a --no-transcripts dry run).

    Examples:
        python -m src.cli retry-transcripts
        python -m src.cli retry-transcripts --source bg2-pod --delay 5
        python -m src.cli retry-transcripts --limit 10
    """
    import time as _time

    db = ctx.obj['db']
    cursor = db.conn.cursor()

    # Query items missing transcripts: no_transcript status OR pending with null/empty transcript
    if source:
        cursor.execute(
            """SELECT * FROM content_items
               WHERE (status = 'no_transcript' OR (status = 'pending' AND (transcript IS NULL OR transcript = '')))
               AND source_id = ?
               ORDER BY published_at DESC""",
            (source,)
        )
    else:
        cursor.execute(
            """SELECT * FROM content_items
               WHERE status = 'no_transcript' OR (status = 'pending' AND (transcript IS NULL OR transcript = ''))
               ORDER BY source_id, published_at DESC"""
        )

    rows = cursor.fetchall()
    if limit:
        rows = rows[:limit]

    if not rows:
        click.echo("No items with no_transcript status found.")
        return

    click.echo(f"\nFound {len(rows)} items to retry (delay: {delay}s between fetches)")

    # Group by source for fetcher reuse
    from collections import defaultdict
    by_source = defaultdict(list)
    for row in rows:
        item = db._row_to_content_item(row)
        by_source[item.source_id].append(item)

    total_recovered = 0
    total_failed = 0

    for source_id, items in by_source.items():
        click.echo(f"\n{'='*50}")
        click.echo(f"Source: {source_id} ({len(items)} items)")
        click.echo('='*50)

        # Get the fetcher for this source
        try:
            src = get_source_by_id(source_id)
            fetcher = get_fetcher(src)
        except (SystemExit, ValueError) as e:
            click.echo(f"  Could not create fetcher for {source_id}: {e}")
            total_failed += len(items)
            continue

        for i, item in enumerate(items):
            if i > 0 and delay > 0:
                _time.sleep(delay)

            click.echo(f"  Retrying: {item.title[:55]}...", nl=False)

            try:
                transcript = fetcher.fetch_transcript(item)
                if transcript:
                    word_count = len(transcript.split())
                    db.update_content_status(item.id, "pending", transcript)
                    click.echo(f" OK ({word_count:,} words)")
                    total_recovered += 1
                else:
                    click.echo(f" FAILED (no transcript returned)")
                    total_failed += 1
            except Exception as e:
                click.echo(f" ERROR: {e}")
                total_failed += 1

    click.echo(f"\n{'='*50}")
    click.echo(f"RESULTS")
    click.echo(f"  Recovered: {total_recovered}")
    click.echo(f"  Still failed: {total_failed}")
    click.echo(f"  Total attempted: {total_recovered + total_failed}")
    click.echo('='*50)

    if total_recovered > 0:
        click.echo(f"\n  {total_recovered} items now have status 'pending' and can be processed.")
        click.echo("  Run: python -m src.cli process --all --delay 5")


if __name__ == '__main__':
    cli()
