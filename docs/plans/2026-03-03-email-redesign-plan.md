# Email Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign the daily briefing email to remove the headline index, combine header with editorial intro, create three visually distinct card layouts per tier, surface content type and concepts_explained, reframe BACKLOG as Evergreen, and improve prompt quality.

**Architecture:** All changes are in `src/briefing/emailer.py` (HTML template), `src/processors/prompts.py` (LLM prompts), and a new test file. The composition logic (`composer.py`), data models (`models.py`), and delivery logic (`Emailer` class) are unchanged.

**Tech Stack:** Python, inline HTML/CSS (email-safe), pytest for structural validation.

**Design doc:** `docs/plans/2026-03-03-email-redesign-design.md`

---

### Task 1: Add structural tests for the new email layout

**Files:**
- Create: `tests/test_emailer.py`

We need tests that validate the HTML structure of the redesigned email. These tests use mock data to generate HTML and check for expected patterns.

**Step 1: Create test file with mock data fixtures and structural assertions**

```python
"""Tests for email HTML generation."""
from __future__ import annotations

import pytest
from datetime import datetime, date
from src.storage.models import (
    ContentItem, ProcessedContent, ConceptExplanation, DailyBriefing
)
from src.briefing.emailer import generate_briefing_html


def _make_content(id="test1", source_id="dwarkesh-patel", source_name="Dwarkesh Patel",
                  content_type="video", title="Test Interview Title",
                  url="https://youtube.com/watch?v=test1", word_count=15000,
                  duration_seconds=4620, published_at=None):
    return ContentItem(
        id=id, source_id=source_id, source_name=source_name,
        content_type=content_type, title=title, url=url,
        published_at=published_at or datetime(2026, 3, 2),
        fetched_at=datetime.now(), duration_seconds=duration_seconds,
        word_count=word_count, status="processed",
    )


def _make_processed(content_id="test1", tier="deep_dive", content_category="interview",
                    is_backlog=False, concepts=None, domains=None):
    return ProcessedContent(
        content_id=content_id,
        core_summary="This is a test summary with sharp insights about AI.",
        key_insights=["Insight one about markets.", "Insight two about strategy.", "Insight three about tech."],
        concepts_explained=concepts or [],
        so_what="Stop building without AI. The window closes in 12 months.",
        domains=domains or ["vibe-coding", "GPU-capex"],
        content_category=content_category,
        freshness="fresh",
        tier=tier,
        tier_rationale="Test rationale.",
        source_id="dwarkesh-patel",
        is_backlog=is_backlog,
    )


def _make_briefing(item_ids=None, total_count=5):
    return DailyBriefing(
        id="test-briefing",
        briefing_date=date(2026, 3, 3),
        created_at=datetime.now(),
        fresh_count=3, backlog_count=2, total_count=total_count,
        item_ids=item_ids or ["test1"],
    )


def _make_item(id="test1", tier="deep_dive", content_category="interview",
               is_backlog=False, concepts=None, domains=None, title="Test Title",
               content_type="video", duration_seconds=4620, word_count=15000):
    return {
        "content": _make_content(id=id, title=title, content_type=content_type,
                                  duration_seconds=duration_seconds, word_count=word_count),
        "processed": _make_processed(content_id=id, tier=tier,
                                      content_category=content_category,
                                      is_backlog=is_backlog, concepts=concepts,
                                      domains=domains),
    }


class TestHeadlineIndexRemoved:
    """The headline index table should NOT appear in the redesigned email."""

    def test_no_headline_table(self):
        items = [_make_item()]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "<table" not in html

    def test_editorial_intro_in_header_card(self):
        items = [_make_item()]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items, editorial_intro="Sharp take on today.")
        # Editorial intro should appear in the output
        assert "Sharp take on today." in html


class TestTierCardDifferentiation:
    """Each tier should render with distinct visual treatment."""

    def test_deep_dive_has_pink_background(self):
        items = [_make_item(tier="deep_dive")]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "#fef7f7" in html  # pink background

    def test_deep_dive_has_red_border(self):
        items = [_make_item(tier="deep_dive")]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "#ef4444" in html  # red border

    def test_deep_dive_shows_3_insights(self):
        items = [_make_item(tier="deep_dive")]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert html.count("<li") == 3

    def test_deep_dive_has_so_what_box(self):
        items = [_make_item(tier="deep_dive")]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "So what:" in html
        assert "#eff6ff" in html  # blue box background

    def test_worth_a_look_has_yellow_border(self):
        items = [_make_item(tier="worth_a_look")]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "#eab308" in html  # yellow border

    def test_worth_a_look_shows_2_insights(self):
        items = [_make_item(tier="worth_a_look")]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert html.count("<li") == 2

    def test_worth_a_look_has_inline_take_not_box(self):
        items = [_make_item(tier="worth_a_look")]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "Take:" in html
        assert "#eff6ff" not in html  # should NOT have the blue box

    def test_summary_sufficient_no_summary_text(self):
        items = [_make_item(tier="summary_sufficient")]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        # The core_summary text should NOT appear for summary_sufficient
        assert "test summary with sharp insights" not in html

    def test_summary_sufficient_has_take_only(self):
        items = [_make_item(tier="summary_sufficient")]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "Take:" in html

    def test_summary_sufficient_no_insights(self):
        items = [_make_item(tier="summary_sufficient")]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "<li" not in html

    def test_summary_sufficient_no_link(self):
        items = [_make_item(tier="summary_sufficient")]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        # Should not have Watch/Read action links
        assert "Watch" not in html or "Watch (" not in html


class TestContentTypeBadge:
    """Content type should be surfaced in the meta line."""

    def test_deep_dive_shows_content_type(self):
        items = [_make_item(tier="deep_dive", content_category="interview")]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "Interview" in html

    def test_worth_a_look_shows_content_type(self):
        items = [_make_item(tier="worth_a_look", content_category="market_call")]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "Market Call" in html


class TestConceptsExplained:
    """Concepts should be surfaced in Deep Dive cards only."""

    def test_deep_dive_shows_concepts(self):
        concepts = [ConceptExplanation(term="Vibe coding", explanation="Building software by describing what you want.")]
        items = [_make_item(tier="deep_dive", concepts=concepts)]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "Vibe coding" in html
        assert "Building software by describing" in html

    def test_worth_a_look_hides_concepts(self):
        concepts = [ConceptExplanation(term="Vibe coding", explanation="Building software by describing what you want.")]
        items = [_make_item(tier="worth_a_look", concepts=concepts)]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "Vibe coding" not in html


class TestBacklogBadge:
    """Backlog items should show 'Evergreen' badge, not 'BACKLOG'."""

    def test_backlog_shows_evergreen_not_backlog(self):
        items = [_make_item(tier="worth_a_look", is_backlog=True)]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "Evergreen" in html
        assert "BACKLOG" not in html

    def test_non_backlog_has_no_badge(self):
        items = [_make_item(tier="worth_a_look", is_backlog=False)]
        briefing = _make_briefing()
        html = generate_briefing_html(briefing, items)
        assert "Evergreen" not in html
        assert "BACKLOG" not in html
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/sukritandvandana/Documents/Projects/daily-briefing-tool/.claude/worktrees/email-redesign && source venv/bin/activate && python -m pytest tests/test_emailer.py -v`
Expected: Multiple FAIL (headline table still exists, cards not differentiated, etc.)

