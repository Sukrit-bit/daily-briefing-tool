"""
Main summarization logic.

Orchestrates the processing of content items through the LLM:
1. Gets pending content from the database
2. Builds prompts
3. Sends to LLM (Gemini or OpenAI with fallback)
4. Parses responses into ProcessedContent
5. Applies tier calibration based on content signals
6. Saves results
"""

from datetime import datetime
from typing import Optional

from .prompts import build_summarization_prompt, PROMPT_VERSION, BLACKLISTED_PHRASES, ENTITY_CORRECTIONS
from ..fetchers.rss import _is_paywall_content
from ..storage.database import Database
from ..storage.models import ContentItem, ProcessedContent, ConceptExplanation


# Minimum word count to process — skip YouTube Shorts, teasers, etc.
MIN_WORD_COUNT = 500

# Valid values for validation
VALID_TIERS = {"deep_dive", "worth_a_look", "summary_sufficient"}
VALID_FRESHNESS = {"fresh", "evergreen", "stale"}
VALID_CONTENT_TYPES = {
    "market_call", "news_analysis", "industry_trend",
    "framework", "tutorial", "interview", "commentary",
}

# Sources known for high-quality deep content (interviews, research, essays)
# NOTE: greg-isenberg intentionally excluded — his content is tutorials, not deep research
DEEP_SOURCES = {"dwarkesh-patel", "lennys-podcast", "stratechery"}

# Tier calibration thresholds
# LLMs tend to default everything to worth_a_look, so we apply
# signal-based overrides to ensure proper distribution
DEEP_DIVE_MIN_WORDS = 12000      # High bar — most YouTube transcripts are 8-12K and don't warrant deep dive
DEEP_DIVE_LONG_FORM = 18000      # Very long content = deep dive regardless of source
DEEP_DIVE_MIN_INSIGHTS = 5       # Many insights = dense content
SUMMARY_SUFFICIENT_MAX_WORDS = 1500  # Short = limited depth


