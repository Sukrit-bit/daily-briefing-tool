"""
Content fetchers for the Daily Briefing Tool.

Each fetcher knows how to get content from a specific source type:
- YouTubeFetcher: YouTube channels
- RSSFetcher: RSS feeds (Stratechery, Substack, etc.)
- TwitterFetcher: Twitter/X accounts (future)
"""

from .base import BaseFetcher
from .youtube import YouTubeFetcher
from .rss import RSSFetcher
from ..storage.models import Source


def get_fetcher(source: Source) -> BaseFetcher:
    """
    Factory function to get the appropriate fetcher for a source.
    
    Args:
        source: Source configuration
        
    Returns:
        Appropriate fetcher instance
        
    Raises:
        ValueError: If source type is not supported
    """
    fetchers = {
        'youtube_channel': YouTubeFetcher,
        'rss': RSSFetcher,
    }
    
    fetcher_class = fetchers.get(source.source_type)
    if not fetcher_class:
        raise ValueError(f"Unsupported source type: {source.source_type}")
    
    return fetcher_class(source)


__all__ = [
    'BaseFetcher',
    'YouTubeFetcher', 
    'RSSFetcher',
    'get_fetcher',
]
