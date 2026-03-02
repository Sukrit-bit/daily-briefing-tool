"""
Tests for the redesigned email template in emailer.py.

These tests validate HTML structure and content for three distinct tier layouts,
content type badges, concepts_explained display, and the Evergreen badge.
"""
from __future__ import annotations

from datetime import datetime, date

import pytest

from src.briefing.emailer import generate_briefing_html
from src.storage.models import ContentItem, ProcessedContent, ConceptExplanation, DailyBriefing


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_content(
    id: str = "test1",
    source_id: str = "dwarkesh-patel",
    source_name: str = "Dwarkesh Patel",
    content_type: str = "video",
    title: str = "Test Deep Dive Title",
    url: str = "https://youtube.com/watch?v=test1",
    duration_seconds: int = 4620,
    word_count: int = 15000,
) -> ContentItem:
    return ContentItem(
        id=id,
        source_id=source_id,
        source_name=source_name,
        content_type=content_type,
        title=title,
        url=url,
        published_at=datetime(2026, 3, 2),
        fetched_at=datetime.now(),
        duration_seconds=duration_seconds,
        word_count=word_count,
        status="processed",
    )


def _make_processed(
    content_id: str = "test1",
    tier: str = "deep_dive",
    core_summary: str = "This is a deep dive summary sentence one. Sentence two here. And sentence three.",
    key_insights: list[str] | None = None,
    concepts_explained: list[ConceptExplanation] | None = None,
    so_what: str = "This matters because it changes the landscape.",
    content_category: str = "interview",
    source_id: str = "dwarkesh-patel",
    is_backlog: bool = False,
    domains: list[str] | None = None,
) -> ProcessedContent:
    if key_insights is None:
        key_insights = [
            "Insight number one about the topic",
            "Insight number two with details",
            "Insight number three wrapping up",
        ]
    if concepts_explained is None:
        concepts_explained = [
            ConceptExplanation(term="Scaling Laws", explanation="How model performance improves with data and compute."),
        ]
    if domains is None:
        domains = ["AI", "scaling"]
    return ProcessedContent(
        content_id=content_id,
        core_summary=core_summary,
        key_insights=key_insights,
        concepts_explained=concepts_explained,
        so_what=so_what,
        domains=domains,
        content_category=content_category,
        tier=tier,
        source_id=source_id,
        is_backlog=is_backlog,
    )


def _make_briefing(total_count: int = 5, item_ids: list[str] | None = None) -> DailyBriefing:
    if item_ids is None:
        item_ids = ["test1"]
    return DailyBriefing(
        id="test-briefing",
        briefing_date=date(2026, 3, 3),
        created_at=datetime.now(),
        fresh_count=3,
        backlog_count=2,
        total_count=total_count,
        item_ids=item_ids,
    )


def _build_items(
    content_overrides: dict | None = None,
    processed_overrides: dict | None = None,
) -> list[dict]:
    """Build a single-item list with optional overrides."""
    c_kwargs = content_overrides or {}
    p_kwargs = processed_overrides or {}
    return [{"content": _make_content(**c_kwargs), "processed": _make_processed(**p_kwargs)}]


def _html_with_all_tiers(editorial_intro: str | None = None) -> str:
    """Generate HTML containing one item per tier for multi-tier tests."""
    items = [
        {
            "content": _make_content(id="dd1", title="Deep Dive Article"),
            "processed": _make_processed(
                content_id="dd1",
                tier="deep_dive",
                content_category="interview",
                core_summary="Deep summary one. Deep summary two. Deep summary three.",
                key_insights=["DD insight 1", "DD insight 2", "DD insight 3"],
                concepts_explained=[
                    ConceptExplanation(term="Scaling Laws", explanation="Performance scales with compute."),
                ],
            ),
        },
        {
            "content": _make_content(id="wal1", title="Worth a Look Article", url="https://youtube.com/watch?v=wal1"),
            "processed": _make_processed(
                content_id="wal1",
                tier="worth_a_look",
                content_category="market_call",
                core_summary="WAL summary one. WAL summary two.",
                key_insights=["WAL insight 1", "WAL insight 2", "WAL insight 3"],
                concepts_explained=[
                    ConceptExplanation(term="Should Not Appear", explanation="This concept should be hidden."),
                ],
            ),
        },
        {
            "content": _make_content(id="ss1", title="Summary Sufficient Article", url="https://youtube.com/watch?v=ss1"),
            "processed": _make_processed(
                content_id="ss1",
                tier="summary_sufficient",
                core_summary="SS summary that should not appear in the output.",
                key_insights=["SS insight 1"],
                so_what="Quick take on the summary sufficient item.",
            ),
        },
    ]
    briefing = _make_briefing(total_count=3, item_ids=["dd1", "wal1", "ss1"])
    return generate_briefing_html(briefing, items, editorial_intro=editorial_intro)


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestHeadlineIndexRemoved:
    """Test 1: No headline index table in output."""

    def test_no_table_tag(self):
        html = _html_with_all_tiers()
        assert "<table" not in html


class TestEditorialIntro:
    """Test 2: Editorial intro text appears when provided."""

    def test_editorial_intro_present(self):
        html = _html_with_all_tiers(editorial_intro="Today we cover scaling and markets.")
        assert "Today we cover scaling and markets." in html

    def test_no_editorial_intro_when_empty(self):
        html = _html_with_all_tiers(editorial_intro=None)
        assert "border-left:3px solid #6366f1" not in html


