"""
Email generation and delivery for daily briefings.

Generates HTML email from briefing data and sends via Gmail SMTP.
The email is optimized for a 5-10 minute morning scan with three
distinct card layouts per tier (Deep Dive, Worth a Look, Summary Sufficient).
"""
from __future__ import annotations

import html
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from ..storage.models import DailyBriefing, ContentItem, ProcessedContent


def _clean_title(title: str) -> str:
    """Unescape HTML entities in titles (e.g., &amp; → &).

    Titles from RSS/YouTube feeds often contain escaped entities.
    We unescape them so they render correctly in the HTML email.
    """
    return html.unescape(title)


def _format_duration(seconds: Optional[int]) -> str:
    """Format duration in seconds to human-readable string."""
    if not seconds:
        return ""
    if seconds >= 3600:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h {mins}m"
    return f"{seconds // 60}m"


def _format_length(word_count: int, duration_seconds: Optional[int] = None) -> str:
    """Format content length for display, handling the 0k words bug."""
    duration = _format_duration(duration_seconds)
    if duration:
        return duration
    if word_count < 1000:
        return f"{word_count} words"
    return f"{word_count // 1000}k words"


def _relative_date(dt: datetime) -> str:
    """Format datetime as relative string like '2 days ago'."""
    now = datetime.now()
    diff = now - dt
    days = diff.days

    if days == 0:
        return "today"
    elif days == 1:
        return "yesterday"
    elif days < 7:
        return f"{days}d ago"
    elif days < 30:
        return f"{days // 7}w ago"
    elif days < 60:
        return "1mo ago"
    else:
        return f"{days // 30}mo ago"


def _truncate_sentences(text: str, max_sentences: int) -> str:
    """Truncate text to the first N sentences."""
    sentences = []
    for s in text.replace('\n', ' ').split('. '):
        s = s.strip()
        if s:
            if not s.endswith('.'):
                s += '.'
            sentences.append(s)
            if len(sentences) >= max_sentences:
                break
    return ' '.join(sentences)


def _action_link(content) -> str:
    """Generate action link text: 'Watch (42m)' for video, 'Read' for article."""
    if content.content_type == "video":
        duration = _format_duration(content.duration_seconds)
        if duration:
            return f"Watch ({duration})"
        return "Watch"
    return "Read"


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


def _concepts_html(concepts: list) -> str:
    """Generate HTML for concepts_explained (Deep Dive only, max 2)."""
    if not concepts:
        return ""
    items_html = ""
    for c in concepts[:2]:
        term = html.escape(c.term)
        explanation = html.escape(c.explanation)
        items_html += f'<p style="margin:4px 0;font-size:13px;color:#334155;line-height:1.4;"><strong>{term}:</strong> {explanation}</p>'
    return f'<div style="margin-top:8px;padding:8px 10px;background:#f8fafc;border-radius:6px;">{items_html}</div>'


def _so_what_box(so_what: str) -> str:
    """Generate the blue so-what box HTML."""
    if not so_what:
        return ""
    so_what_text = _truncate_sentences(so_what, 2)
    return f"""
    <div style="margin-top:8px;padding:8px 10px;background:#eff6ff;border-radius:6px;border-left:3px solid #3b82f6;">
        <p style="margin:0;font-size:13px;color:#1e3a5f;line-height:1.4;"><strong>So what:</strong> {so_what_text}</p>
    </div>
    """


def _topic_tag_pills(domains: list[str]) -> str:
    """Generate inline topic tag pills for detail cards."""
    if not domains:
        return ""
    pills = " ".join(
        f'<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;background:#f1f5f9;color:#475569;margin-right:2px;">{tag}</span>'
        for tag in domains[:3]
    )
    return f'<p style="margin:2px 0 0 0;">{pills}</p>'


def _so_what_inline(so_what: str) -> str:
    """Generate a compact inline so-what for Worth a Look and Summary Sufficient cards."""
    if not so_what:
        return ""
    so_what_text = _truncate_sentences(so_what, 2)
    return f"""
    <p style="margin:4px 0 0 0;font-size:13px;color:#1e3a5f;line-height:1.4;font-style:italic;">
        <strong>Take:</strong> {so_what_text}
    </p>
    """


