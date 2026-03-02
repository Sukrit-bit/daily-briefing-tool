"""Generate a test HTML email with mock data covering all three tiers.

Usage:
    python scripts/build_test_email.py
    # Opens data/test_email_redesign.html in browser
"""
from __future__ import annotations

import sys
import os
import webbrowser
from datetime import datetime, date, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.storage.models import ContentItem, ProcessedContent, DailyBriefing, ConceptExplanation
from src.briefing.emailer import generate_briefing_html

# ── Mock Data ──────────────────────────────────────────────────────

now = datetime.now()
today = date.today()

# 2 Deep Dives
dd1_content = ContentItem(
    id="dd1", source_id="dwarkesh-patel", source_name="Dwarkesh Patel",
    content_type="video", title="Dario Amodei: Scaling, Alignment, and the Future of Anthropic",
    url="https://youtube.com/watch?v=example1",
    published_at=now - timedelta(days=1), fetched_at=now,
    duration_seconds=5940, word_count=22000, status="processed",
)
dd1_processed = ProcessedContent(
    content_id="dd1",
    core_summary="Amodei makes the clearest public case yet that scaling laws haven't hit a wall — Anthropic's internal benchmarks show capability gains accelerating, not plateauing. The real bottleneck isn't compute but evaluation: we can't measure what matters fast enough.",
    key_insights=[
        "Constitutional AI now handles 93% of safety cases that previously required human review.",
        "Anthropic's enterprise revenue grew 8x in 6 months — mostly from replacing internal tools, not chatbots.",
        "The 'alignment tax' (performance cost of safety) has dropped from 15% to under 3% in 18 months.",
    ],
    concepts_explained=[
        ConceptExplanation("Constitutional AI", "Training an AI to follow rules by having another AI critique its outputs — like having an editor review every draft before publication."),
        ConceptExplanation("Alignment Tax", "The performance penalty you pay for making AI safe. Like adding seatbelts to a race car — it slows you down, but the cost keeps shrinking."),
    ],
    so_what="MSFT and GOOG are spending $50B+/yr on AI infra assuming scaling works. Amodei just told you it does — but the real alpha is in evaluation tooling, not model training. Watch companies building AI benchmarks.",
    domains=["scaling-laws", "Anthropic", "alignment"],
    content_category="interview",
    freshness="fresh",
    tier="deep_dive",
    tier_rationale="22K-word interview with the CEO of Anthropic — 3 non-obvious claims backed by internal data.",
    source_id="dwarkesh-patel",
    is_backlog=False,
)

dd2_content = ContentItem(
    id="dd2", source_id="lennys-podcast", source_name="Lenny's Podcast",
    content_type="video", title="How Figma Rebuilt Their Entire Product Around AI — with Dylan Field",
    url="https://youtube.com/watch?v=example2",
    published_at=now - timedelta(days=2), fetched_at=now,
    duration_seconds=4500, word_count=18500, status="processed",
)
dd2_processed = ProcessedContent(
    content_id="dd2",
    core_summary="Dylan Field reveals Figma scrapped 6 months of AI features that tested well in isolation but created cognitive overload when combined. The surviving feature — AI-generated component variants — now accounts for 28% of all new components created on the platform.",
    key_insights=[
        "Figma killed their AI auto-layout feature despite 72% approval in user testing — it broke designer intuition.",
        "The 'AI tax' on design tools: users spend 30% more time reviewing AI suggestions than they save.",
        "Component variants generation succeeded because it fits existing workflows — designers already think in variants.",
    ],
    concepts_explained=[
        ConceptExplanation("AI Tax", "The hidden cost of reviewing and correcting AI output. Like having a fast but sloppy assistant — you save time on drafting but spend it on quality control."),
    ],
    so_what="Every SaaS company bolting AI onto existing workflows should study Figma's kill list. The pattern: AI features that require new mental models fail; AI features that accelerate existing habits win. $FGMA is the case study.",
    domains=["Figma", "AI-UX", "design-tools"],
    content_category="interview",
    freshness="fresh",
    tier="deep_dive",
    tier_rationale="18K-word interview with concrete internal data — the 'kill list' framework is genuinely novel.",
    source_id="lennys-podcast",
    is_backlog=False,
)