class TestDeepDiveCard:
    """Test 3: Deep Dive card structure — pink bg, red border, 3 insights, blue so_what box."""

    def test_pink_background(self):
        html = _html_with_all_tiers()
        assert "#fef7f7" in html

    def test_red_border(self):
        html = _html_with_all_tiers()
        assert "#ef4444" in html

    def test_three_insight_bullets(self):
        items = _build_items()
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        # Count <li items within the deep dive section
        assert html.count("<li") == 3

    def test_so_what_blue_box(self):
        html = _html_with_all_tiers()
        assert "So what:" in html
        assert "#eff6ff" in html


class TestWorthALookCard:
    """Test 4: Worth a Look card — yellow border, 2 insights, inline take, no blue box."""

    def test_yellow_border(self):
        html = _html_with_all_tiers()
        assert "#eab308" in html

    def test_two_insight_bullets(self):
        items = [
            {
                "content": _make_content(id="wal1"),
                "processed": _make_processed(
                    content_id="wal1",
                    tier="worth_a_look",
                    key_insights=["Insight A", "Insight B", "Insight C"],
                ),
            },
        ]
        briefing = _make_briefing(total_count=1, item_ids=["wal1"])
        html = generate_briefing_html(briefing, items)
        # Should only have 2 <li items (capped at 2)
        assert html.count("<li") == 2

    def test_inline_take_present(self):
        items = [
            {
                "content": _make_content(id="wal1"),
                "processed": _make_processed(content_id="wal1", tier="worth_a_look"),
            },
        ]
        briefing = _make_briefing(total_count=1, item_ids=["wal1"])
        html = generate_briefing_html(briefing, items)
        assert "Take:" in html

    def test_no_blue_so_what_box(self):
        items = [
            {
                "content": _make_content(id="wal1"),
                "processed": _make_processed(content_id="wal1", tier="worth_a_look"),
            },
        ]
        briefing = _make_briefing(total_count=1, item_ids=["wal1"])
        html = generate_briefing_html(briefing, items)
        assert "#eff6ff" not in html


class TestSummarySufficientCard:
    """Test 5: Summary Sufficient — no summary text, has Take, no insights, no link."""

    def test_no_core_summary(self):
        items = [
            {
                "content": _make_content(id="ss1"),
                "processed": _make_processed(
                    content_id="ss1",
                    tier="summary_sufficient",
                    core_summary="SS summary that should not appear in the output.",
                ),
            },
        ]
        briefing = _make_briefing(total_count=1, item_ids=["ss1"])
        html = generate_briefing_html(briefing, items)
        assert "SS summary that should not appear in the output." not in html

    def test_has_inline_take(self):
        items = [
            {
                "content": _make_content(id="ss1"),
                "processed": _make_processed(
                    content_id="ss1",
                    tier="summary_sufficient",
                    so_what="Quick take on this topic.",
                ),
            },
        ]
        briefing = _make_briefing(total_count=1, item_ids=["ss1"])
        html = generate_briefing_html(briefing, items)
        assert "Take:" in html

    def test_no_insight_bullets(self):
        items = [
            {
                "content": _make_content(id="ss1"),
                "processed": _make_processed(content_id="ss1", tier="summary_sufficient"),
            },
        ]
        briefing = _make_briefing(total_count=1, item_ids=["ss1"])
        html = generate_briefing_html(briefing, items)
        assert "<li" not in html

    def test_no_watch_read_link(self):
        items = [
            {
                "content": _make_content(id="ss1"),
                "processed": _make_processed(content_id="ss1", tier="summary_sufficient"),
            },
        ]
        briefing = _make_briefing(total_count=1, item_ids=["ss1"])
        html = generate_briefing_html(briefing, items)
        assert "Watch" not in html
        assert "Read" not in html
        # Also ensure no action link arrow
        assert "&rarr;" not in html


class TestContentTypeLabels:
    """Tests 6-7: Content type labels appear in meta line."""

    def test_interview_label_deep_dive(self):
        items = _build_items(processed_overrides={"content_category": "interview", "tier": "deep_dive"})
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "Interview" in html

    def test_market_call_label_worth_a_look(self):
        items = [
            {
                "content": _make_content(id="wal1"),
                "processed": _make_processed(
                    content_id="wal1",
                    tier="worth_a_look",
                    content_category="market_call",
                ),
            },
        ]
        briefing = _make_briefing(total_count=1, item_ids=["wal1"])
        html = generate_briefing_html(briefing, items)
        assert "Market Call" in html


class TestConceptsExplained:
    """Tests 8-9: Concepts shown for Deep Dive, hidden for Worth a Look."""

    def test_deep_dive_shows_concepts(self):
        html = _html_with_all_tiers()
        assert "Scaling Laws" in html

    def test_worth_a_look_hides_concepts(self):
        items = [
            {
                "content": _make_content(id="wal1"),
                "processed": _make_processed(
                    content_id="wal1",
                    tier="worth_a_look",
                    concepts_explained=[
                        ConceptExplanation(term="HiddenConcept", explanation="Should not appear"),
                    ],
                ),
            },
        ]
        briefing = _make_briefing(total_count=1, item_ids=["wal1"])
        html = generate_briefing_html(briefing, items)
        assert "HiddenConcept" not in html


class TestEvergreenBadge:
    """Test 10: Backlog items show 'Evergreen' not 'BACKLOG'."""

    def test_evergreen_badge_shown(self):
        items = _build_items(processed_overrides={"is_backlog": True})
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "Evergreen" in html
        assert "BACKLOG" not in html

    def test_evergreen_badge_teal_color(self):
        items = _build_items(processed_overrides={"is_backlog": True})
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "#0d9488" in html
        assert "#f0fdfa" in html