def generate_briefing_html(
    briefing: DailyBriefing,
    items: list[dict],
    backlog_progress: Optional[dict] = None,
    footer_stats: Optional[dict] = None,
    editorial_intro: Optional[str] = None,
) -> str:
    """
    Generate the full HTML email for a daily briefing.
    Designed for a 5-10 minute morning scan.
    """
    date_str = briefing.briefing_date.strftime("%B %d, %Y")

    # Group items by tier
    deep_dives = []
    worth_a_look = []
    summary_sufficient = []

    for item in items:
        p = item["processed"]
        if p.tier == "deep_dive":
            deep_dives.append(item)
        elif p.tier == "worth_a_look":
            worth_a_look.append(item)
        else:
            summary_sufficient.append(item)

    # ========== Detail Cards ==========
    sections_html = ""

    if deep_dives:
        sections_html += _build_tier_section(
            "🔴 Deep Dive", "Worth consuming in full", deep_dives,
            detail_level="full", bg_color="#fef7f7", accent_border="#ef4444",
        )

    if worth_a_look:
        sections_html += _build_tier_section(
            "🟡 Worth a Look", "Summary captures most of it", worth_a_look,
            detail_level="medium", accent_border="#eab308", border_width=3,
        )

    if summary_sufficient:
        sections_html += _build_tier_section(
            "🟢 Summary Sufficient", "You've got the gist", summary_sufficient,
            detail_level="compact", bg_color="#f8fafc",
        )

    # Backlog progress bar
    backlog_html = ""
    if backlog_progress and backlog_progress.get("total_items", 0) > 0:
        pct = backlog_progress["percent_complete"]
        delivered = backlog_progress["delivered_items"]
        total = backlog_progress["total_items"]
        backlog_html = f"""
        <div style="margin-top:20px;padding:12px;background:#f8fafc;border-radius:8px;">
            <p style="margin:0 0 6px 0;font-size:13px;color:#64748b;">
                Backlog: {pct:.0f}% ({delivered}/{total})
            </p>
            <div style="background:#e2e8f0;border-radius:4px;height:6px;overflow:hidden;">
                <div style="background:#3b82f6;height:100%;width:{int(pct)}%;border-radius:4px;"></div>
            </div>
        </div>
        """

    # Estimate read time — count words actually rendered per tier
    total_words = 0
    for item in items:
        p = item["processed"]
        if p.tier == "deep_dive":
            total_words += len(p.core_summary.split())
            total_words += sum(len(ins.split()) for ins in p.key_insights[:3])
        elif p.tier == "worth_a_look":
            total_words += len(p.core_summary.split())
            total_words += sum(len(ins.split()) for ins in p.key_insights[:2])
        # summary_sufficient: only so_what is shown
        if p.so_what:
            total_words += len(p.so_what.split())
    overhead_seconds = len(items) * 15  # ~15s per item for scanning title, meta, context-switching
    reading_seconds = total_words / 200 * 60  # ~200 wpm scanning speed
    est_minutes = max(3, round((overhead_seconds + reading_seconds) / 60))
    read_time_str = f"~{est_minutes} min read"

    # Count badges
    badges = []
    if deep_dives:
        badges.append(f'<span style="padding:3px 10px;border-radius:12px;font-size:12px;white-space:nowrap;background:#fef2f2;color:#991b1b;">🔴&nbsp;{len(deep_dives)}</span>')
    if worth_a_look:
        badges.append(f'<span style="padding:3px 10px;border-radius:12px;font-size:12px;white-space:nowrap;background:#fefce8;color:#854d0e;">🟡&nbsp;{len(worth_a_look)}</span>')
    if summary_sufficient:
        badges.append(f'<span style="padding:3px 10px;border-radius:12px;font-size:12px;white-space:nowrap;background:#f0fdf4;color:#166534;">🟢&nbsp;{len(summary_sufficient)}</span>')
    badges_html = " ".join(badges)

    # Footer stats
    stats_html = ""
    if footer_stats:
        bc = footer_stats.get("briefing_count", 0)
        td = footer_stats.get("total_delivered", 0)
        if bc > 0 or td > 0:
            stats_html = f"""
            <p style="margin:0 0 6px 0;font-size:12px;color:#94a3b8;text-align:center;">
                You've read {bc} briefing{"s" if bc != 1 else ""} &middot; {td} items processed
            </p>
            """

    # Editorial intro (inside header card)
    editorial_html = ""
    if editorial_intro:
        editorial_html = f"""
            <div style="background:#f8fafc;border-radius:8px;padding:12px 16px;margin-top:12px;border-left:3px solid #6366f1;">
                <p style="margin:0;font-size:13px;color:#334155;line-height:1.5;font-style:italic;">
                    {editorial_intro}
                </p>
            </div>
        """

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
    <div style="max-width:600px;margin:0 auto;padding:20px;">

        <!-- Header Card -->
        <div style="background:white;border-radius:12px;padding:20px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
            <h1 style="margin:0 0 4px 0;font-size:22px;color:#0f172a;">Daily Briefing</h1>
            <p style="margin:0 0 8px 0;color:#94a3b8;font-size:13px;">
                {date_str} &middot; {briefing.total_count} items &middot; {read_time_str} &middot; {badges_html}
            </p>
            {editorial_html}
        </div>

        <!-- Detail Cards -->
        {sections_html}

        <!-- Footer -->
        <div style="background:white;border-radius:12px;padding:16px;margin-top:12px;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
            {backlog_html}
            {stats_html}
            <p style="margin:6px 0 0 0;font-size:12px;color:#94a3b8;text-align:center;">
                Daily Briefing Tool &middot; Built by Sukrit with Claude
            </p>
        </div>

    </div>
