"""
Email generation and delivery for daily briefings.

Generates HTML email from briefing data and sends via Gmail SMTP.
The email is optimized for a 5-10 minute morning scan:
- Layer 1: Glanceable headline index (30 seconds)
- Layer 2: Compact summary cards (5 minutes)
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


def _so_what_inline(so_what: str) -> str:
    """Generate a compact inline so-what for summary_sufficient cards."""
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

    # ========== LAYER 1: Headline Index ==========
    headline_rows = ""
    for item in items:
        c = item["content"]
        p = item["processed"]
        length_str = _format_length(c.word_count, c.duration_seconds)
        rel = _relative_date(c.published_at)
        title_clean = _clean_title(c.title)
        # Truncate long titles in the headline index for scannability
        if len(title_clean) > 70:
            title_clean = title_clean[:67] + "..."
        backlog_tag = ' <span style="color:#dc2626;font-size:11px;font-weight:600;background:#fef2f2;padding:1px 5px;border-radius:3px;">BACKLOG</span>' if p.is_backlog else ""

        # Build topic tag pills
        tag_pills = ""
        if p.domains:
            tag_pills = " ".join(
                f'<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;background:#f1f5f9;color:#475569;margin-right:2px;">{tag}</span>'
                for tag in p.domains[:3]
            )
            tag_pills = f"<br>{tag_pills}"

        headline_rows += f"""
        <tr>
            <td style="padding:5px 8px 5px 0;vertical-align:top;width:24px;font-size:16px;">{p.tier_emoji}</td>
            <td style="padding:5px 0;">
                <span style="color:#0f172a;font-size:14px;font-weight:500;">{title_clean}</span>{backlog_tag}
                <br>
                <span style="font-size:12px;color:#94a3b8;">{c.source_name} &middot; {length_str} &middot; {rel}</span>
                {tag_pills}
            </td>
        </tr>
        """

    # ========== LAYER 2: Detail Cards ==========
    sections_html = ""

    if deep_dives:
        sections_html += _build_tier_section(
            "🔴 Deep Dive", "Worth consuming in full", deep_dives,
            detail_level="full", bg_color="#fef7f7", accent_border="#ef4444",
        )

    if worth_a_look:
        sections_html += _build_tier_section(
            "🟡 Worth a Look", "Summary captures most of it", worth_a_look, detail_level="medium"
        )

    if summary_sufficient:
        sections_html += _build_tier_section(
            "🟢 Summary Sufficient", "You've got the gist", summary_sufficient, detail_level="compact"
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

    # Estimate read time — per-item overhead + word-based reading time
    total_words = 0
    for item in items:
        p = item["processed"]
        total_words += len(p.core_summary.split())
        total_words += sum(len(ins.split()) for ins in p.key_insights[:3])
        if p.so_what:
            total_words += len(p.so_what.split())
    overhead_seconds = len(items) * 15  # ~15s per item for scanning title, meta, context-switching
    reading_seconds = total_words / 200 * 60  # ~200 wpm scanning speed
    est_minutes = max(3, round((overhead_seconds + reading_seconds) / 60))
    read_time_str = f"~{est_minutes} min read"

    # Count badges
    badges = []
    if deep_dives:
        badges.append(f'<span style="padding:3px 10px;border-radius:12px;font-size:12px;background:#fef2f2;color:#991b1b;">🔴 {len(deep_dives)}</span>')
    if worth_a_look:
        badges.append(f'<span style="padding:3px 10px;border-radius:12px;font-size:12px;background:#fefce8;color:#854d0e;">🟡 {len(worth_a_look)}</span>')
    if summary_sufficient:
        badges.append(f'<span style="padding:3px 10px;border-radius:12px;font-size:12px;background:#f0fdf4;color:#166534;">🟢 {len(summary_sufficient)}</span>')
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

    # Editorial intro (between headline index and detail cards)
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

        <!-- Header + Headline Index (Layer 1) -->
        <div style="background:white;border-radius:12px;padding:20px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
            <h1 style="margin:0 0 4px 0;font-size:22px;color:#0f172a;">Daily Briefing</h1>
            <p style="margin:0 0 12px 0;color:#94a3b8;font-size:13px;">
                {date_str} &middot; {briefing.total_count} items &middot; {read_time_str} &middot; {badges_html}
            </p>

            <!-- Headline Index -->
            <table style="width:100%;border-collapse:collapse;">
                {headline_rows}
            </table>
            {editorial_html}
        </div>

        <!-- Detail Cards (Layer 2) -->
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
    bg_color: str = "white", accent_border: str = "",
) -> str:
    """
    Build HTML for a tier section.

    detail_level:
        "full"    — deep_dive: summary + 3 insights + so_what + link
        "medium"  — worth_a_look: summary + 3 insights + so_what + link
        "compact" — summary_sufficient: summary + inline take
    """
    border_style = f"border-left:4px solid {accent_border};" if accent_border else ""
    section_html = f"""
    <div style="background:{bg_color};border-radius:12px;padding:20px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.1);{border_style}">
        <h2 style="margin:0 0 2px 0;font-size:16px;color:#0f172a;">{title}</h2>
        <p style="margin:0 0 16px 0;font-size:12px;color:#94a3b8;">{subtitle}</p>
    """

    for item in items:
        content: ContentItem = item["content"]
        processed: ProcessedContent = item["processed"]

        # Meta line
        length_str = _format_length(content.word_count, content.duration_seconds)
        rel_date = _relative_date(content.published_at)
        meta_parts = [content.source_name, length_str, rel_date]
        meta = " &middot; ".join(meta_parts)
        if processed.is_backlog:
            meta += ' <span style="color:#dc2626;font-size:11px;font-weight:600;background:#fef2f2;padding:1px 5px;border-radius:3px;">BACKLOG</span>'

        title_clean = _clean_title(content.title)

        if detail_level == "full":
            # Deep dive: summary (2-3 sentences) + top 3 insights + so_what + link
            summary_text = _truncate_sentences(processed.core_summary, 3)

            insights_html = ""
            if processed.key_insights:
                items_html = "".join(
                    f"<li style='margin-bottom:3px;color:#334155;font-size:13px;line-height:1.4;'>{ins}</li>"
                    for ins in processed.key_insights[:3]
                )
                insights_html = f'<ul style="margin:8px 0 0 0;padding-left:18px;">{items_html}</ul>'

            so_what_html = _so_what_box(processed.so_what)

            section_html += f"""
            <div id="item-{processed.content_id}" style="padding:12px 0;border-bottom:1px solid #f1f5f9;">
                <h3 style="margin:0 0 4px 0;font-size:15px;">
                    <a href="{content.url}" style="color:#0f172a;text-decoration:none;">{title_clean}</a>
                </h3>
                <p style="margin:0 0 6px 0;font-size:12px;color:#94a3b8;">{meta}</p>
                <p style="margin:0;font-size:13px;color:#334155;line-height:1.5;">{summary_text}</p>
                {insights_html}
                {so_what_html}
                <p style="margin:8px 0 0 0;">
                    <a href="{content.url}" style="color:#3b82f6;font-size:13px;text-decoration:none;font-weight:500;">
                        {_action_link(content)} &rarr;
                    </a>
                </p>
            </div>
            """

        elif detail_level == "medium":
            # Worth a look: summary + top 3 insights + so_what + link
            summary_text = _truncate_sentences(processed.core_summary, 2)

            insights_html = ""
            if processed.key_insights:
                items_html = "".join(
                    f"<li style='margin-bottom:2px;color:#334155;font-size:13px;'>{ins}</li>"
                    for ins in processed.key_insights[:3]
                )
                insights_html = f'<ul style="margin:6px 0 0 0;padding-left:18px;">{items_html}</ul>'

            so_what_html = _so_what_box(processed.so_what)

            section_html += f"""
            <div id="item-{processed.content_id}" style="padding:10px 0;border-bottom:1px solid #f1f5f9;">
                <h3 style="margin:0 0 4px 0;font-size:15px;">
                    <a href="{content.url}" style="color:#0f172a;text-decoration:none;">{title_clean}</a>
                </h3>
                <p style="margin:0 0 6px 0;font-size:12px;color:#94a3b8;">{meta}</p>
                <p style="margin:0;font-size:13px;color:#334155;line-height:1.5;">{summary_text}</p>
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
            # Summary sufficient: summary + inline take
            summary_text = _truncate_sentences(processed.core_summary, 2)
            so_what_html = _so_what_inline(processed.so_what)

            section_html += f"""
            <div id="item-{processed.content_id}" style="padding:8px 0;border-bottom:1px solid #f1f5f9;">
                <h3 style="margin:0 0 3px 0;font-size:14px;">
                    <a href="{content.url}" style="color:#0f172a;text-decoration:none;">{title_clean}</a>
                </h3>
                <p style="margin:0 0 4px 0;font-size:12px;color:#94a3b8;">{meta}</p>
                <p style="margin:0;font-size:13px;color:#64748b;line-height:1.4;">{summary_text}</p>
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

            with smtplib.SMTP("smtp.gmail.com", 587) as server:
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
