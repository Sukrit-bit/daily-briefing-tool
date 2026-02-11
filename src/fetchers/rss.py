"""
RSS feed fetcher.

Fetches articles from RSS feeds (like Stratechery, Substack, etc.)
and extracts the full article content.

Supports WordPress-style pagination (?paged=N) for feeds like Stratechery
that have more content than fits in a single page.
"""

from __future__ import annotations

import re
import time
import requests
from datetime import datetime, date
from typing import Generator, Optional

import feedparser
from bs4 import BeautifulSoup

from .base import BaseFetcher
from ..storage.models import ContentItem, Source

# Sources whose RSS entries should be filtered to only include "Articles" category.
# This skips paid Daily Updates, This Week summaries, etc.
CATEGORY_FILTER_SOURCES = {"stratechery"}


# Paywall signature phrases — if 2+ appear in short content, it's a paywall stub
PAYWALL_SIGNATURES = [
    "subscribe to stratechery",
    "this update is for paying subscribers",
    "already a subscriber? sign in",
    "join as a paid subscriber",
    "this post is for paid subscribers",
    "upgrade to paid",
    "member-only content",
    "subscriber-only",
    "premium subscription",
    "sign in to read",
    "become a member",
    "exclusive content for subscribers",
    "stratechery plus",
]


def _is_paywall_content(text: str, max_words: int = 1000) -> bool:
    """Detect if text is a paywall stub rather than real article content."""
    if not text:
        return False
    words = text.split()
    if len(words) > max_words:
        return False  # Long content is unlikely to be just a paywall page
    text_lower = text.lower()
    matches = sum(1 for sig in PAYWALL_SIGNATURES if sig in text_lower)
    return matches >= 2


