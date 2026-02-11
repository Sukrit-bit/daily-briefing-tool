from __future__ import annotations

"""
Database module for the Daily Briefing Tool.

Uses SQLite for simple, file-based persistence.
All data operations go through this module.
"""

import sqlite3
import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional
import os

from .models import (
    ContentItem, 
    ProcessedContent, 
    ConceptExplanation,
    DailyBriefing, 
    Feedback,
    BacklogProgress
)


class Database:
    """
    SQLite database handler for the Daily Briefing Tool.
    
    Usage:
        db = Database("./data/briefing.db")
        db.save_content(content_item)
        items = db.get_pending_content()
    """
    
    def __init__(self, db_path: str = None):
        """Initialize database connection."""
        if db_path is None:
            db_path = os.getenv("DATABASE_PATH", "./data/briefing.db")
        
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row  # Enable column access by name
        
        self._create_tables()
    
    def _create_tables(self):
        """Create all tables if they don't exist."""
        cursor = self.conn.cursor()
        
        # Content items (raw fetched content)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS content_items (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                content_type TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                published_at TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                duration_seconds INTEGER,
                transcript TEXT,
                word_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending'
            )
        """)
        
        # Processed content (after LLM)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_content (
                content_id TEXT PRIMARY KEY,
                core_summary TEXT NOT NULL,
                key_insights TEXT NOT NULL,
                concepts_explained TEXT NOT NULL,
                so_what TEXT,
                domains TEXT NOT NULL,
                content_category TEXT,
                freshness TEXT DEFAULT 'fresh',
                tier TEXT DEFAULT 'summary_sufficient',
                tier_rationale TEXT,
                processed_at TEXT NOT NULL,
                prompt_version TEXT,
                model_used TEXT,
                is_backlog INTEGER DEFAULT 0,
                delivered INTEGER DEFAULT 0,
                delivered_at TEXT,
                FOREIGN KEY (content_id) REFERENCES content_items(id)
            )
        """)
        
        # Daily briefings
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_briefings (
                id TEXT PRIMARY KEY,
                briefing_date TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                fresh_count INTEGER DEFAULT 0,
                backlog_count INTEGER DEFAULT 0,
                total_count INTEGER DEFAULT 0,
                item_ids TEXT NOT NULL,
                email_sent INTEGER DEFAULT 0,
                email_sent_at TEXT
            )
        """)
        
        # Feedback
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                content_id TEXT NOT NULL,
                flagged_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                note TEXT,
                original_summary TEXT,
                prompt_version TEXT,
                FOREIGN KEY (content_id) REFERENCES content_items(id)
            )
        """)
        
        # Backlog progress (single row table)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backlog_progress (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                total_items INTEGER DEFAULT 0,
                delivered_items INTEGER DEFAULT 0,
                last_updated TEXT NOT NULL
            )
        """)
        
        # Create indexes for common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_content_status ON content_items(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_content_source ON content_items(source_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_content_published ON content_items(published_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_processed_delivered ON processed_content(delivered)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_processed_tier ON processed_content(tier)")
        
        self.conn.commit()
    
    def close(self):
        """Close database connection."""
        self.conn.close()
    
    # =========================================
    # CONTENT ITEMS
    # =========================================
    
    def save_content(self, item: ContentItem) -> bool:
        """
        Save a content item. Returns True if inserted, False if already exists.
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO content_items 
                (id, source_id, source_name, content_type, title, url, 
                 published_at, fetched_at, duration_seconds, transcript, word_count, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.id,
                item.source_id,
                item.source_name,
                item.content_type,
                item.title,
                item.url,
                item.published_at.isoformat(),
                item.fetched_at.isoformat(),
                item.duration_seconds,
                item.transcript,
                item.word_count,
                item.status,
            ))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Already exists (duplicate URL)
            return False
    
    def update_content_status(self, content_id: str, status: str, transcript: str = None):
        """Update the status (and optionally transcript) of a content item."""
        cursor = self.conn.cursor()
        if transcript is not None:
            cursor.execute("""
                UPDATE content_items 
                SET status = ?, transcript = ?, word_count = ?
                WHERE id = ?
            """, (status, transcript, len(transcript.split()) if transcript else 0, content_id))
        else:
            cursor.execute("""
                UPDATE content_items SET status = ? WHERE id = ?
            """, (status, content_id))
        self.conn.commit()
    
    def get_content(self, content_id: str) -> Optional[ContentItem]:
        """Get a content item by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM content_items WHERE id = ?", (content_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_content_item(row)
        return None
    
    def get_content_by_url(self, url: str) -> Optional[ContentItem]:
        """Get a content item by URL."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM content_items WHERE url = ?", (url,))
        row = cursor.fetchone()
        if row:
            return self._row_to_content_item(row)
        return None
    
    def get_pending_content(self, limit: int = None) -> list[ContentItem]:
        """Get all content items with status='pending'."""
        cursor = self.conn.cursor()
        query = "SELECT * FROM content_items WHERE status = 'pending' ORDER BY published_at DESC"
        if limit:
            query += f" LIMIT {limit}"
        cursor.execute(query)
        return [self._row_to_content_item(row) for row in cursor.fetchall()]
    
    def get_content_by_source(self, source_id: str, since: date = None) -> list[ContentItem]:
        """Get all content items from a specific source."""
        cursor = self.conn.cursor()
        if since:
            cursor.execute("""
                SELECT * FROM content_items 
                WHERE source_id = ? AND published_at >= ?
                ORDER BY published_at DESC
            """, (source_id, since.isoformat()))
        else:
            cursor.execute("""
                SELECT * FROM content_items WHERE source_id = ? ORDER BY published_at DESC
            """, (source_id,))
        return [self._row_to_content_item(row) for row in cursor.fetchall()]
    
    def count_content_by_status(self) -> dict:
        """Get count of content items by status."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT status, COUNT(*) as count 
            FROM content_items 
            GROUP BY status
        """)
        return {row["status"]: row["count"] for row in cursor.fetchall()}
    
    def _row_to_content_item(self, row) -> ContentItem:
        """Convert a database row to ContentItem."""
        return ContentItem(
            id=row["id"],
            source_id=row["source_id"],
            source_name=row["source_name"],
            content_type=row["content_type"],
            title=row["title"],
            url=row["url"],
            published_at=datetime.fromisoformat(row["published_at"]),
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            duration_seconds=row["duration_seconds"],
            transcript=row["transcript"],
            word_count=row["word_count"] or 0,
            status=row["status"],
        )
    
    # =========================================
    # PROCESSED CONTENT
    # =========================================
    
    def save_processed(self, processed: ProcessedContent):
        """Save processed content."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO processed_content
            (content_id, core_summary, key_insights, concepts_explained, so_what,
             domains, content_category, freshness, tier, tier_rationale,
             processed_at, prompt_version, model_used, is_backlog, delivered, delivered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            processed.content_id,
            processed.core_summary,
            json.dumps(processed.key_insights),
            json.dumps([{"term": c.term, "explanation": c.explanation} for c in processed.concepts_explained]),
            processed.so_what,
            json.dumps(processed.domains),
            processed.content_category,
            processed.freshness,
            processed.tier,
            processed.tier_rationale,
            processed.processed_at.isoformat(),
            processed.prompt_version,
            processed.model_used,
            1 if processed.is_backlog else 0,
            1 if processed.delivered else 0,
            processed.delivered_at.isoformat() if processed.delivered_at else None,
        ))
        self.conn.commit()
    
    def get_processed(self, content_id: str) -> Optional[ProcessedContent]:
        """Get processed content by content_id."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM processed_content WHERE content_id = ?", (content_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_processed(row)
        return None
    
    def get_undelivered_fresh(self, max_age_weeks: int = 6) -> list[ProcessedContent]:
        """Get fresh content that hasn't been delivered yet."""
        cursor = self.conn.cursor()
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(weeks=max_age_weeks)).isoformat()

        cursor.execute("""
            SELECT p.*, c.source_id FROM processed_content p
            JOIN content_items c ON p.content_id = c.id
            WHERE p.delivered = 0
            AND p.is_backlog = 0
            AND p.freshness != 'stale'
            AND c.published_at >= ?
            ORDER BY
                CASE p.tier
                    WHEN 'deep_dive' THEN 1
                    WHEN 'worth_a_look' THEN 2
                    ELSE 3
                END,
                c.published_at DESC
        """, (cutoff,))
        return [self._row_to_processed(row) for row in cursor.fetchall()]
    
    def get_undelivered_backlog(self, limit: int = 10) -> list[ProcessedContent]:
        """Get backlog content that hasn't been delivered yet (priority-first)."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT p.*, c.source_id FROM processed_content p
            JOIN content_items c ON p.content_id = c.id
            WHERE p.delivered = 0
            AND p.is_backlog = 1
            AND p.freshness = 'evergreen'
            ORDER BY
                CASE p.tier
                    WHEN 'deep_dive' THEN 1
                    WHEN 'worth_a_look' THEN 2
                    ELSE 3
                END,
                c.published_at DESC
            LIMIT ?
        """, (limit,))
        return [self._row_to_processed(row) for row in cursor.fetchall()]
    
    def mark_delivered(self, content_ids: list[str], delivered_at: datetime = None):
        """Mark content items as delivered."""
        if not content_ids:
            return
        if delivered_at is None:
            delivered_at = datetime.now()
        
        cursor = self.conn.cursor()
        placeholders = ",".join("?" * len(content_ids))
        cursor.execute(f"""
            UPDATE processed_content 
            SET delivered = 1, delivered_at = ?
            WHERE content_id IN ({placeholders})
        """, [delivered_at.isoformat()] + content_ids)
        self.conn.commit()
    
    def _row_to_processed(self, row) -> ProcessedContent:
        """Convert a database row to ProcessedContent."""
        concepts_data = json.loads(row["concepts_explained"]) if row["concepts_explained"] else []
        concepts = [ConceptExplanation(term=c["term"], explanation=c["explanation"]) for c in concepts_data]

        # source_id is available when we JOIN with content_items
        source_id = ""
        try:
            source_id = row["source_id"] or ""
        except (IndexError, KeyError):
            pass

        return ProcessedContent(
            content_id=row["content_id"],
            source_id=source_id,
            core_summary=row["core_summary"],
            key_insights=json.loads(row["key_insights"]) if row["key_insights"] else [],
            concepts_explained=concepts,
            so_what=row["so_what"] or "",
            domains=json.loads(row["domains"]) if row["domains"] else [],
            content_category=row["content_category"] or "",
            freshness=row["freshness"] or "fresh",
            tier=row["tier"] or "summary_sufficient",
            tier_rationale=row["tier_rationale"] or "",
            processed_at=datetime.fromisoformat(row["processed_at"]),
            prompt_version=row["prompt_version"] or "",
            model_used=row["model_used"] or "",
            is_backlog=bool(row["is_backlog"]),
            delivered=bool(row["delivered"]),
            delivered_at=datetime.fromisoformat(row["delivered_at"]) if row["delivered_at"] else None,
        )
    
    # =========================================
    # DAILY BRIEFINGS
    # =========================================
    
    def save_briefing(self, briefing: DailyBriefing):
        """Save a daily briefing."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO daily_briefings
            (id, briefing_date, created_at, fresh_count, backlog_count, total_count,
             item_ids, email_sent, email_sent_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            briefing.id,
            briefing.briefing_date.isoformat(),
            briefing.created_at.isoformat(),
            briefing.fresh_count,
            briefing.backlog_count,
            briefing.total_count,
            json.dumps(briefing.item_ids),
            1 if briefing.email_sent else 0,
            briefing.email_sent_at.isoformat() if briefing.email_sent_at else None,
        ))
        self.conn.commit()
    
    def get_briefing(self, briefing_date: date) -> Optional[DailyBriefing]:
        """Get briefing for a specific date."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM daily_briefings WHERE briefing_date = ?", 
            (briefing_date.isoformat(),)
        )
        row = cursor.fetchone()
        if row:
            return self._row_to_briefing(row)
        return None
    
    def _row_to_briefing(self, row) -> DailyBriefing:
        """Convert a database row to DailyBriefing."""
        return DailyBriefing(
            id=row["id"],
            briefing_date=date.fromisoformat(row["briefing_date"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            fresh_count=row["fresh_count"],
            backlog_count=row["backlog_count"],
            total_count=row["total_count"],
            item_ids=json.loads(row["item_ids"]) if row["item_ids"] else [],
            email_sent=bool(row["email_sent"]),
            email_sent_at=datetime.fromisoformat(row["email_sent_at"]) if row["email_sent_at"] else None,
        )
    
    # =========================================
    # FEEDBACK
    # =========================================
    
    def save_feedback(self, feedback: Feedback):
        """Save user feedback."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO feedback
            (id, content_id, flagged_at, reason, note, original_summary, prompt_version)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            feedback.id,
            feedback.content_id,
            feedback.flagged_at.isoformat(),
            feedback.reason,
            feedback.note,
            feedback.original_summary,
            feedback.prompt_version,
        ))
        self.conn.commit()
    
    def get_feedback_stats(self) -> dict:
        """Get feedback statistics by reason."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT reason, COUNT(*) as count 
            FROM feedback 
            GROUP BY reason
        """)
        return {row["reason"]: row["count"] for row in cursor.fetchall()}
    
    # =========================================
    # BACKLOG PROGRESS
    # =========================================
    
    def init_backlog_progress(self, total_items: int):
        """Initialize backlog progress tracking (run once on first backfill)."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO backlog_progress (id, total_items, delivered_items, last_updated)
            VALUES (1, ?, 0, ?)
        """, (total_items, datetime.now().isoformat()))
        self.conn.commit()
    
    def update_backlog_progress(self, delivered_increment: int = 0):
        """Update backlog progress."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE backlog_progress 
            SET delivered_items = delivered_items + ?, last_updated = ?
            WHERE id = 1
        """, (delivered_increment, datetime.now().isoformat()))
        self.conn.commit()
    
    def get_backlog_progress(self) -> Optional[BacklogProgress]:
        """Get current backlog progress."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM backlog_progress WHERE id = 1")
        row = cursor.fetchone()
        if row:
            return BacklogProgress(
                total_items=row["total_items"],
                delivered_items=row["delivered_items"],
                last_updated=datetime.fromisoformat(row["last_updated"]),
            )
        return None
    
    # =========================================
    # STATS (for email footer)
    # =========================================

    def get_briefing_count(self) -> int:
        """Get total number of briefings composed."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM daily_briefings")
        row = cursor.fetchone()
        return row["cnt"] if row else 0

    def get_total_items_delivered(self) -> int:
        """Get total number of items that have been delivered in briefings."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM processed_content WHERE delivered = 1")
        row = cursor.fetchone()
        return row["cnt"] if row else 0

    def update_processed_tier(self, content_id: str, tier: str):
        """Update tier for a processed content item (used by composer caps)."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE processed_content SET tier = ? WHERE content_id = ?",
            (tier, content_id),
        )
        self.conn.commit()

    def update_content_duration(self, content_id: str, duration_seconds: int):
        """Update duration_seconds for a content item (backfill support)."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE content_items SET duration_seconds = ? WHERE id = ?",
            (duration_seconds, content_id),
        )
        self.conn.commit()

    # =========================================
    # UTILITY
    # =========================================
    
    def get_full_content_with_processed(self, content_id: str) -> Optional[tuple[ContentItem, ProcessedContent]]:
        """Get both content item and its processed data."""
        content = self.get_content(content_id)
        if not content:
            return None
        processed = self.get_processed(content_id)
        return (content, processed) if processed else None