**Step 3: Commit test file**

```bash
git add tests/test_emailer.py
git commit -m "test: add structural tests for email redesign"
```

---

### Task 2: Add content type label helper and update backlog badge

**Files:**
- Modify: `src/briefing/emailer.py:86-128` (helper functions area)

**Step 1: Add `_content_type_label` function after `_action_link`**

Add this function at line ~95 (after `_action_link`):

```python
# Maps LLM content_category values to human-readable labels
_CONTENT_TYPE_LABELS = {
    "interview": "Interview",
    "market_call": "Market Call",
    "news_analysis": "Analysis",
    "industry_trend": "Trend",
    "framework": "Framework",
    "tutorial": "Tutorial",
    "commentary": "Commentary",
}


def _content_type_label(content_category: str) -> str:
    """Get human-readable label for content type."""
    return _CONTENT_TYPE_LABELS.get(content_category, "")
```

**Step 2: Add `_concepts_html` function**

Add after the new content type helper:

```python
def _concepts_html(concepts: list) -> str:
    """Generate HTML for concepts_explained (Deep Dive only)."""
    if not concepts:
        return ""
    items_html = ""
    for c in concepts[:2]:  # Max 2 concepts
        items_html += f'<p style="margin:4px 0;font-size:13px;color:#334155;line-height:1.4;"><strong>{c.term}:</strong> {c.explanation}</p>'
    return f'<div style="margin-top:8px;padding:8px 10px;background:#f8fafc;border-radius:6px;">{items_html}</div>'
```

