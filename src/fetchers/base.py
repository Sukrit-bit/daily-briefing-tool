"""
Base fetcher abstract class.

All content fetchers (YouTube, RSS, Twitter) inherit from this
and implement the same interface. This allows the rest of the system
to treat all sources uniformly.
"""

from abc import ABC, abstractmethod
import time
from datetime import date
from typing import Generator, Optional

from ..storage.models import ContentItem, Source


class BaseFetcher(ABC):
    """
    Abstract base class for content fetchers.
    
    Each fetcher knows how to:
    1. Get a list of content (videos, articles) from a source
    2. Extract the full text/transcript for each item
    
    Subclasses must implement:
    - fetch_content_list(): Get metadata for all content items
    - fetch_transcript(): Get the full text for a specific item
    """
    
    def __init__(self, source: Source):
        """
        Initialize fetcher with a source configuration.
        
        Args:
            source: Source configuration (from sources.yaml)
        """
        self.source = source
    
    @abstractmethod
    def fetch_content_list(self, since: date = None, limit: int = None) -> Generator[ContentItem, None, None]:
        """
        Fetch list of content items from the source.
        
        This should yield ContentItem objects with metadata populated,
        but transcript may be None (fetched separately for efficiency).
        
        Args:
            since: Only fetch content published after this date
            limit: Maximum number of items to fetch
            
        Yields:
            ContentItem objects (transcript may be None)
        """
        pass
    
    @abstractmethod
    def fetch_transcript(self, item: ContentItem) -> Optional[str]:
        """
        Fetch the full transcript/text for a content item.
        
        Args:
            item: ContentItem to fetch transcript for
            
        Returns:
            Full transcript/text, or None if unavailable
        """
        pass
    
    def fetch_all(self, since: date = None, limit: int = None, include_transcripts: bool = True, transcript_delay: float = 2.0) -> Generator[ContentItem, None, None]:
        """
        Fetch all content with transcripts.

        This is the main entry point for fetching. It:
        1. Gets the list of content
        2. Fetches transcript for each item (with delay to avoid rate limits)
        3. Yields complete ContentItem objects

        Args:
            since: Only fetch content published after this date
            limit: Maximum number of items to fetch
            include_transcripts: If True, fetch transcripts (slower but complete)
            transcript_delay: Seconds to wait between transcript fetches
                to avoid YouTube rate limiting (default 2.0)

        Yields:
            Complete ContentItem objects with transcripts
        """
        is_first = True
        for item in self.fetch_content_list(since=since, limit=limit):
            if include_transcripts:
                # Throttle transcript fetches to avoid YouTube rate limiting
                if not is_first and transcript_delay > 0:
                    time.sleep(transcript_delay)
                is_first = False

                transcript = self.fetch_transcript(item)
                if transcript:
                    item.transcript = transcript
                    item.word_count = len(transcript.split())
                    item.status = "pending"
                else:
                    item.status = "no_transcript"
            yield item
    
    @property
    def source_id(self) -> str:
        return self.source.id
    
    @property
    def source_name(self) -> str:
        return self.source.name