class Summarizer:
    """
    Processes content items through an LLM for summarization and tagging.
    Supports Gemini, OpenAI, or auto-fallback via LLMClient.
    """

    def __init__(self, db: Database, client=None):
        """
        Args:
            db: Database instance
            client: Any LLM client with generate/estimate_tokens/truncate_for_context
                    (GeminiClient, OpenAIClient, or LLMClient). Defaults to LLMClient(auto).
        """
        self.db = db
        if client is None:
            from .llm_client import LLMClient
            client = LLMClient(provider="auto")
        self.client = client

    def process_item(self, item: ContentItem) -> Optional[ProcessedContent]:
        """
        Process a single content item through the LLM.

        Args:
            item: ContentItem with transcript to process

        Returns:
            ProcessedContent if successful, None if failed
        """
        if not item.transcript:
            print(f"  Skipping (no transcript): {item.title}")
            self.db.update_content_status(item.id, "no_transcript")
            return None

        # Paywall detection — catch stubs that slipped through the fetcher
        if _is_paywall_content(item.transcript):
            print(f"  Skipping (paywall content detected): {item.title}")
            self.db.update_content_status(item.id, "paywall")
            return None

        if item.word_count < MIN_WORD_COUNT:
            print(f"  Skipping (too short: {item.word_count} words < {MIN_WORD_COUNT} min): {item.title}")
            self.db.update_content_status(item.id, "skipped")
            return None

        # Build the prompt
        prompt = build_summarization_prompt(item)

        # Truncate content if it's too long for the context window
        estimated_tokens = self.client.estimate_tokens(prompt)
        if estimated_tokens > self.client.MAX_INPUT_TOKENS:
            # Truncate just the transcript portion and rebuild
            max_transcript_tokens = self.client.MAX_INPUT_TOKENS - self.client.estimate_tokens(
                prompt.replace(item.transcript, "")
            )
            truncated_transcript = self.client.truncate_for_context(
                item.transcript, max_transcript_tokens
            )
            # Rebuild prompt with truncated transcript
            original_transcript = item.transcript
            item.transcript = truncated_transcript
            prompt = build_summarization_prompt(item)
            item.transcript = original_transcript  # Restore original

        # Send to Gemini
        result = self.client.generate(prompt)

        if result is None:
            print(f"  Failed (API error): {item.title}")
            self.db.update_content_status(item.id, "failed")
            return None

        # Parse and validate the response
        processed = self._parse_response(item, result)
        if processed is None:
            print(f"  Failed (parse error): {item.title}")
            self.db.update_content_status(item.id, "failed")
            return None

        # Save to database
        self.db.save_processed(processed)
        self.db.update_content_status(item.id, "processed")

        return processed

    def process_pending(self, limit: int = None, delay: int = 0) -> dict:
        """
        Process all pending content items.

        Args:
            limit: Maximum number of items to process
            delay: Seconds to wait between API calls (helps with rate limits)

        Returns:
            Dict with counts: {processed, failed, skipped, total}
        """
        import time as _time

        items = self.db.get_pending_content(limit=limit)

        stats = {"processed": 0, "failed": 0, "skipped": 0, "total": len(items)}
        last_api_call = 0  # Track when we last made an API call

        for i, item in enumerate(items, 1):
            print(f"\n[{i}/{len(items)}] {item.title[:60]}")

            if not item.transcript:
                print(f"  Skipped (no transcript)")
                self.db.update_content_status(item.id, "no_transcript")
                stats["skipped"] += 1
                continue

            if _is_paywall_content(item.transcript):
                print(f"  Skipped (paywall content)")
                self.db.update_content_status(item.id, "paywall")
                stats["skipped"] += 1
                continue

            if item.word_count < MIN_WORD_COUNT:
                print(f"  Skipped (too short: {item.word_count} words)")
                self.db.update_content_status(item.id, "skipped")
                stats["skipped"] += 1
                continue

            # Respect rate limit delay between API calls
            if delay > 0 and last_api_call > 0:
                elapsed = _time.time() - last_api_call
                if elapsed < delay:
                    wait = delay - elapsed
                    print(f"  Waiting {wait:.0f}s (rate limit delay)...")
                    _time.sleep(wait)

            last_api_call = _time.time()
            result = self.process_item(item)

            if result:
                print(f"  {result.tier_emoji} {result.tier} | {', '.join(result.domains)}")
                stats["processed"] += 1
            else:
                stats["failed"] += 1

        return stats

    def _enforce_blacklist(self, data: dict) -> dict:
        """
        Post-processing: replace blacklisted phrases and fix known entity errors
        in all text fields of the LLM output.

        This is the second line of defense — the prompt tells the LLM to avoid
        these phrases, but LLMs don't always comply. This catches anything
        that slips through.
        """
        text_fields = ["core_summary", "so_what", "tier_rationale"]
        list_fields = ["key_insights"]

        for field in text_fields:
            if field in data and isinstance(data[field], str):
                data[field] = self._clean_text(data[field])

        for field in list_fields:
            if field in data and isinstance(data[field], list):
                data[field] = [
                    self._clean_text(item) if isinstance(item, str) else item
                    for item in data[field]
                ]

        # Also clean concept explanations
        if "concepts_explained" in data and isinstance(data["concepts_explained"], list):
            for concept in data["concepts_explained"]:
                if isinstance(concept, dict) and "explanation" in concept:
                    concept["explanation"] = self._clean_text(concept["explanation"])

        return data

    @staticmethod
    def _clean_text(text: str) -> str:
        """Apply blacklist replacements and entity corrections to a string."""
        import re

        for phrase, replacement in BLACKLISTED_PHRASES.items():
            pattern = re.compile(re.escape(phrase), re.IGNORECASE)
            text = pattern.sub(replacement, text)

        for wrong, correct in ENTITY_CORRECTIONS.items():
            text = text.replace(wrong, correct)

        # Clean up double spaces left by removals
        text = re.sub(r'  +', ' ', text)
        # Clean up orphaned punctuation from removals (e.g., "; ;" or ", ,")
        text = re.sub(r'[;,]\s*[;,]', ',', text)
        text = text.strip()

        return text

    def _calibrate_tier(self, item: ContentItem, llm_tier: str, content_type: str,
                        key_insights: list, freshness: str) -> tuple:
        """
        Apply signal-based tier calibration to correct LLM's tendency to
        default everything to worth_a_look.

        Uses content signals (word count, source, content type, insight density)
        to override the LLM tier when there's strong evidence.

        Returns:
            (tier, rationale_suffix) — the calibrated tier and an explanation
        """
        tier = llm_tier
        reason = ""

        # --- Promote to deep_dive ---
        # Very long content (15K+) is almost certainly deep enough to warrant the original
        if (item.word_count >= DEEP_DIVE_LONG_FORM
                and tier != "deep_dive"):
            tier = "deep_dive"
            reason = f" [Calibrated: {item.word_count:,}-word long-form]"

        # Long-form content from quality sources is almost always worth a deep dive
        elif (item.word_count >= DEEP_DIVE_MIN_WORDS
                and item.source_id in DEEP_SOURCES
                and tier != "deep_dive"):
            tier = "deep_dive"
            reason = f" [Calibrated: {item.word_count:,} words from {item.source_id}]"

        # Long-form interviews are worth the original
        elif (item.word_count >= DEEP_DIVE_MIN_WORDS
              and content_type == "interview"
              and tier != "deep_dive"):
            tier = "deep_dive"
            reason = f" [Calibrated: {item.word_count:,}-word interview]"

        # Long content (8K+) with many insights should be deep_dive
        elif (item.word_count >= DEEP_DIVE_MIN_WORDS
              and len(key_insights) >= DEEP_DIVE_MIN_INSIGHTS
              and tier != "deep_dive"):
            tier = "deep_dive"
            reason = f" [Calibrated: {item.word_count:,} words, {len(key_insights)} insights]"

        # --- Demote to summary_sufficient ---
        # Very short content can't have much depth (even if LLM says "evergreen")
        elif (item.word_count <= SUMMARY_SUFFICIENT_MAX_WORDS
              and tier != "summary_sufficient"):
            tier = "summary_sufficient"
            reason = f" [Calibrated: only {item.word_count} words]"

        # Stale content that's not evergreen should be summary_sufficient at best
        elif freshness == "stale" and tier == "deep_dive":
            tier = "worth_a_look"
            reason = " [Calibrated: stale content demoted]"

        return tier, reason

    def _parse_response(self, item: ContentItem, data: dict) -> Optional[ProcessedContent]:
        """
        Parse and validate the LLM response into a ProcessedContent object.

        Args:
            item: The original ContentItem
            data: Parsed JSON from the LLM

        Returns:
            ProcessedContent if valid, None if parsing fails
        """
        try:
            # Post-processing: enforce blacklist on LLM output before parsing
            data = self._enforce_blacklist(data)

            # Extract and validate core fields
            core_summary = data.get("core_summary", "")
            if not core_summary:
                print(f"  Missing core_summary in response")
                return None

            key_insights = data.get("key_insights", [])
            if not isinstance(key_insights, list):
                key_insights = [str(key_insights)]

            # Parse concepts
            concepts_raw = data.get("concepts_explained", [])
            concepts = []
            if isinstance(concepts_raw, list):
                for c in concepts_raw:
                    if isinstance(c, dict) and "term" in c and "explanation" in c:
                        concepts.append(ConceptExplanation(
                            term=c["term"],
                            explanation=c["explanation"],
                        ))

            so_what = data.get("so_what", "")

            # Extract topic tags (dynamic, no validation against fixed set)
            topic_tags_raw = data.get("topic_tags", data.get("domains", []))
            if isinstance(topic_tags_raw, str):
                topic_tags_raw = [topic_tags_raw]
            # Normalize: lowercase, strip whitespace, limit to 3
            topic_tags = [t.strip().lower() for t in topic_tags_raw if isinstance(t, str) and t.strip()][:3]
            if not topic_tags:
                topic_tags = ["general"]  # Fallback

            # Validate content type
            content_type = data.get("content_type", "commentary")
            if content_type not in VALID_CONTENT_TYPES:
                content_type = "commentary"

            # Validate freshness
            freshness = data.get("freshness", "fresh")
            if freshness not in VALID_FRESHNESS:
                freshness = "fresh"

            # Validate tier from LLM
            llm_tier = data.get("tier", "summary_sufficient")
            if llm_tier not in VALID_TIERS:
                llm_tier = "summary_sufficient"

            tier_rationale = data.get("tier_rationale", "")

            # Apply signal-based tier calibration
            tier, calibration_note = self._calibrate_tier(
                item, llm_tier, content_type, key_insights, freshness
            )
            if calibration_note:
                tier_rationale += calibration_note

            # Determine if this is backlog content
            days_old = (datetime.now() - item.published_at).days
            is_backlog = days_old > 14  # More than 2 weeks old = backlog

            return ProcessedContent(
                content_id=item.id,
                core_summary=core_summary,
                key_insights=key_insights,
                concepts_explained=concepts,
                so_what=so_what,
                domains=topic_tags,
                content_category=content_type,
                freshness=freshness,
                tier=tier,
                tier_rationale=tier_rationale,
                processed_at=datetime.now(),
                prompt_version=PROMPT_VERSION,
                model_used=self.client.model_name,
                is_backlog=is_backlog,
                delivered=False,
                delivered_at=None,
            )

        except Exception as e:
            print(f"  Parse error: {e}")
            return None
