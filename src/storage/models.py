from __future__ import annotations

"""
Data models for the Daily Briefing Tool.

These dataclasses define the structure of all data in the system.
They're used both for in-memory operations and as the schema reference for SQLite.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional
import hashlib
import json


@dataclass
class ContentItem:
    """
    Raw content fetched from a source (before LLM processing).
    
    This represents a single video, article, or post from any source.
    The `id` is a hash of source_id + url to ensure uniqueness.
    """
    id: str                         # Unique ID (hash of source_id + url)
    source_id: str                  # e.g., "dwarkesh-patel"
    source_name: str                # e.g., "Dwarkesh Patel"
    content_type: str               # "video" | "article"
    title: str
    url: str
    published_at: datetime
    fetched_at: datetime
    duration_seconds: Optional[int] = None  # For videos
    transcript: Optional[str] = None        # Full transcript/article text
    word_count: int = 0
    status: str = "pending"         # "pending" | "processed" | "failed" | "skipped" | "no_transcript"
    
    @staticmethod
    def generate_id(source_id: str, url: str) -> str:
        """Generate a unique ID from source and URL."""
        raw = f"{source_id}:{url}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "content_type": self.content_type,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at.isoformat(),
            "fetched_at": self.fetched_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "transcript": self.transcript,
            "word_count": self.word_count,
            "status": self.status,
        }


@dataclass
class ConceptExplanation:
    """A technical concept with its accessible explanation."""
    term: str
    explanation: str


@dataclass
class ProcessedContent:
    """
    Content after LLM processing - summarized, tagged, and scored.
    
    This is the enriched version of ContentItem, containing the summary,
    domain tags, freshness assessment, and consumption recommendation.
    """
    content_id: str                 # FK to ContentItem.id

    # Summary components
    core_summary: str               # 3-5 sentences
    key_insights: list[str] = field(default_factory=list)
    concepts_explained: list[ConceptExplanation] = field(default_factory=list)
    so_what: str = ""               # Implications for reader
    
    # Classification
    domains: list[str] = field(default_factory=list)  # ["finance", "ai", "startups", "strategy"]
    content_category: str = ""      # "market_call" | "news_analysis" | "framework" | etc.
    freshness: str = "fresh"        # "fresh" | "evergreen" | "stale"
    
    # Recommendation
    tier: str = "summary_sufficient"  # "deep_dive" | "worth_a_look" | "summary_sufficient"
    tier_rationale: str = ""
    
    # Metadata
    processed_at: datetime = field(default_factory=datetime.now)
    prompt_version: str = "v1.0"
    model_used: str = "gemini-3-flash"
    
    # Source tracking (populated from content_items join for diversity enforcement)
    source_id: str = ""

    # Backlog tracking
    is_backlog: bool = False        # True if from historical fetch
    delivered: bool = False         # True if included in a briefing
    delivered_at: Optional[datetime] = None
    
    @property
    def tier_emoji(self) -> str:
        """Get emoji for the tier."""
        return {
            "deep_dive": "🔴",
            "worth_a_look": "🟡",
            "summary_sufficient": "🟢"
        }.get(self.tier, "⚪")
    
    @property
    def tier_priority(self) -> int:
        """Get numeric priority for sorting (lower = higher priority)."""
        return {
            "deep_dive": 1,
            "worth_a_look": 2,
            "summary_sufficient": 3
        }.get(self.tier, 99)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "content_id": self.content_id,
            "core_summary": self.core_summary,
            "key_insights": self.key_insights,
            "concepts_explained": [
                {"term": c.term, "explanation": c.explanation}
                for c in self.concepts_explained
            ],
            "so_what": self.so_what,
            "domains": self.domains,
            "content_category": self.content_category,
            "freshness": self.freshness,
            "tier": self.tier,
            "tier_rationale": self.tier_rationale,
            "processed_at": self.processed_at.isoformat(),
            "prompt_version": self.prompt_version,
            "model_used": self.model_used,
            "is_backlog": self.is_backlog,
            "delivered": self.delivered,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
        }


@dataclass
class DailyBriefing:
    """
    A daily briefing - the curated set of content for a specific day.
    """
    id: str
    briefing_date: date
    created_at: datetime
    
    # Content breakdown
    fresh_count: int = 0
    backlog_count: int = 0
    total_count: int = 0
    
    # Items (content_ids in display order)
    item_ids: list[str] = field(default_factory=list)
    
    # Delivery status
    email_sent: bool = False
    email_sent_at: Optional[datetime] = None
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "briefing_date": self.briefing_date.isoformat(),
            "created_at": self.created_at.isoformat(),
            "fresh_count": self.fresh_count,
            "backlog_count": self.backlog_count,
            "total_count": self.total_count,
            "item_ids": self.item_ids,
            "email_sent": self.email_sent,
            "email_sent_at": self.email_sent_at.isoformat() if self.email_sent_at else None,
        }


@dataclass
class Feedback:
    """
    User feedback on a summary quality.
    """
    id: str
    content_id: str
    flagged_at: datetime
    reason: str                     # "too_shallow" | "missed_point" | "technical_unclear" | "wrong_tier" | "other"
    note: Optional[str] = None      # Optional free-text
    original_summary: str = ""      # Snapshot of summary at flag time
    prompt_version: str = ""
    
    VALID_REASONS = [
        "too_shallow",
        "missed_point", 
        "technical_unclear",
        "wrong_tier",
        "other"
    ]
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content_id": self.content_id,
            "flagged_at": self.flagged_at.isoformat(),
            "reason": self.reason,
            "note": self.note,
            "original_summary": self.original_summary,
            "prompt_version": self.prompt_version,
        }


@dataclass
class BacklogProgress:
    """
    Tracks progress through the historical backlog.
    """
    total_items: int                # Fixed on day 1
    delivered_items: int            # Increments as backlog surfaces
    last_updated: datetime
    
    @property
    def percent_complete(self) -> float:
        if self.total_items == 0:
            return 100.0
        return round((self.delivered_items / self.total_items) * 100, 1)
    
    @property
    def items_remaining(self) -> int:
        return self.total_items - self.delivered_items
    
    def estimated_completion(self, daily_rate: float = 3.0) -> Optional[date]:
        """Estimate completion date based on average daily delivery rate."""
        if self.items_remaining <= 0:
            return date.today()
        days_remaining = int(self.items_remaining / daily_rate)
        from datetime import timedelta
        return date.today() + timedelta(days=days_remaining)


@dataclass 
class Source:
    """
    A content source (YouTube channel, RSS feed, etc.).
    Loaded from config/sources.yaml.
    """
    id: str
    name: str
    source_type: str                # "youtube_channel" | "rss" | "twitter"
    url: str                        # channel_url or feed_url
    fetch_since: date
    active: bool = True
    notes: str = ""
    primary_domains: list[str] = field(default_factory=list)
    
    @classmethod
    def from_yaml(cls, data: dict) -> "Source":
        """Create Source from YAML config entry."""
        return cls(
            id=data["id"],
            name=data["name"],
            source_type=data["type"],
            url=data.get("channel_url") or data.get("feed_url", ""),
            fetch_since=datetime.strptime(data["fetch_since"], "%Y-%m-%d").date(),
            active=data.get("active", True),
            notes=data.get("notes", ""),
            primary_domains=data.get("primary_domains", []),
        )