**Step 3: Update `_so_what_inline` — change BACKLOG badge references (search-replace later in Task 3)**

No changes to `_so_what_inline` itself — it's already correct for the new WaL treatment.

**Step 4: Commit**

```bash
git add src/briefing/emailer.py
git commit -m "feat: add content type labels and concepts HTML helpers"
```

---

### Task 3: Rewrite `generate_briefing_html` — remove headline index, combine header + editorial intro

**Files:**
- Modify: `src/briefing/emailer.py:131-311` (the main `generate_briefing_html` function)

**Step 1: Replace the entire `generate_briefing_html` function**

The new version:
- Removes the headline index table (lines 158-190)
- Moves editorial intro into the header card (after badges, before detail cards)
- Passes `accent_border="#eab308"` for worth_a_look section
- Keeps the same signature and return type

Key changes:
1. Delete lines 158-190 (headline_rows loop and table)
2. Move `editorial_html` into the header card div (after badges_html)
3. Remove `{headline_rows}` table from the HTML template
4. Pass yellow accent border to worth_a_look section

**Step 2: Replace BACKLOG badge with Evergreen badge globally**

In `_build_tier_section` (line 342-343), change:
```python
# OLD:
meta += ' <span style="color:#dc2626;font-size:11px;font-weight:600;background:#fef2f2;padding:1px 5px;border-radius:3px;">BACKLOG</span>'
# NEW:
meta += ' <span style="color:#0d9488;font-size:11px;font-weight:600;background:#f0fdfa;padding:1px 5px;border-radius:3px;">Evergreen</span>'
```

**Step 3: Commit**

```bash
git add src/briefing/emailer.py
git commit -m "feat: remove headline index, combine header + editorial intro"
```

---

### Task 4: Rewrite `_build_tier_section` with three distinct card layouts

**Files:**
- Modify: `src/briefing/emailer.py:314-431` (the `_build_tier_section` function)

This is the biggest change. The three layouts:

**Deep Dive (detail_level="full"):**
- Pink background + 4px red left border (keep)
- Title: 16px bold (was 15px)
- Content type badge in meta line
- Topic tag pills
- Summary: 3 sentences
- Key insights: 3 bullets
- So what: blue box (`_so_what_box`)
- Concepts explained (NEW)
- Action link

**Worth a Look (detail_level="medium"):**
- White background + 3px yellow left border (NEW)
- Title: 15px medium
- Content type badge in meta line (subtle)
- Topic tag pills
- Summary: 2 sentences
- Key insights: 2 bullets (was 3)
- So what: inline take (`_so_what_inline`) — NOT the blue box
- Action link