</body>
</html>"""


def _build_tier_section(
    title: str, subtitle: str, items: list[dict], detail_level: str = "full",
    bg_color: str = "white", accent_border: str = "", border_width: int = 4,
) -> str:
    """
    Build HTML for a tier section with distinct layouts per tier.

    detail_level:
        "full"    — Deep Dive: pink bg, red border, 16px title, 3 insights,
                     blue so_what box, concepts_explained, action link
        "medium"  — Worth a Look: white bg, yellow left border, 15px title,
                     2 insights, inline take, action link
        "compact" — Summary Sufficient: gray bg, no border, 14px muted title,
                     no summary, no insights, inline take, no link
    """
    if detail_level == "compact":
        # Compact section: minimal padding, no border
        section_html = f"""
    <div style="background:{bg_color};border-radius:12px;padding:16px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
        <h2 style="margin:0 0 2px 0;font-size:16px;color:#0f172a;">{title}</h2>
        <p style="margin:0 0 12px 0;font-size:12px;color:#94a3b8;">{subtitle}</p>
    """
    else:
        border_style = f"border-left:{border_width}px solid {accent_border};" if accent_border else ""
        section_html = f"""
    <div style="background:{bg_color};border-radius:12px;padding:20px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.1);{border_style}">
        <h2 style="margin:0 0 2px 0;font-size:16px;color:#0f172a;">{title}</h2>
        <p style="margin:0 0 16px 0;font-size:12px;color:#94a3b8;">{subtitle}</p>
    """

    for item in items:
        content: ContentItem = item["content"]
        processed: ProcessedContent = item["processed"]

        title_clean = _clean_title(content.title)

        # Backlog / Evergreen badge
        backlog_badge = ""
        if processed.is_backlog:
            backlog_badge = ' <span style="color:#0d9488;font-size:11px;font-weight:600;background:#f0fdfa;padding:1px 5px;border-radius:3px;">Evergreen</span>'

        if detail_level == "full":
            # ── Deep Dive ──────────────────────────────────────────────
            length_str = _format_length(content.word_count, content.duration_seconds)
            rel_date = _relative_date(content.published_at)
            ct_label = _content_type_label(processed.content_category)

            meta_parts = [content.source_name]
            if ct_label:
                meta_parts.append(ct_label)
            meta_parts.extend([length_str, rel_date])
            meta = " &middot; ".join(meta_parts)
            meta += backlog_badge

            summary_text = _truncate_sentences(processed.core_summary, 3)
            tag_pills_html = _topic_tag_pills(processed.domains)

            insights_html = ""
            if processed.key_insights:
                items_html = "".join(
                    f"<li style='margin-bottom:3px;color:#334155;font-size:13px;line-height:1.4;'>{ins}</li>"
                    for ins in processed.key_insights[:3]
                )
                insights_html = f'<ul style="margin:8px 0 0 0;padding-left:18px;">{items_html}</ul>'

            so_what_html = _so_what_box(processed.so_what)
            concepts_html = _concepts_html(processed.concepts_explained)

            section_html += f"""
            <div id="item-{processed.content_id}" style="padding:12px 0;border-bottom:1px solid #f1f5f9;">
                <h3 style="margin:0 0 4px 0;font-size:16px;">
                    <a href="{content.url}" style="color:#0f172a;text-decoration:none;">{title_clean}</a>
                </h3>
                <p style="margin:0 0 4px 0;font-size:12px;color:#94a3b8;">{meta}</p>
                {tag_pills_html}
                <p style="margin:6px 0 0 0;font-size:13px;color:#334155;line-height:1.5;">{summary_text}</p>
                {insights_html}
                {so_what_html}
                {concepts_html}
                <p style="margin:8px 0 0 0;">
                    <a href="{content.url}" style="color:#3b82f6;font-size:13px;text-decoration:none;font-weight:500;">
                        {_action_link(content)} &rarr;
                    </a>
                </p>
            </div>
            """

        elif detail_level == "medium":
            # ── Worth a Look ───────────────────────────────────────────
            length_str = _format_length(content.word_count, content.duration_seconds)
            rel_date = _relative_date(content.published_at)
            ct_label = _content_type_label(processed.content_category)

            meta_parts = [content.source_name]
            if ct_label:
                meta_parts.append(ct_label)
            meta_parts.extend([length_str, rel_date])
            meta = " &middot; ".join(meta_parts)
            meta += backlog_badge

            summary_text = _truncate_sentences(processed.core_summary, 2)
            tag_pills_html = _topic_tag_pills(processed.domains)

            insights_html = ""
            if processed.key_insights:
                items_html = "".join(
                    f"<li style='margin-bottom:2px;color:#334155;font-size:13px;'>{ins}</li>"
                    for ins in processed.key_insights[:2]
                )
                insights_html = f'<ul style="margin:6px 0 0 0;padding-left:18px;">{items_html}</ul>'

            so_what_html = _so_what_inline(processed.so_what)

            section_html += f"""
            <div id="item-{processed.content_id}" style="padding:10px 0;border-bottom:1px solid #f1f5f9;">
                <h3 style="margin:0 0 4px 0;font-size:15px;">
                    <a href="{content.url}" style="color:#0f172a;text-decoration:none;">{title_clean}</a>
                </h3>
                <p style="margin:0 0 4px 0;font-size:12px;color:#94a3b8;">{meta}</p>
                {tag_pills_html}
                <p style="margin:6px 0 0 0;font-size:13px;color:#334155;line-height:1.5;">{summary_text}</p>
                {insights_html}
                {so_what_html}
                <p style="margin:6px 0 0 0;">
                    <a href="{content.url}" style="color:#3b82f6;font-size:13px;text-decoration:none;font-weight:500;">
                        {_action_link(content)} &rarr;
                    </a>
                </p>
            </div>
            """

        else:
            # ── Summary Sufficient ─────────────────────────────────────
            rel_date = _relative_date(content.published_at)
            meta = f"{content.source_name} &middot; {rel_date}"
            meta += backlog_badge

            so_what_html = _so_what_inline(processed.so_what)

            section_html += f"""
            <div id="item-{processed.content_id}" style="padding:8px 0;border-bottom:1px solid #e2e8f0;">
                <p style="margin:0 0 3px 0;font-size:14px;font-weight:500;color:#334155;">{title_clean}</p>
                <p style="margin:0 0 4px 0;font-size:12px;color:#94a3b8;">{meta}</p>
                {so_what_html}
            </div>
            """

    section_html += "</div>"
    return section_html


def generate_subject_line(briefing: DailyBriefing, items: list[dict]) -> str:
    """Generate email subject line optimized for Outlook mobile (~75 char preview).

    Format: "Feb 10: [title] (+N more)"
    - Prefix "Feb 10: " = ~9 chars, suffix " (+N more)" = ~12 chars
    - Leaves ~54 chars for the title
    - Truncates at word boundaries to avoid mid-word cuts
    - Only adds "..." when truncation actually happens
    """
    date_str = briefing.briefing_date.strftime("%b %d")

    # Lead with the most important item title
    if items:
        top_title = html.unescape(items[0]["content"].title)
        max_title_len = 54
        if len(top_title) > max_title_len:
            # Truncate at last word boundary before the limit
            truncated = top_title[:max_title_len]
            last_space = truncated.rfind(' ')
            if last_space > 20:  # Don't truncate too aggressively
                truncated = truncated[:last_space]
            top_title = truncated.rstrip('.,;:!? ') + "..."
        remaining = briefing.total_count - 1
        if remaining > 0:
            return f"{date_str}: {top_title} (+{remaining} more)"
        return f"{date_str}: {top_title}"

    return f"Daily Briefing — {date_str} | {briefing.total_count} items"


class Emailer:
    """Sends briefing emails via Gmail SMTP."""

    def __init__(
        self,
        from_email: str = None,
        to_email: str = None,
    ):
        self.smtp_user = os.getenv("SMTP_USER")
        self.smtp_password = os.getenv("SMTP_APP_PASSWORD")
        self.from_email = from_email or os.getenv("EMAIL_FROM", f"Daily Briefing <{self.smtp_user}>")
        raw_to = to_email or os.getenv("EMAIL_TO", "")
        self.to_emails = [e.strip() for e in raw_to.split(",") if e.strip()]

        if not self.smtp_user or not self.smtp_password:
            raise ValueError("SMTP_USER and SMTP_APP_PASSWORD must be set in .env")
        if not self.to_emails:
            raise ValueError("EMAIL_TO not set")

    def send_briefing(
        self,
        briefing: DailyBriefing,
        items: list[dict],
        backlog_progress: Optional[dict] = None,
        footer_stats: Optional[dict] = None,
        editorial_intro: Optional[str] = None,
    ) -> bool:
        """
        Generate and send the briefing email via Gmail SMTP.

        Returns:
            True if sent successfully
        """
        email_html = generate_briefing_html(briefing, items, backlog_progress, footer_stats, editorial_intro)
        subject = generate_subject_line(briefing, items)

        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_email
            msg["To"] = ", ".join(self.to_emails)
            msg["Subject"] = subject
            msg.attach(MIMEText(email_html, "html"))

            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_user, self.to_emails, msg.as_string())

            print(f"  Email sent to {', '.join(self.to_emails)}")
            return True

        except Exception as e:
            print(f"  Email send failed: {e}")
            return False

    def save_html_backup(
        self,
        briefing: DailyBriefing,
        items: list[dict],
        backlog_progress: Optional[dict] = None,
        footer_stats: Optional[dict] = None,
        editorial_intro: Optional[str] = None,
        output_path: str = None,
    ) -> str:
        """Save briefing HTML to a local file."""
        email_html = generate_briefing_html(briefing, items, backlog_progress, footer_stats, editorial_intro)

        if output_path is None:
            date_str = briefing.briefing_date.strftime("%Y-%m-%d")
            output_path = f"data/briefing_{date_str}.html"

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(email_html)

        return output_path
