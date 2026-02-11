from __future__ import annotations

"""
YouTube channel fetcher.

Fetches videos from YouTube channels and extracts transcripts
using the youtube-transcript-api library.

Supports three video discovery strategies (in priority order):
1. YouTube Data API v3 (requires YOUTUBE_API_KEY) — reaches full channel history
2. RSS feed (~15 most recent videos)
3. Page scraping (~30 most recent videos)
"""

import os
import re
import json
import time
import requests
from datetime import datetime, date
from typing import Generator, Optional
from urllib.parse import urlparse, parse_qs

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

from .base import BaseFetcher
from ..storage.models import ContentItem, Source

# YouTube Data API v3 base URL
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeFetcher(BaseFetcher):
    """
    Fetches videos and transcripts from YouTube channels.

    Uses:
    - YouTube Data API v3 for video discovery (preferred, requires API key)
    - YouTube's public RSS feed or page scraping as fallback
    - youtube-transcript-api for transcripts (free, no API key needed)
    """

    # Minimum duration to consider a video (filters out Shorts, clips, teasers)
    MIN_VIDEO_DURATION_SECONDS = 120  # 2 minutes — anything shorter is likely a Short

    # YouTube channel URL patterns
    CHANNEL_PATTERNS = [
        r'youtube\.com/@([^/]+)',           # youtube.com/@handle
        r'youtube\.com/channel/([^/]+)',    # youtube.com/channel/UC...
        r'youtube\.com/c/([^/]+)',          # youtube.com/c/name
        r'youtube\.com/user/([^/]+)',       # youtube.com/user/name
    ]

    # Delay between YouTube Data API calls (seconds) to be respectful
    API_CALL_DELAY = 0.5

    def __init__(self, source: Source):
        super().__init__(source)
        self.channel_id = self._extract_channel_identifier()

    def _extract_channel_identifier(self) -> str:
        """Extract channel handle or ID from URL."""
        url = self.source.url
        for pattern in self.CHANNEL_PATTERNS:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        raise ValueError(f"Could not parse YouTube channel URL: {url}")

    @staticmethod
    def _is_youtube_short_url(url: str) -> bool:
        """Check if URL is a YouTube Shorts URL."""
        return '/shorts/' in url

    # ------------------------------------------------------------------
    # YouTube Data API v3 methods
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_iso8601_duration(duration: str) -> int:
        """
        Parse ISO 8601 duration string from YouTube API to seconds.

        Examples:
            "PT1H23M45S" -> 5025
            "PT45M30S"   -> 2730
            "PT5M"       -> 300
            "PT30S"      -> 30
            "P0D"        -> 0  (live streams sometimes)
        """
        if not duration:
            return 0

        match = re.match(
            r'PT?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?',
            duration,
        )
        if not match:
            return 0

        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds

    def _resolve_channel_id(self, api_key: str) -> Optional[str]:
        """
        Resolve a channel handle (e.g. 'DwarkeshPatel') or channel ID to a
        canonical UC... channel ID using the YouTube Data API.

        Returns:
            Channel ID string (e.g. 'UCM1_dL...'), or None on failure.
        """
        identifier = self.channel_id  # From _extract_channel_identifier()

        # If it already looks like a channel ID, return as-is
        if identifier.startswith("UC") and len(identifier) == 24:
            return identifier

        # Use forHandle parameter (works for @handle URLs)
        params = {
            "part": "id,contentDetails",
            "forHandle": identifier,
            "key": api_key,
        }
        try:
            resp = requests.get(
                f"{YOUTUBE_API_BASE}/channels",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            items = data.get("items", [])
            if items:
                return items[0]["id"]

            # forHandle didn't work — try forUsername as fallback
            params.pop("forHandle")
            params["forUsername"] = identifier
            resp = requests.get(
                f"{YOUTUBE_API_BASE}/channels",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            if items:
                return items[0]["id"]

        except Exception as e:
            print(f"  API: Failed to resolve channel ID for {identifier}: {e}")

        return None

    def _get_channel_videos_via_api(self, limit: int = 500) -> list[dict]:
        """
        Get channel videos using YouTube Data API v3.

        Strategy:
        1. Resolve channel handle -> channel ID (UC...)
        2. Derive uploads playlist ID (UU...)
        3. Paginate playlistItems.list to collect video IDs + titles + dates
        4. Batch-fetch video durations via videos.list (50 per call)
        5. Filter out Shorts (< MIN_VIDEO_DURATION_SECONDS)

        Quota cost:
        - channels.list: 1 unit
        - playlistItems.list: 1 unit per page (50 items)
        - videos.list: 1 unit per call (50 IDs per call)
        - Total for 200 videos: ~1 + 4 + 4 = 9 units

        Args:
            limit: Maximum number of videos to return.

        Returns:
            List of dicts with keys: video_id, title, url, published,
            duration_seconds. Returns empty list if API key is missing
            or any API call fails.
        """
        api_key = os.getenv("YOUTUBE_API_KEY")
        if not api_key:
            return []

        # Step 1: Resolve channel ID
        channel_id = self._resolve_channel_id(api_key)
        if not channel_id:
            print(f"  API: Could not resolve channel ID for {self.source.name}")
            return []

        # Step 2: Derive uploads playlist ID (UC... -> UU...)
        uploads_playlist_id = "UU" + channel_id[2:]
        print(f"  API: Fetching videos from playlist {uploads_playlist_id} for {self.source.name}")

        # Step 3: Paginate through playlistItems to collect video metadata
        raw_videos = []  # List of {video_id, title, published}
        next_page_token = None

        while len(raw_videos) < limit:
            params = {
                "part": "snippet",
                "playlistId": uploads_playlist_id,
                "maxResults": 50,
                "key": api_key,
            }
            if next_page_token:
                params["pageToken"] = next_page_token

            try:
                resp = requests.get(
                    f"{YOUTUBE_API_BASE}/playlistItems",
                    params=params,
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  API: playlistItems request failed: {e}")
                break

            items = data.get("items", [])
            if not items:
                break

            for item in items:
                snippet = item.get("snippet", {})
                video_id = snippet.get("resourceId", {}).get("videoId")
                if not video_id:
                    continue

                raw_videos.append({
                    "video_id": video_id,
                    "title": snippet.get("title", ""),
                    "published": snippet.get("publishedAt", ""),
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                })

                if len(raw_videos) >= limit:
                    break

            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break

            # Throttle between pages
            time.sleep(self.API_CALL_DELAY)

        print(f"  API: Found {len(raw_videos)} videos in uploads playlist")

        if not raw_videos:
            return []

        # Step 4: Batch-fetch durations via videos.list (50 IDs per call)
        # Build a lookup: video_id -> duration_seconds
        duration_map = {}
        video_ids = [v["video_id"] for v in raw_videos]

        for batch_start in range(0, len(video_ids), 50):
            batch = video_ids[batch_start:batch_start + 50]
            params = {
                "part": "contentDetails",
                "id": ",".join(batch),
                "key": api_key,
            }

            try:
                resp = requests.get(
                    f"{YOUTUBE_API_BASE}/videos",
                    params=params,
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  API: videos.list request failed for batch at {batch_start}: {e}")
                continue

            for item in data.get("items", []):
                vid = item["id"]
                iso_duration = item.get("contentDetails", {}).get("duration", "")
                duration_map[vid] = self._parse_iso8601_duration(iso_duration)

            # Throttle between batches
            if batch_start + 50 < len(video_ids):
                time.sleep(self.API_CALL_DELAY)

        # Step 5: Merge durations and filter Shorts
        videos = []
        shorts_filtered = 0

        for v in raw_videos:
            vid = v["video_id"]
            duration = duration_map.get(vid)

            # Filter out Shorts / very short videos
            if duration is not None and duration < self.MIN_VIDEO_DURATION_SECONDS:
                shorts_filtered += 1
                continue

            # Filter out Shorts by URL pattern (shouldn't happen from API, but be safe)
            if self._is_youtube_short_url(v.get("url", "")):
                shorts_filtered += 1
                continue

            videos.append({
                "video_id": vid,
                "title": v["title"],
                "url": v["url"],
                "published": v["published"],
                "duration_seconds": duration,
            })

        if shorts_filtered > 0:
            print(f"  API: Filtered {shorts_filtered} Shorts (< {self.MIN_VIDEO_DURATION_SECONDS // 60}m)")

        print(f"  API: Returning {len(videos)} videos after filtering")
        return videos

    # ------------------------------------------------------------------
    # RSS + scrape methods (fallback)
    # ------------------------------------------------------------------

    def _get_channel_videos_via_rss(self, limit: int = 50) -> list[dict]:
        """
        Get recent videos via YouTube's RSS feed.

        Note: RSS only returns the ~15 most recent videos.
        For more, we need to scrape or use the API.
        """
        # First, we need to get the channel ID (UC...) from the handle
        # YouTube RSS feeds require the channel ID, not the handle

        # Try to get channel page and extract channel ID
        channel_url = self.source.url
        if not channel_url.endswith('/videos'):
            channel_url = channel_url.rstrip('/') + '/videos'

        try:
            response = requests.get(channel_url, timeout=30)
            response.raise_for_status()

            # Extract channel ID from page
            # Look for "channelId":"UC..." in the page source
            channel_id_match = re.search(r'"channelId":"(UC[^"]+)"', response.text)
            if not channel_id_match:
                # Try alternate pattern
                channel_id_match = re.search(r'channel_id=([^"&]+)', response.text)

            if channel_id_match:
                channel_id = channel_id_match.group(1)
                rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

                rss_response = requests.get(rss_url, timeout=30)
                rss_response.raise_for_status()

                # Parse RSS (simple regex extraction, no feedparser dependency here)
                videos = []
                entries = re.findall(r'<entry>(.*?)</entry>', rss_response.text, re.DOTALL)

                for entry in entries[:limit]:
                    video_id_match = re.search(r'<yt:videoId>([^<]+)</yt:videoId>', entry)
                    title_match = re.search(r'<title>([^<]+)</title>', entry)
                    published_match = re.search(r'<published>([^<]+)</published>', entry)

                    if video_id_match and title_match:
                        videos.append({
                            'video_id': video_id_match.group(1),
                            'title': title_match.group(1),
                            'published': published_match.group(1) if published_match else None,
                            'url': f"https://www.youtube.com/watch?v={video_id_match.group(1)}"
                        })

                return videos

        except Exception as e:
            print(f"RSS fetch failed for {self.source.name}: {e}")

        return []

    def _get_channel_videos_via_scrape(self, limit: int = 50) -> list[dict]:
        """
        Get videos by scraping the channel's videos page.

        This can get more videos than RSS but is more fragile.
        """
        channel_url = self.source.url
        if not channel_url.endswith('/videos'):
            channel_url = channel_url.rstrip('/') + '/videos'

        try:
            # Use a browser-like user agent
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
            }

            response = requests.get(channel_url, headers=headers, timeout=30)
            response.raise_for_status()

            videos = []

            # YouTube embeds video data as JSON in the page
            # Look for the initial data JSON
            json_match = re.search(r'var ytInitialData = ({.*?});</script>', response.text)
            if not json_match:
                json_match = re.search(r'ytInitialData\s*=\s*({.*?});</script>', response.text)

            if json_match:
                try:
                    data = json.loads(json_match.group(1))

                    # Navigate the nested structure to find videos
                    # This structure can change, so we search recursively
                    video_items = self._extract_video_items(data)

                    for item in video_items[:limit]:
                        if item.get('video_id'):
                            videos.append(item)

                except json.JSONDecodeError:
                    pass

            # Fallback: simple regex extraction
            if not videos:
                video_ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', response.text)
                titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"\}\]', response.text)

                seen = set()
                for vid in video_ids:
                    if vid not in seen and len(videos) < limit:
                        seen.add(vid)
                        videos.append({
                            'video_id': vid,
                            'title': titles[len(videos)] if len(videos) < len(titles) else f"Video {vid}",
                            'url': f"https://www.youtube.com/watch?v={vid}",
                            'published': None
                        })

            return videos

        except Exception as e:
            print(f"Scrape failed for {self.source.name}: {e}")
            return []

    def _extract_video_items(self, data: dict, depth: int = 0) -> list[dict]:
        """Recursively extract video items from YouTube's JSON structure."""
        if depth > 20:  # Prevent infinite recursion
            return []

        videos = []

        if isinstance(data, dict):
            # Check if this is a video renderer
            if 'videoId' in data and 'title' in data:
                title = data.get('title', {})
                if isinstance(title, dict):
                    title_text = title.get('runs', [{}])[0].get('text', '') or title.get('simpleText', '')
                else:
                    title_text = str(title)

                # Get published time
                published_text = data.get('publishedTimeText', {}).get('simpleText', '')

                # Get duration
                duration_text = data.get('lengthText', {}).get('simpleText', '')
                duration_seconds = self._parse_duration(duration_text)

                # Filter out Shorts / very short videos when duration is known
                if duration_seconds is not None and duration_seconds < self.MIN_VIDEO_DURATION_SECONDS:
                    return videos  # Skip this video entirely

                videos.append({
                    'video_id': data['videoId'],
                    'title': title_text,
                    'url': f"https://www.youtube.com/watch?v={data['videoId']}",
                    'published_text': published_text,
                    'published': None,  # We'll parse this later
                    'duration_seconds': duration_seconds,
                })

            # Recurse into nested structures
            for key, value in data.items():
                videos.extend(self._extract_video_items(value, depth + 1))

        elif isinstance(data, list):
            for item in data:
                videos.extend(self._extract_video_items(item, depth + 1))

        return videos

    def _parse_duration(self, duration_text: str) -> Optional[int]:
        """Parse duration string (e.g., '1:23:45' or '45:30') to seconds."""
        if not duration_text:
            return None

        parts = duration_text.split(':')
        try:
            if len(parts) == 3:  # H:MM:SS
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:  # MM:SS
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 1:  # SS
                return int(parts[0])
        except ValueError:
            pass
        return None

    def _parse_relative_date(self, text: str) -> Optional[datetime]:
        """
        Parse relative date strings like '2 days ago', '1 week ago'.
        Returns approximate datetime.
        """
        if not text:
            return None

        from datetime import timedelta
        now = datetime.now()

        text = text.lower().strip()

        patterns = [
            (r'(\d+)\s*second', lambda m: now - timedelta(seconds=int(m.group(1)))),
            (r'(\d+)\s*minute', lambda m: now - timedelta(minutes=int(m.group(1)))),
            (r'(\d+)\s*hour', lambda m: now - timedelta(hours=int(m.group(1)))),
            (r'(\d+)\s*day', lambda m: now - timedelta(days=int(m.group(1)))),
            (r'(\d+)\s*week', lambda m: now - timedelta(weeks=int(m.group(1)))),
            (r'(\d+)\s*month', lambda m: now - timedelta(days=int(m.group(1)) * 30)),
            (r'(\d+)\s*year', lambda m: now - timedelta(days=int(m.group(1)) * 365)),
        ]

        for pattern, converter in patterns:
            match = re.search(pattern, text)
            if match:
                return converter(match)

        return None

    def _enrich_durations_via_ytdlp(self, videos: list) -> list:
        """
        Batch-enrich videos missing duration_seconds using yt-dlp Python API.

        Uses yt-dlp's extract_info with download=False for fast,
        metadata-only extraction.
        """
        import yt_dlp

        to_enrich = [v for v in videos if not v.get('duration_seconds')]
        if not to_enrich:
            return videos

        print(f"  Enriching durations for {len(to_enrich)} videos via yt-dlp...")
        enriched = 0

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'socket_timeout': 10,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            for video in to_enrich:
                url = video.get('url', '')
                try:
                    info = ydl.extract_info(url, download=False)
                    duration = info.get('duration')
                    if duration:
                        video['duration_seconds'] = int(duration)
                        enriched += 1
                except Exception as e:
                    print(f"    yt-dlp failed for {video.get('title', url)[:50]}: {e}")

        print(f"  Enriched {enriched}/{len(to_enrich)} durations")
        return videos

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def fetch_content_list(self, since: date = None, limit: int = None) -> Generator[ContentItem, None, None]:
        """
        Fetch list of videos from the YouTube channel.

        Tries YouTube Data API v3 first (if YOUTUBE_API_KEY is set).
        Falls back to RSS + scraping if the API key is missing or the
        API call fails.

        When using the API path, yt-dlp duration enrichment is SKIPPED
        because the API already provides precise durations.

        Args:
            since: Only fetch videos published after this date
            limit: Maximum number of videos to fetch

        Yields:
            ContentItem objects (without transcripts)
        """
        if limit is None:
            limit = 100  # Default limit

        if since is None:
            since = self.source.fetch_since

        # --- Strategy selection ---
        used_api = False
        videos = []

        # Prefer YouTube Data API v3 when key is available
        if os.getenv("YOUTUBE_API_KEY"):
            try:
                videos = self._get_channel_videos_via_api(limit=limit)
                if videos:
                    used_api = True
                    print(f"  Using YouTube Data API v3 ({len(videos)} videos)")
            except Exception as e:
                print(f"  API failed for {self.source.name}, falling back to RSS/scrape: {e}")
                videos = []

        # Fallback: RSS + scraping
        if not used_api:
            print(f"  Using RSS + scrape fallback for {self.source.name}")
            # Try RSS first (faster, more reliable, but limited to ~15 videos)
            videos = self._get_channel_videos_via_rss(limit=limit)

            # If RSS didn't return enough, try scraping
            if len(videos) < min(limit, 20):
                scraped = self._get_channel_videos_via_scrape(limit=limit)
                # Merge, preferring scraped data (has more metadata)
                seen_ids = {v['video_id'] for v in videos}
                for v in scraped:
                    if v['video_id'] not in seen_ids:
                        videos.append(v)
                        seen_ids.add(v['video_id'])

        # Deduplicate and sort by published date (newest first)
        seen = set()
        unique_videos = []
        for v in videos:
            if v['video_id'] not in seen:
                seen.add(v['video_id'])
                unique_videos.append(v)

        # Filter out Shorts by URL pattern (before transcript/enrichment work)
        before_url_filter = len(unique_videos)
        unique_videos = [v for v in unique_videos if not self._is_youtube_short_url(v.get('url', ''))]
        url_filtered = before_url_filter - len(unique_videos)
        if url_filtered > 0:
            print(f"  Filtered {url_filtered} YouTube Shorts by URL pattern")

        # Only enrich durations via yt-dlp for the fallback path.
        # The API path already has precise durations from videos.list.
        if not used_api:
            unique_videos = self._enrich_durations_via_ytdlp(unique_videos[:limit])

            # Second filter pass: catch Shorts missed by scraping (duration now known via yt-dlp)
            before_duration_filter = len(unique_videos)
            unique_videos = [v for v in unique_videos if not v.get('duration_seconds') or v['duration_seconds'] >= self.MIN_VIDEO_DURATION_SECONDS]
            duration_filtered = before_duration_filter - len(unique_videos)
            if duration_filtered > 0:
                print(f"  Filtered {duration_filtered} YouTube Shorts (< {self.MIN_VIDEO_DURATION_SECONDS // 60}m)")

        # Convert to ContentItems and filter by date
        now = datetime.now()
        for video in unique_videos[:limit]:
            # Parse published date
            published_at = None
            if video.get('published'):
                try:
                    # ISO format from RSS or API
                    published_at = datetime.fromisoformat(video['published'].replace('Z', '+00:00'))
                except Exception:
                    pass

            if not published_at and video.get('published_text'):
                published_at = self._parse_relative_date(video['published_text'])

            if not published_at:
                published_at = now  # Assume recent if we can't parse

            # Remove timezone for consistency
            if published_at.tzinfo:
                published_at = published_at.replace(tzinfo=None)

            # Filter by date
            if since and published_at.date() < since:
                continue

            content_id = ContentItem.generate_id(self.source.id, video['url'])

            yield ContentItem(
                id=content_id,
                source_id=self.source.id,
                source_name=self.source.name,
                content_type="video",
                title=video['title'],
                url=video['url'],
                published_at=published_at,
                fetched_at=now,
                duration_seconds=video.get('duration_seconds'),
                transcript=None,  # Fetched separately
                word_count=0,
                status="pending",
            )

    # ------------------------------------------------------------------
    # Transcript methods
    # ------------------------------------------------------------------

    def fetch_transcript(self, item: ContentItem) -> Optional[str]:
        """
        Fetch transcript for a YouTube video.

        Uses youtube-transcript-api which extracts transcripts
        without requiring an API key.

        Args:
            item: ContentItem for the video

        Returns:
            Full transcript text, or None if unavailable
        """
        # Extract video ID from URL
        video_id = self._extract_video_id(item.url)
        if not video_id:
            print(f"Could not extract video ID from: {item.url}")
            return None

        try:
            # youtube-transcript-api v1.x: instantiate, then fetch
            api = YouTubeTranscriptApi()

            # Try to find the best transcript via list()
            transcript_list = api.list(video_id)

            # Prefer manual English, fall back to auto-generated
            transcript_meta = None
            try:
                transcript_meta = transcript_list.find_manually_created_transcript(['en'])
            except Exception:
                pass

            if transcript_meta is None:
                try:
                    transcript_meta = transcript_list.find_generated_transcript(['en'])
                except Exception:
                    pass

            if transcript_meta is not None:
                # Fetch the actual transcript data
                fetched = transcript_meta.fetch()
                full_text = ' '.join([snippet.text for snippet in fetched.snippets])
            else:
                # Last resort: just fetch directly (gets default transcript)
                fetched = api.fetch(video_id)
                full_text = ' '.join([snippet.text for snippet in fetched.snippets])

            # Clean up the text
            full_text = self._clean_transcript(full_text)

            return full_text

        except TranscriptsDisabled:
            print(f"Transcripts disabled for: {item.title}")
            return None
        except NoTranscriptFound:
            print(f"No transcript found for: {item.title}")
            return None
        except VideoUnavailable:
            print(f"Video unavailable: {item.title}")
            return None
        except Exception as e:
            print(f"Transcript error for {item.title}: {e}")
            return None

    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from YouTube URL."""
        # Handle various URL formats
        patterns = [
            r'youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
            r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
            r'youtu\.be/([a-zA-Z0-9_-]{11})',
            r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
            r'youtube\.com/v/([a-zA-Z0-9_-]{11})',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        # Try parsing as URL with query params
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if 'v' in params:
            return params['v'][0]

        return None

    def _clean_transcript(self, text: str) -> str:
        """Clean up transcript text."""
        # Remove multiple spaces
        text = re.sub(r'\s+', ' ', text)

        # Remove [Music], [Applause], etc.
        text = re.sub(r'\[.*?\]', '', text)

        # Fix common transcript issues
        text = text.replace('\n', ' ')
        text = text.strip()

        return text