# 4 Worth a Look
wal1_content = ContentItem(
    id="wal1", source_id="stratechery", source_name="Stratechery",
    content_type="article", title="The End of the App Store Monopoly",
    url="https://stratechery.com/2026/app-store-monopoly",
    published_at=now - timedelta(days=1), fetched_at=now,
    word_count=4200, status="processed",
)
wal1_processed = ProcessedContent(
    content_id="wal1",
    core_summary="The EU's DMA enforcement is forcing Apple to allow sideloading, but Thompson argues the real disruption isn't alternative app stores — it's alternative payment rails. Stripe and Adyen are already building iOS payment SDKs.",
    key_insights=[
        "Apple's 30% cut generated $24B in 2025 — more than Adobe's entire annual revenue.",
        "Epic's Fortnite sideloading numbers suggest <5% of users will switch stores, but payment switching could hit 40%.",
    ],
    so_what="The App Store fight was never about distribution — it's about payments. Stripe just became the most important company in mobile.",
    domains=["App-Store", "DMA", "payments"],
    content_category="news_analysis",
    freshness="fresh",
    tier="worth_a_look",
    source_id="stratechery",
    is_backlog=False,
)

wal2_content = ContentItem(
    id="wal2", source_id="bg2-pod", source_name="BG2 Pod",
    content_type="video", title="Why We're Selling NVDA and Buying ASML",
    url="https://youtube.com/watch?v=example4",
    published_at=now, fetched_at=now,
    duration_seconds=2700, word_count=8500, status="processed",
)
wal2_processed = ProcessedContent(
    content_id="wal2",
    core_summary="Bill Gurley and Brad Gerstner make the case that NVDA's margin compression is inevitable as custom silicon (Google TPUs, Amazon Trainium) scales. They're rotating into ASML, the picks-and-shovels play that benefits regardless of who wins the chip war.",
    key_insights=[
        "ASML's EUV machines have a 2-year order backlog — every chip maker needs them regardless of architecture.",
        "Custom silicon now handles 35% of hyperscaler AI inference, up from 8% two years ago.",
    ],
    so_what="NVDA bulls are pricing in permanent monopoly margins. The BG2 thesis: own the toolmaker (ASML), not the goldminer.",
    domains=["NVDA", "ASML", "chip-war"],
    content_category="market_call",
    freshness="fresh",
    tier="worth_a_look",
    source_id="bg2-pod",
    is_backlog=False,
)

wal3_content = ContentItem(
    id="wal3", source_id="y-combinator", source_name="Y Combinator",
    content_type="video", title="The Solo Founder Playbook — YC W26 Batch Insights",
    url="https://youtube.com/watch?v=example5",
    published_at=now - timedelta(days=3), fetched_at=now,
    duration_seconds=1800, word_count=6000, status="processed",
)
wal3_processed = ProcessedContent(
    content_id="wal3",
    core_summary="42% of YC W26 batch companies are solo founders — up from 18% in 2023. The thesis: AI tools have collapsed the minimum viable team from 3 to 1.",
    key_insights=[
        "Solo founders in W26 ship MVPs 2.3x faster than teams, but hit scaling walls at $500K ARR.",
        "The new YC advice: hire your first employee for ops, not engineering.",
    ],
    so_what="Stop optimizing for co-founder chemistry. Ship alone, hire for scale. The YC data says the 'you need a co-founder' orthodoxy is dead.",
    domains=["solo-founders", "YC-W26", "MVP-speed"],
    content_category="framework",
    freshness="fresh",
    tier="worth_a_look",
    source_id="y-combinator",
    is_backlog=False,
)

wal4_content = ContentItem(
    id="wal4", source_id="20vc", source_name="20VC",
    content_type="video", title="Benchmark's Sarah Tavel on AI Fund Deployment and the Death of SaaS Multiples",
    url="https://youtube.com/watch?v=example6",
    published_at=now - timedelta(days=1), fetched_at=now,
    duration_seconds=3300, word_count=10000, status="processed",
)
wal4_processed = ProcessedContent(
    content_id="wal4",
    core_summary="Tavel argues VC fund deployment cycles are compressing from 3 years to 18 months because AI companies reach product-market fit faster. The downside: they also hit revenue plateaus faster.",
    key_insights=[
        "Benchmark deployed their latest fund in 14 months — fastest in firm history.",
        "SaaS multiples won't recover because AI makes switching costs near-zero.",
    ],
    so_what="The venture model itself is mutating. Faster deployment + shorter growth cycles = smaller funds win. The mega-fund era ($1B+ AUM) may be ending.",
    domains=["VC-deployment", "SaaS-multiples", "Benchmark"],
    content_category="interview",
    freshness="fresh",
    tier="worth_a_look",
    source_id="20vc",
    is_backlog=True,  # This one is Evergreen to test the badge
)

# 4 Summary Sufficient
ss1_content = ContentItem(
    id="ss1", source_id="nate-b-jones", source_name="Nate B Jones",
    content_type="video", title="5 AI Tools That Replaced My Entire Marketing Stack",
    url="https://youtube.com/watch?v=example7",
    published_at=now - timedelta(days=1), fetched_at=now,
    duration_seconds=900, word_count=2800, status="processed",
)
ss1_processed = ProcessedContent(
    content_id="ss1",
    core_summary="Standard listicle: Clay for outbound, Jasper for copy, Midjourney for assets, Zapier for automation, Notion AI for docs.",
    so_what="Nothing new here — these are the same 5 tools every AI marketing thread recommends. Save 15 minutes.",
    domains=["AI-marketing", "tool-stack"],
    content_category="tutorial",
    freshness="evergreen",
    tier="summary_sufficient",
    source_id="nate-b-jones",
)