**Summary Sufficient (detail_level="compact"):**
- No section wrapper card (just items with thin dividers)
- Title: 14px, muted color (#334155), no link
- Meta: source + date only
- No summary, no insights
- So what: inline take only
- No action link

**Step 1: Rewrite the function with three distinct branches**

The key structural changes:
- `detail_level="full"`: Add `_content_type_label()` to meta, add `_concepts_html()` after insights, title font to 16px
- `detail_level="medium"`: Add yellow border to section wrapper, slice insights to `[:2]`, use `_so_what_inline()` instead of `_so_what_box()`, add content type to meta
- `detail_level="compact"`: Completely new layout — section wrapper has no card styling (thin background), items are minimal: title (no link, muted color) + source/date + inline take only

**Step 2: Run tests**

Run: `cd /Users/sukritandvandana/Documents/Projects/daily-briefing-tool/.claude/worktrees/email-redesign && source venv/bin/activate && python -m pytest tests/test_emailer.py -v`
Expected: Most tests PASS

**Step 3: Fix any remaining test failures**

**Step 4: Commit**

```bash
git add src/briefing/emailer.py
git commit -m "feat: three distinct card layouts per tier"
```

---

### Task 5: Update prompts — so_what variety, editorial intro quality, topic tag specificity

**Files:**
- Modify: `src/processors/prompts.py`

**Step 1: Add "This reshapes how..." to so_what banned patterns**

In `build_summarization_prompt`, add to the SO_WHAT VARIETY section (around line 147-148):

```
- BANNED PATTERN: "This reshapes how [X] works because..." — overused. Use a different structure.
- BANNED PATTERN: "This signals a shift in..." — too generic. Be specific about WHAT shifts and WHO is affected.
```

**Step 2: Improve editorial intro prompt with negative example**

In `build_editorial_intro_prompt`, add after the existing rules:

```
- NEVER write motivational-poster synthesis like "The AI era isn't just about X; it's a relentless exercise in Y." That's LinkedIn, not Matt Levine.
- GOOD example: "Three items today about agents eating SaaS, and one about why they shouldn't — the tension is the story."
- BAD example: "Today's stories reveal a singular truth: the old ways of thinking are not just outdated, but actively detrimental in an AI-powered world."
- Reference a specific item or tension. Don't abstract.
```

**Step 3: Add topic tag negative examples**

In the TOPIC_TAGS section (around line 161), add:

```
   ALSO BAD (still too generic): "design-evolution", "ai-integration", "workforce-evolution", "engineering-collaboration"
   These read like database categories. Be specific: "Claude-design-team", "designer-to-engineer", "mockup-death"
```

**Step 4: Bump PROMPT_VERSION to v5.1**

Change line 11: `PROMPT_VERSION = "v5.1"`

**Step 5: Commit**

```bash
git add src/processors/prompts.py
git commit -m "feat: improve so_what variety, editorial intro, and topic tag prompts (v5.1)"
```

---

### Task 6: Visual verification — generate test HTML and preview

**Files:**
- No new files. Uses existing `compose --save-html` or manual HTML generation.

**Step 1: Generate a test briefing HTML using mock data**

Create a one-off script to generate sample HTML with all three tiers:

```bash
cd /Users/sukritandvandana/Documents/Projects/daily-briefing-tool/.claude/worktrees/email-redesign
source venv/bin/activate
python -c "
from src.briefing.emailer import generate_briefing_html
from src.storage.models import *
from datetime import datetime, date

# Build mock items covering all tiers
items = [
    {'content': ContentItem(id='dd1', source_id='dwarkesh-patel', source_name='Dwarkesh Patel', content_type='video', title='Jensen Huang on the Future of Compute', url='https://youtube.com/watch?v=dd1', published_at=datetime(2026,3,3), fetched_at=datetime.now(), duration_seconds=4620, word_count=19000, status='processed'),
     'processed': ProcessedContent(content_id='dd1', core_summary='Three-hour interview. Huang argues compute will be 100x cheaper in 5 years. The capex cycle is just starting.', key_insights=['NVIDIA is building inference-optimized chips', 'Sovereign AI spending is the next growth lever', 'Open source models need 10x more compute'], concepts_explained=[ConceptExplanation('Sovereign AI', 'Governments building their own AI infrastructure')], so_what='The real play here is NVDA at these multiples.', domains=['GPU-capex', 'NVDA', 'sovereign-AI'], content_category='interview', tier='deep_dive', source_id='dwarkesh-patel')},
    {'content': ContentItem(id='wal1', source_id='20vc', source_name='20VC with Harry Stebbings', content_type='video', title='The SaaS Apocalypse', url='https://youtube.com/watch?v=wal1', published_at=datetime(2026,3,3), fetched_at=datetime.now(), duration_seconds=3600, word_count=12000, status='processed'),
     'processed': ProcessedContent(content_id='wal1', core_summary='Autonomous agents will fundamentally change how software is bought. The buyer shifts from humans to probabilistic AI employees.', key_insights=['Agent-native development makes Cursor obsolete', 'Open-source agent stack emerging fast', 'Agents will orchestrate multiple LLMs dynamically'], so_what='Stop building for humans. Start building for agents. 12-month window before the market shifts.', domains=['SaaS-commoditization', 'agent-stack'], content_category='market_call', tier='worth_a_look', source_id='20vc')},
    {'content': ContentItem(id='wal2', source_id='stratechery', source_name='Stratechery', content_type='article', title='Apple Vision Pro Content Strategy', url='https://stratechery.com/test', published_at=datetime(2026,2,1), fetched_at=datetime.now(), word_count=2000, status='processed'),
     'processed': ProcessedContent(content_id='wal2', core_summary='Apple is producing immersive video like traditional TV, destroying the devices unique ability to create presence.', key_insights=['Too many camera cuts disorient VR viewers', 'Fixed camera replicates courtside experience'], so_what='Everyone thinks VR needs more production. Actually it needs less.', domains=['vision-pro', 'XR-content'], content_category='commentary', tier='worth_a_look', source_id='stratechery', is_backlog=True)},
    {'content': ContentItem(id='ss1', source_id='nate-b-jones', source_name='Nate B Jones', content_type='video', title='AI Skills You Learned 6 Months Ago Are Wrong', url='https://youtube.com/watch?v=ss1', published_at=datetime(2026,3,3), fetched_at=datetime.now(), duration_seconds=1680, word_count=4000, status='processed'),
     'processed': ProcessedContent(content_id='ss1', core_summary='Short rehash of frontier operations concept.', key_insights=['Skills expire quarterly'], so_what='Nothing new here. The frontier ops framing is catchy but the advice is generic.', domains=['ai-skills'], content_category='commentary', tier='summary_sufficient', source_id='nate-b-jones')},
    {'content': ContentItem(id='ss2', source_id='y-combinator', source_name='Y Combinator', content_type='video', title='How to Talk to Users', url='https://youtube.com/watch?v=ss2', published_at=datetime(2026,3,2), fetched_at=datetime.now(), duration_seconds=900, word_count=2000, status='processed'),
     'processed': ProcessedContent(content_id='ss2', core_summary='Standard YC advice on customer discovery.', key_insights=['Talk to users early'], so_what='If youve read The Mom Test, skip this.', domains=['customer-discovery'], content_category='tutorial', tier='summary_sufficient', source_id='y-combinator')},
]

briefing = DailyBriefing(id='test', briefing_date=date(2026,3,3), created_at=datetime.now(), fresh_count=3, backlog_count=2, total_count=5, item_ids=[i['processed'].content_id for i in items])

html = generate_briefing_html(briefing, items, editorial_intro='Three items about agents eating SaaS, one about why Apple still doesn\'t get VR, and Dwarkesh got Jensen for three hours — that last one alone is worth your morning.')
with open('data/test_redesign.html', 'w') as f:
    f.write(html)
print('Saved to data/test_redesign.html')
"
```

**Step 2: Open in browser and verify visually**

Run: `open data/test_redesign.html`

Check:
- [ ] No headline index table
- [ ] Header shows date + count + badges + editorial intro
- [ ] Deep Dive card: pink bg, red border, 16px title, 3 insights, blue so_what box, concepts shown, content type badge
- [ ] Worth a Look cards: white bg, yellow left border, 2 insights, inline take (not box), content type badge
- [ ] Summary Sufficient: compact list, no summary text, just title + take, no links
- [ ] Backlog item shows "Evergreen" teal badge, not red "BACKLOG"
- [ ] Overall visual rhythm has three distinct densities

**Step 3: Run full test suite**

Run: `python -m pytest tests/test_emailer.py -v`
Expected: ALL PASS

**Step 4: Commit all remaining changes**

```bash
git add -A
git commit -m "feat: email redesign complete — visual verification passed"
```

---

### Task 7: Update CLAUDE.md and documentation

**Files:**
- Modify: `CLAUDE.md` (update email structure docs, version history)

**Step 1:** Update the "Email Structure" section in CLAUDE.md to reflect the new layout (no headline index, three distinct card types).

**Step 2:** Add V16 to version history table.

**Step 3:** Update PROMPT_VERSION reference to v5.1.

**Step 4:** Commit

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for email redesign (V16)"
```