class RSSFetcher(BaseFetcher):
    """
    Fetches articles from RSS feeds.

    Designed to work with:
    - Stratechery (free articles)
    - Substack newsletters
    - Standard blog RSS feeds
    """

    def __init__(self, source: Source):
        super().__init__(source)
        self.feed_url = self.source.url
    
    # Delay between paginated feed fetches (seconds) to be respectful
    PAGE_FETCH_DELAY = 1.0

    def fetch_content_list(self, since: date = None, limit: int = None) -> Generator[ContentItem, None, None]:
        """
        Fetch list of articles from the RSS feed.

        Supports WordPress-style pagination (?paged=N) for feeds that have
        more content than fits in a single page. Pagination continues until
        one of these stop conditions is met:
          - A page returns no entries (past the end)
          - A page returns an HTTP/parse error (bozo with no entries)
          - ALL entries on a page predate the `since` date
          - We've reached the `limit`

        For Stratechery, entries are filtered to the "Articles" category only,
        which skips paid Daily Updates and This Week summaries.

        Args:
            since: Only fetch articles published after this date
            limit: Maximum number of articles to fetch

        Yields:
            ContentItem objects (content may be partial from RSS)
        """
        if limit is None:
            limit = 50

        if since is None:
            since = self.source.fetch_since

        apply_category_filter = self.source.id in CATEGORY_FILTER_SOURCES
        now = datetime.now()
        count = 0
        page = 1

        while count < limit:
            # Build the URL for this page
            if page == 1:
                page_url = self.feed_url
            else:
                # WordPress pagination: ?paged=N
                separator = "&" if "?" in self.feed_url else "?"
                page_url = f"{self.feed_url}{separator}paged={page}"

            try:
                feed = feedparser.parse(page_url)
            except Exception as e:
                print(f"RSS fetch error for {self.source.name} (page {page}): {e}")
                break

            # Stop if the feed had a fatal parse error and returned nothing
            if feed.bozo and not feed.entries:
                if page == 1:
                    # First page error is worth reporting
                    print(f"RSS parse error for {self.source.name}: {feed.bozo_exception}")
                else:
                    # Later pages returning errors means we've gone past the end
                    print(f"  Page {page}: no more content (feed error), stopping pagination")
                break

            if feed.bozo and page == 1:
                # Non-fatal warning on first page
                print(f"RSS parse warning for {self.source.name}: {feed.bozo_exception}")

            # Stop if the page has no entries
            if not feed.entries:
                if page > 1:
                    print(f"  Page {page}: empty, stopping pagination")
                break

            # Track whether any entry on this page was within the date range
            any_in_range = False

            for entry in feed.entries:
                if count >= limit:
                    break

                # Parse published date
                published_at = self._parse_entry_date(entry)
                if not published_at:
                    published_at = now

                # Filter by date — skip entries before `since`
                if since and published_at.date() < since:
                    continue

                # Mark that at least one entry was within range
                any_in_range = True

                # Category filter (Stratechery only): skip non-Articles
                if apply_category_filter:
                    categories = [tag.get('term', '') for tag in entry.get('tags', [])]
                    if 'Articles' not in categories:
                        continue

                # Get the article URL
                url = entry.get('link', '')
                if not url:
                    continue

                # Generate content ID
                content_id = ContentItem.generate_id(self.source.id, url)

                # Get title
                title = entry.get('title', 'Untitled')

                # Get content from RSS (may be summary or full content)
                content = self._extract_entry_content(entry)

                yield ContentItem(
                    id=content_id,
                    source_id=self.source.id,
                    source_name=self.source.name,
                    content_type="article",
                    title=title,
                    url=url,
                    published_at=published_at,
                    fetched_at=now,
                    duration_seconds=None,
                    transcript=content,  # Preliminary content from RSS
                    word_count=len(content.split()) if content else 0,
                    status="pending",
                )
                count += 1

            # If we've hit the limit, stop
            if count >= limit:
                break

            # If no entries on this page were within the date range,
            # all remaining pages will be even older — stop paginating
            if not any_in_range:
                print(f"  Page {page}: all entries predate {since}, stopping pagination")
                break

            # Move to next page with a polite delay
            page += 1
            time.sleep(self.PAGE_FETCH_DELAY)

        if page > 1 and count > 0:
            print(f"  Fetched {count} items across {page} page(s) from {self.source.name}")
    
    def _parse_entry_date(self, entry) -> Optional[datetime]:
        """Parse the publication date from an RSS entry."""
        # Try different date fields
        date_fields = ['published_parsed', 'updated_parsed', 'created_parsed']
        
        for field in date_fields:
            parsed = entry.get(field)
            if parsed:
                try:
                    return datetime(*parsed[:6])
                except Exception:
                    pass
        
        # Try string date fields
        for field in ['published', 'updated', 'created']:
            date_str = entry.get(field)
            if date_str:
                try:
                    from dateutil import parser
                    return parser.parse(date_str)
                except Exception:
                    pass
        
        return None
    
    def _extract_entry_content(self, entry) -> str:
        """Extract content from RSS entry."""
        # Try content field first (usually full content)
        if 'content' in entry:
            for content in entry['content']:
                if content.get('type', '') == 'text/html':
                    return self._html_to_text(content.get('value', ''))
        
        # Fall back to summary
        summary = entry.get('summary', '')
        if summary:
            return self._html_to_text(summary)
        
        # Fall back to description
        description = entry.get('description', '')
        if description:
            return self._html_to_text(description)
        
        return ''
    
    def _html_to_text(self, html: str) -> str:
        """Convert HTML to clean text."""
        if not html:
            return ''
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove script and style elements
        for element in soup(['script', 'style', 'nav', 'footer', 'header']):
            element.decompose()
        
        # Get text
        text = soup.get_text(separator=' ')
        
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        return text
    
    def fetch_transcript(self, item: ContentItem) -> Optional[str]:
        """
        Fetch the full article content.
        
        If the RSS content is just a summary, this fetches the full page.
        
        Args:
            item: ContentItem for the article
            
        Returns:
            Full article text, or None if unavailable
        """
        # If we already have substantial content from RSS, use it
        if item.transcript and item.word_count > 500:
            return item.transcript
        
        # Otherwise, try to fetch the full page
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            }
            
            response = requests.get(item.url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                element.decompose()
            
            # Try to find the main article content
            article_content = None
            
            # Common article containers
            selectors = [
                'article',
                '.post-content',
                '.entry-content',
                '.article-content',
                '.post-body',
                'main',
                '[role="main"]',
            ]
            
            for selector in selectors:
                content = soup.select_one(selector)
                if content:
                    article_content = content
                    break
            
            if article_content:
                text = article_content.get_text(separator=' ')
            else:
                # Fall back to body
                text = soup.get_text(separator=' ')
            
            # Clean up
            text = re.sub(r'\s+', ' ', text)
            text = text.strip()
            
            # If we got less than what RSS gave us, use RSS content
            if item.transcript and len(text) < len(item.transcript):
                return item.transcript
            
            return text
            
        except Exception as e:
            print(f"Full article fetch error for {item.title}: {e}")
            # Return whatever we got from RSS
            return item.transcript
    
    def fetch_all(self, since: date = None, limit: int = None, include_transcripts: bool = True, transcript_delay: float = 0) -> Generator[ContentItem, None, None]:
        """
        Fetch all articles with full content.
        
        Overridden to handle RSS articles which may already have content.
        """
        for item in self.fetch_content_list(since=since, limit=limit):
            if include_transcripts:
                # Always try to get full content for articles
                full_content = self.fetch_transcript(item)
                if full_content:
                    item.transcript = full_content
                    item.word_count = len(full_content.split())
                    # Check for paywall content
                    if _is_paywall_content(full_content):
                        item.status = "paywall"
                        item.transcript = None
                        item.word_count = 0
                    else:
                        item.status = "pending"
                elif item.transcript:
                    # Use RSS content if full fetch failed
                    if _is_paywall_content(item.transcript):
                        item.status = "paywall"
                        item.transcript = None
                        item.word_count = 0
                    else:
                        item.status = "pending"
                else:
                    item.status = "no_transcript"
            yield item