ss2_content = ContentItem(
    id="ss2", source_id="greg-isenberg", source_name="Greg Isenberg",
    content_type="video", title="How I'd Build a $1M SaaS in 2026 (Step by Step)",
    url="https://youtube.com/watch?v=example8",
    published_at=now - timedelta(days=2), fetched_at=now,
    duration_seconds=1200, word_count=3500, status="processed",
)
ss2_processed = ProcessedContent(
    content_id="ss2",
    core_summary="Greg's formula: pick a boring niche, use AI to build faster, charge $99/mo, get to 840 customers. Standard playbook rehash.",
    so_what="The 'boring SaaS + AI speed' thesis is sound but this adds nothing to what Greg said 6 months ago. The framework hasn't evolved.",
    domains=["SaaS-playbook", "indie-hacker"],
    content_category="framework",
    freshness="stale",
    tier="summary_sufficient",
    source_id="greg-isenberg",
)

ss3_content = ContentItem(
    id="ss3", source_id="nate-b-jones", source_name="Nate B Jones",
    content_type="video", title="OpenAI's New Agent SDK — First Impressions",
    url="https://youtube.com/watch?v=example9",
    published_at=now, fetched_at=now,
    duration_seconds=720, word_count=2200, status="processed",
)
ss3_processed = ProcessedContent(
    content_id="ss3",
    core_summary="Quick overview of OpenAI's Agents SDK. Covers tool_use, handoffs, and guardrails. No original analysis — basically reads the docs.",
    so_what="Read the OpenAI docs directly instead. This adds commentary but no insight.",
    domains=["OpenAI-agents", "SDK-review"],
    content_category="tutorial",
    freshness="fresh",
    tier="summary_sufficient",
    source_id="nate-b-jones",
)

ss4_content = ContentItem(
    id="ss4", source_id="greg-isenberg", source_name="Greg Isenberg",
    content_type="video", title="The AI Wrapper Opportunity Nobody Talks About",
    url="https://youtube.com/watch?v=example10",
    published_at=now - timedelta(days=4), fetched_at=now,
    duration_seconds=960, word_count=3000, status="processed",
)
ss4_processed = ProcessedContent(
    content_id="ss4",
    core_summary="Greg argues vertical AI wrappers still have a 12-month window. Examples: legal doc review, insurance claims, restaurant inventory.",
    so_what="The window thesis is right but the examples are already crowded. The real wrapper opportunities are in industries that don't have YouTube channels.",
    domains=["AI-wrappers", "vertical-SaaS"],
    content_category="commentary",
    freshness="evergreen",
    tier="summary_sufficient",
    source_id="greg-isenberg",
)

# ── Assemble ──────────────────────────────────────────────────────

items = [
    {"content": dd1_content, "processed": dd1_processed},
    {"content": dd2_content, "processed": dd2_processed},
    {"content": wal1_content, "processed": wal1_processed},
    {"content": wal2_content, "processed": wal2_processed},
    {"content": wal3_content, "processed": wal3_processed},
    {"content": wal4_content, "processed": wal4_processed},
    {"content": ss1_content, "processed": ss1_processed},
    {"content": ss2_content, "processed": ss2_processed},
    {"content": ss3_content, "processed": ss3_processed},
    {"content": ss4_content, "processed": ss4_processed},
]

briefing = DailyBriefing(
    id="test-briefing",
    briefing_date=today,
    created_at=now,
    fresh_count=8,
    backlog_count=2,
    total_count=10,
    item_ids=[i["content"].id for i in items],
)

editorial_intro = "Three items about AI collapsing team sizes, one about why VCs can't deploy money fast enough — the through-line is that the entire startup stack is compressing."

backlog_progress = {
    "total_items": 905,
    "delivered_items": 847,
    "percent_complete": 93.6,
}

footer_stats = {
    "briefing_count": 28,
    "total_delivered": 312,
}

# ── Generate ──────────────────────────────────────────────────────

html = generate_briefing_html(
    briefing=briefing,
    items=items,
    backlog_progress=backlog_progress,
    footer_stats=footer_stats,
    editorial_intro=editorial_intro,
)

output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "test_email_redesign.html")
os.makedirs(os.path.dirname(output_path), exist_ok=True)
with open(output_path, "w") as f:
    f.write(html)

print(f"Test email saved to: {output_path}")
webbrowser.open(f"file://{output_path}")
