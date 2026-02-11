"""
Briefing composition logic.

Selects items for the daily briefing by mixing fresh content
with backlog items, respecting the daily cap and tier priorities.
"""

import hashlib
from datetime import date, datetime
from typing import Optional

from ..storage.database import Database
from ..storage.models import DailyBriefing, ProcessedContent


class BriefingComposer:
    """
    Composes the daily briefing by selecting and ordering content.

    Selection logic:
    - Fresh content (not backlog, not stale, published within 6 weeks)
    - Backlog content (evergreen only, priority-ordered)
    - Mix: 50-70% fresh, 30-50% backlog depending on volume
    - Hard cap at 18 items, soft target of 15
    """

    MAX_ITEMS = 18
    TARGET_ITEMS = 15
    MAX_DEEP_DIVES = 3  # Hard ceiling — when everything is special, nothing is

    def __init__(self, db: Database):
        self.db = db

    def compose(self, briefing_date: date = None) -> DailyBriefing:
        """
        Compose a daily briefing for the given date.

        Args:
            briefing_date: Date for the briefing (defaults to today)

        Returns:
            DailyBriefing with selected and ordered items
        """
        if briefing_date is None:
            briefing_date = date.today()

        # Check if briefing already exists for this date
        existing = self.db.get_briefing(briefing_date)
        if existing:
            return existing

        # 1. Get fresh content pool
        fresh_pool = self.db.get_undelivered_fresh(max_age_weeks=6)

        # 2. Determine backlog allocation based on fresh volume
        fresh_count = len(fresh_pool)
        if fresh_count <= 3:
            backlog_target = 8      # Light day: heavy backlog
        elif fresh_count <= 6:
            backlog_target = 5      # Normal day
        elif fresh_count <= 9:
            backlog_target = 3      # Heavy day
        else:
            backlog_target = 2      # Very heavy day: minimum backlog

        # 3. Get backlog items (priority-first)
        backlog_pool = self.db.get_undelivered_backlog(limit=backlog_target)

        # 4. Combine, enforce source diversity, cap deep dives, then cap total
        all_items = fresh_pool + backlog_pool
        all_items = self._enforce_source_diversity(all_items)
        all_items = self._cap_deep_dives(all_items)

        if len(all_items) > self.MAX_ITEMS:
            all_items = self._prioritize_and_cap(all_items, self.MAX_ITEMS)

        # 5. Order for display: by tier, then fresh before backlog within tier
        ordered = self._order_for_display(all_items)

        # 6. Build the briefing
        fresh_selected = [i for i in ordered if not i.is_backlog]
        backlog_selected = [i for i in ordered if i.is_backlog]

        briefing_id = hashlib.sha256(
            f"briefing:{briefing_date.isoformat()}".encode()
        ).hexdigest()[:16]

        briefing = DailyBriefing(
            id=briefing_id,
            briefing_date=briefing_date,
            created_at=datetime.now(),
            fresh_count=len(fresh_selected),
            backlog_count=len(backlog_selected),
            total_count=len(ordered),
            item_ids=[i.content_id for i in ordered],
            email_sent=False,
            email_sent_at=None,
        )

        return briefing

    def save_and_deliver(self, briefing: DailyBriefing):
        """
        Save the briefing and mark all its items as delivered.

        Call this after the briefing has been composed and
        (optionally) the email has been sent.
        """
        self.db.save_briefing(briefing)
        self.db.mark_delivered(briefing.item_ids)

        # Update backlog progress
        backlog_count = briefing.backlog_count
        if backlog_count > 0:
            self.db.update_backlog_progress(delivered_increment=backlog_count)

    def get_briefing_items(self, briefing: DailyBriefing) -> list[dict]:
        """
        Get full item data for a briefing (content + processed joined).

        Returns a list of dicts with both ContentItem and ProcessedContent fields,
        in the briefing's display order.
        """
        items = []
        for content_id in briefing.item_ids:
            result = self.db.get_full_content_with_processed(content_id)
            if result:
                content, processed = result
                items.append({
                    "content": content,
                    "processed": processed,
                })
        return items

    # Source diversity: max items per source (soft cap)
    MAX_PER_SOURCE = 2
    MAX_PER_SOURCE_WITH_DEEP_DIVE = 3  # Allow a 3rd if it's deep_dive

    def _enforce_source_diversity(
        self, items: list[ProcessedContent]
    ) -> list[ProcessedContent]:
        """
        Enforce per-source item caps to ensure briefing diversity.

        Rules:
        - Max 2 items per source by default
        - Allow a 3rd item from a source only if it's rated deep_dive
        - Overflow items stay undelivered for future briefings
        """
        from collections import defaultdict

        # Group by source_id
        by_source = defaultdict(list)
        for item in items:
            by_source[item.source_id].append(item)

        kept = []
        for source_id, source_items in by_source.items():
            # Sort by tier priority (deep_dive first)
            source_items.sort(key=lambda i: i.tier_priority)

            for i, item in enumerate(source_items):
                if i < self.MAX_PER_SOURCE:
                    kept.append(item)
                elif i < self.MAX_PER_SOURCE_WITH_DEEP_DIVE and item.tier == "deep_dive":
                    kept.append(item)
                # else: overflow — stays undelivered for next day

        return kept

    def _cap_deep_dives(
        self, items: list[ProcessedContent]
    ) -> list[ProcessedContent]:
        """
        Enforce a hard ceiling on deep_dive items.

        When more than MAX_DEEP_DIVES items are rated deep_dive,
        demote the excess to worth_a_look (keeping the highest-quality ones).
        Quality proxy: word count from the content_items table.
        Demotions are persisted to the DB so get_briefing_items reads correct tiers.
        """
        deep = [i for i in items if i.tier == "deep_dive"]
        rest = [i for i in items if i.tier != "deep_dive"]

        if len(deep) <= self.MAX_DEEP_DIVES:
            return items

        # Sort deep dives by word count (longest = highest quality, keep those)
        # Fetch word counts from content_items table
        word_counts = {}
        for item in deep:
            row = self.db.conn.execute(
                "SELECT word_count FROM content_items WHERE id = ?",
                (item.content_id,)
            ).fetchone()
            word_counts[item.content_id] = row["word_count"] if row else 0

        deep.sort(key=lambda i: -word_counts.get(i.content_id, 0))

        kept_deep = deep[:self.MAX_DEEP_DIVES]
        demoted = deep[self.MAX_DEEP_DIVES:]

        # Demote excess to worth_a_look — both in-memory AND in DB
        for item in demoted:
            item.tier = "worth_a_look"
            self.db.update_processed_tier(item.content_id, "worth_a_look")

        return kept_deep + rest + demoted

    def _prioritize_and_cap(
        self, items: list[ProcessedContent], cap: int
    ) -> list[ProcessedContent]:
        """
        When over the cap, keep items by tier priority.
        deep_dive first, then worth_a_look, then summary_sufficient.
        """
        items.sort(key=lambda i: i.tier_priority)
        return items[:cap]

    def _order_for_display(
        self, items: list[ProcessedContent]
    ) -> list[ProcessedContent]:
        """
        Order items for display in the briefing:
        1. Group by tier (deep_dive, worth_a_look, summary_sufficient)
        2. Within each tier, interleave sources so the same source never appears back-to-back
        3. Fresh items before backlog within source-interleaved order
        """
        from collections import defaultdict

        # Group by tier
        tier_groups = defaultdict(list)
        for item in items:
            tier_groups[item.tier].append(item)

        # Within each tier, interleave sources
        result = []
        for tier in ["deep_dive", "worth_a_look", "summary_sufficient"]:
            tier_items = tier_groups.get(tier, [])
            if not tier_items:
                continue

            # Sort within tier: fresh first, then by source for grouping
            tier_items.sort(key=lambda i: (0 if not i.is_backlog else 1))

            # Interleave: round-robin by source to avoid clustering
            by_source = defaultdict(list)
            for item in tier_items:
                by_source[item.source_id].append(item)

            # Sort sources by count (most items first) for fair distribution
            source_queues = sorted(by_source.values(), key=lambda q: -len(q))

            interleaved = []
            while any(source_queues):
                next_round = []
                for queue in source_queues:
                    if queue:
                        interleaved.append(queue.pop(0))
                    if queue:  # still has items
                        next_round.append(queue)
                source_queues = next_round

            result.extend(interleaved)

        return result
