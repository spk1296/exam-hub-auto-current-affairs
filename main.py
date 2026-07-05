#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ExamHub India Current Affairs Automation
==========================================

Fetches India's latest current affairs from NewsData.io, filters out
irrelevant/junk content, removes duplicates, generates short summaries,
extracts important keywords, maps each article to every relevant
competitive exam, and uploads everything to Firebase Realtime Database.

Designed to run as a scheduled GitHub Action, but works fine locally too
as long as the three required environment variables are set:

    NEWSDATA_API_KEY
    FIREBASE_SERVICE_ACCOUNT   (raw JSON string of the service account key)
    FIREBASE_DATABASE_URL

Author: ExamHub India
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import requests
from dateutil import parser as date_parser

try:
    import firebase_admin
    from firebase_admin import credentials, db
except ImportError:  # pragma: no cover
    firebase_admin = None


# ======================================================================
# LOGGING SETUP
# ======================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("ExamHub")


# ======================================================================
# CONFIGURATION
# ======================================================================

NEWSDATA_API_KEY = os.environ.get("NEWSDATA_API_KEY", "").strip()
FIREBASE_SERVICE_ACCOUNT = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
FIREBASE_DATABASE_URL = os.environ.get("FIREBASE_DATABASE_URL", "").strip()

NEWSDATA_BASE_URL = "https://newsdata.io/api/1/news"

NEWS_CATEGORIES = [
    "top",
    "politics",
    "business",
    "science",
    "technology",
    "education",
    "sports",
    "world",
]

COUNTRY = "in"
LANGUAGE = "en"

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 4
REQUEST_TIMEOUT_SECONDS = 20

MAX_ARTICLES_PER_EXAM = 100
FIREBASE_ROOT_NODE = "current_affairs"

ALL_EXAMS_NODE = "All Exams"

# ----------------------------------------------------------------------
# Supported exams grouped into logical categories.
# ----------------------------------------------------------------------

EXAM_CATEGORY_MEMBERS: Dict[str, List[str]] = {
    "upsc": ["UPSC"],
    "state": ["BPSC", "Bihar Police", "Bihar SI", "State PSC"],
    "ssc": ["SSC CGL", "SSC CHSL", "SSC GD"],
    "railway": ["Railway NTPC", "Railway Group D", "RRB ALP", "RRB JE"],
    "banking": [
        "IBPS PO",
        "IBPS Clerk",
        "SBI PO",
        "SBI Clerk",
        "RBI Grade B",
        "NABARD",
        "LIC AAO",
    ],
    "social_security": ["EPFO", "ESIC"],
    "teaching": ["CTET", "STET", "UGC NET", "CSIR NET"],
    "defence": ["NDA", "CDS", "AFCAT", "CAPF"],
    "engineering": ["JEE Main", "JEE Advanced", "GATE", "IES"],
    "medical": ["NEET UG", "NEET PG"],
    "law": ["CLAT", "AILET"],
    "management": ["CAT", "MAT", "XAT", "GMAT", "CUET UG", "CUET PG"],
}

ALL_EXAM_NODES: List[str] = sorted(
    {exam for members in EXAM_CATEGORY_MEMBERS.values() for exam in members}
) + [ALL_EXAMS_NODE]

# ----------------------------------------------------------------------
# Topic keyword -> exam category mapping. Keys are lowercase phrases that
# are searched for inside the article title + description. Values are
# category keys from EXAM_CATEGORY_MEMBERS above.
# ----------------------------------------------------------------------

TOPIC_EXAM_MAP: Dict[str, List[str]] = {
    "government scheme": ["upsc", "state", "banking", "ssc"],
    "government policy": ["upsc", "state", "banking", "ssc"],
    "government policies": ["upsc", "state", "banking", "ssc"],
    "cabinet decision": ["upsc", "state"],
    "parliament": ["upsc", "state"],
    "rajya sabha": ["upsc", "state"],
    "lok sabha": ["upsc", "state"],
    "supreme court": ["upsc", "law", "state"],
    "high court": ["upsc", "law", "state"],
    "election commission": ["upsc", "state"],
    "constitution": ["upsc", "law"],
    "judiciary": ["upsc", "law"],
    "reserve bank of india": ["banking", "upsc"],
    " rbi ": ["banking", "upsc"],
    "sebi": ["banking", "upsc"],
    "nabard": ["banking", "upsc"],
    "budget": ["upsc", "banking", "ssc", "state"],
    "economy": ["upsc", "banking", "ssc"],
    "economic": ["upsc", "banking", "ssc"],
    "gdp": ["upsc", "banking"],
    "inflation": ["upsc", "banking"],
    "banking": ["banking", "upsc"],
    "finance": ["banking", "upsc"],
    "agriculture": ["upsc", "state", "banking"],
    "science": ["engineering", "upsc", "ssc"],
    "technology": ["engineering", "upsc", "ssc"],
    "artificial intelligence": ["engineering", "upsc"],
    " ai ": ["engineering", "upsc"],
    "cyber security": ["engineering", "upsc", "defence"],
    "cybersecurity": ["engineering", "upsc", "defence"],
    "space mission": ["engineering", "upsc", "defence"],
    "isro": ["engineering", "upsc", "defence"],
    "nasa": ["engineering", "upsc"],
    "drdo": ["defence", "upsc", "engineering"],
    "defence": ["defence", "upsc"],
    "indian army": ["defence", "upsc"],
    "indian navy": ["defence", "upsc"],
    "indian air force": ["defence", "upsc"],
    "missile": ["defence", "upsc"],
    "military exercise": ["defence", "upsc"],
    "international relations": ["upsc"],
    "united nations": ["upsc"],
    "world health organization": ["upsc"],
    "unesco": ["upsc"],
    "imf": ["upsc", "banking"],
    "world bank": ["upsc", "banking"],
    "g20": ["upsc"],
    "brics": ["upsc"],
    "shanghai cooperation organisation": ["upsc"],
    "award": ["upsc", "ssc", "banking", "railway", "state"],
    "appointment": ["upsc", "ssc", "banking"],
    "appointed": ["upsc", "ssc", "banking"],
    "report released": ["upsc", "ssc", "banking"],
    "index ranking": ["upsc", "ssc", "banking"],
    "environment": ["upsc", "state"],
    "climate change": ["upsc", "state"],
    "national park": ["upsc", "state"],
    "wildlife": ["upsc", "state"],
    "biosphere reserve": ["upsc", "state"],
    "tiger reserve": ["upsc", "state"],
    "education policy": ["teaching", "upsc"],
    "new education policy": ["teaching", "upsc"],
    " nep ": ["teaching", "upsc"],
    "sports": ["ssc", "railway", "upsc", "defence"],
    "important day": ["upsc", "ssc", "railway", "banking", "state"],
    "bihar": ["state"],
}

# ----------------------------------------------------------------------
# Content that should never be uploaded, regardless of category.
# ----------------------------------------------------------------------

BLOCKLIST_KEYWORDS: List[str] = [
    "bollywood",
    "hollywood",
    "movie review",
    "box office",
    "film review",
    "web series",
    "ott release",
    "tv show",
    "television show",
    "reality show",
    "celebrity",
    "actor ",
    "actress",
    "fashion week",
    "runway",
    "entertainment news",
    "gossip",
    "meme",
    "sponsored content",
    "advertisement",
    "promotional offer",
    "click here to buy",
    "horoscope",
    "zodiac",
]


# ======================================================================
# RETRY DECORATOR
# ======================================================================

def retry(max_attempts: int = MAX_RETRIES, backoff_seconds: int = RETRY_BACKOFF_SECONDS):
    """Retry a function on failure with linear backoff. Never raises past
    the final attempt is swallowed by the caller if it also wraps in try/except."""

    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001 - intentional broad catch
                    last_exception = exc
                    logger.warning(
                        "Attempt %d/%d failed for %s: %s",
                        attempt,
                        max_attempts,
                        func.__name__,
                        exc,
                    )
                    if attempt < max_attempts:
                        time.sleep(backoff_seconds * attempt)
            logger.error("All %d attempts failed for %s", max_attempts, func.__name__)
            raise last_exception

        return wrapper

    return decorator


# ======================================================================
# NEWS FETCHER
# ======================================================================

class NewsDataFetcher:
    """Handles all communication with the NewsData.io API."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    @retry()
    def _fetch_page(self, category: str, page_token: Optional[str] = None) -> Dict[str, Any]:
        params = {
            "apikey": self.api_key,
            "country": COUNTRY,
            "language": LANGUAGE,
            "category": category,
        }
        if page_token:
            params["page"] = page_token

        response = requests.get(
            NEWSDATA_BASE_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS
        )

        if response.status_code == 429:
            raise RuntimeError("NewsData.io rate limit reached (HTTP 429)")
        if response.status_code != 200:
            raise RuntimeError(
                f"NewsData.io returned HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Invalid JSON received from NewsData.io: {exc}") from exc

        if not data:
            raise RuntimeError("Empty response body from NewsData.io")

        if data.get("status") != "success":
            raise RuntimeError(f"NewsData.io API error: {data.get('results', data)}")

        return data

    def fetch_category(self, category: str) -> List[Dict[str, Any]]:
        """Fetch a single category's articles. Only the first page is
        requested to conserve the free API quota."""
        try:
            data = self._fetch_page(category)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch category '%s' after retries: %s", category, exc)
            return []

        articles = data.get("results") or []
        logger.info("Fetched %d raw articles for category '%s'", len(articles), category)
        return articles

    def fetch_all(self) -> List[Dict[str, Any]]:
        all_articles: List[Dict[str, Any]] = []
        for category in NEWS_CATEGORIES:
            all_articles.extend(self.fetch_category(category))
        return all_articles


# ======================================================================
# CONTENT FILTER
# ======================================================================

class ContentFilter:
    """Rejects entertainment / spam / low quality articles."""

    @staticmethod
    def _text_of(article: Dict[str, Any]) -> str:
        title = (article.get("title") or "").lower()
        description = (article.get("description") or "").lower()
        content = (article.get("content") or "").lower()
        return f" {title} {description} {content} "

    @classmethod
    def is_allowed(cls, article: Dict[str, Any]) -> bool:
        # Must have a title and a URL at minimum to be useful.
        if not article.get("title") or not article.get("link"):
            return False

        text = cls._text_of(article)
        for bad_word in BLOCKLIST_KEYWORDS:
            if bad_word in text:
                return False
        return True


# ======================================================================
# DEDUPLICATION
# ======================================================================

class Deduplicator:
    """Removes duplicate articles, both within a single run and against
    what is already stored in Firebase."""

    @staticmethod
    def normalize_title(title: str) -> str:
        title = title.lower().strip()
        title = re.sub(r"[^a-z0-9 ]", "", title)
        title = re.sub(r"\s+", " ", title)
        return title

    @staticmethod
    def article_id(url: str) -> str:
        return hashlib.md5(url.strip().lower().encode("utf-8")).hexdigest()

    @classmethod
    def dedupe_batch(cls, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen_urls: Set[str] = set()
        seen_titles: Set[str] = set()
        unique: List[Dict[str, Any]] = []

        for article in articles:
            url = (article.get("link") or "").strip().lower()
            title_norm = cls.normalize_title(article.get("title") or "")

            if not url or not title_norm:
                continue
            if url in seen_urls or title_norm in seen_titles:
                continue

            seen_urls.add(url)
            seen_titles.add(title_norm)
            unique.append(article)

        return unique


# ======================================================================
# SUMMARIZER
# ======================================================================

class Summarizer:
    """Generates a short, clean 2-3 line summary without any external
    LLM dependency, using simple extractive sentence selection."""

    _SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

    @classmethod
    def generate_summary(cls, article: Dict[str, Any]) -> str:
        raw_text = (
            article.get("description")
            or article.get("content")
            or article.get("title")
            or ""
        )
        raw_text = raw_text.strip()

        if not raw_text:
            return "Summary not available for this article."

        # Remove NewsData's truncation marker if present.
        raw_text = raw_text.replace("ONLY AVAILABLE IN PAID PLANS", "").strip()

        sentences = cls._SENTENCE_SPLIT_RE.split(raw_text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return raw_text[:280]

        summary = " ".join(sentences[:3])

        if len(summary) > 320:
            summary = summary[:317].rsplit(" ", 1)[0] + "..."

        return summary


# ======================================================================
# KEYWORD EXTRACTOR
# ======================================================================

class KeywordExtractor:
    """Extracts important keywords found in an article based on the
    important-topics vocabulary used across all supported exams."""

    @staticmethod
    def extract(text: str) -> List[str]:
        text_padded = f" {text.lower()} "
        matched: List[str] = []
        for phrase in TOPIC_EXAM_MAP.keys():
            clean_phrase = phrase.strip()
            if clean_phrase and clean_phrase in text_padded:
                matched.append(clean_phrase.strip().title())
        # Deduplicate while preserving order, cap at 10 keywords.
        seen = set()
        unique_matched = []
        for kw in matched:
            if kw not in seen:
                seen.add(kw)
                unique_matched.append(kw)
        return unique_matched[:10]


# ======================================================================
# EXAM CATEGORIZER
# ======================================================================

class ExamCategorizer:
    """Maps an article to every relevant exam node based on matched
    topic keywords."""

    @staticmethod
    def categorize(text: str) -> List[str]:
        text_padded = f" {text.lower()} "
        matched_categories: Set[str] = set()

        for phrase, categories in TOPIC_EXAM_MAP.items():
            if phrase.strip() in text_padded:
                matched_categories.update(categories)

        exam_names: Set[str] = set()
        for category_key in matched_categories:
            exam_names.update(EXAM_CATEGORY_MEMBERS.get(category_key, []))

        # Every article always goes into "All Exams".
        exam_names.add(ALL_EXAMS_NODE)

        return sorted(exam_names)


# ======================================================================
# ARTICLE BUILDER
# ======================================================================

def build_article_record(raw_article: Dict[str, Any]) -> Dict[str, Any]:
    """Transforms a raw NewsData.io article into our Firebase schema."""

    title = (raw_article.get("title") or "").strip()
    description = (raw_article.get("description") or "").strip() or "No description available."
    url = (raw_article.get("link") or "").strip()
    image_url = raw_article.get("image_url") or ""
    source = raw_article.get("source_id") or raw_article.get("source_name") or "Unknown"

    pub_date_raw = raw_article.get("pubDate")
    try:
        parsed_date = date_parser.parse(pub_date_raw) if pub_date_raw else datetime.now(timezone.utc)
        if parsed_date.tzinfo is None:
            parsed_date = parsed_date.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        parsed_date = datetime.now(timezone.utc)

    combined_text = f"{title} {description} {raw_article.get('content') or ''}"

    now_iso = datetime.now(timezone.utc).isoformat()

    record = {
        "title": title,
        "description": description,
        "summary": Summarizer.generate_summary(raw_article),
        "date": parsed_date.isoformat(),
        "category": ", ".join(raw_article.get("category") or ["general"]),
        "source": source,
        "url": url,
        "imageUrl": image_url,
        "country": "India",
        "language": "English",
        "importantKeywords": KeywordExtractor.extract(combined_text),
        "examNames": ExamCategorizer.categorize(combined_text),
        "createdAt": now_iso,
        "updatedAt": now_iso,
    }
    return record


# ======================================================================
# FIREBASE UPLOADER
# ======================================================================

class FirebaseUploader:
    """Handles Firebase Admin SDK initialization and merging/uploading
    of articles into the Realtime Database, per exam node."""

    def __init__(self, service_account_json: str, database_url: str):
        if firebase_admin is None:
            raise RuntimeError(
                "firebase_admin package is not installed. Run: pip install firebase-admin"
            )

        if not firebase_admin._apps:  # avoid re-initializing on repeated calls
            cred_dict = json.loads(service_account_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred, {"databaseURL": database_url})

    @retry()
    def _get_existing(self, exam_name: str) -> Dict[str, Any]:
        ref = db.reference(f"{FIREBASE_ROOT_NODE}/{exam_name}")
        data = ref.get()
        return data or {}

    @retry()
    def _write(self, exam_name: str, data: Dict[str, Any]) -> None:
        ref = db.reference(f"{FIREBASE_ROOT_NODE}/{exam_name}")
        ref.set(data)

    def upload_articles_for_exam(
        self, exam_name: str, new_articles: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """Merges new_articles into the existing node for exam_name,
        removing duplicates by article id and keeping only the newest
        MAX_ARTICLES_PER_EXAM entries."""

        stats = {"added": 0, "skipped_duplicate": 0, "failed": 0}

        try:
            existing = self._get_existing(exam_name)
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not read existing data for exam '%s': %s", exam_name, exc)
            existing = {}

        merged = dict(existing)

        for article in new_articles:
            article_id = Deduplicator.article_id(article["url"])
            if article_id in merged:
                stats["skipped_duplicate"] += 1
                continue
            merged[article_id] = article
            stats["added"] += 1

        if stats["added"] == 0:
            logger.info("No new articles to add for exam '%s' (all duplicates).", exam_name)
            return stats

        # Sort newest first by 'date', trim to latest MAX_ARTICLES_PER_EXAM.
        def sort_key(item):
            try:
                return date_parser.parse(item[1].get("date", ""))
            except (ValueError, TypeError):
                return datetime.min.replace(tzinfo=timezone.utc)

        sorted_items = sorted(merged.items(), key=sort_key, reverse=True)
        trimmed_items = sorted_items[:MAX_ARTICLES_PER_EXAM]
        final_data = dict(trimmed_items)

        try:
            self._write(exam_name, final_data)
            logger.info(
                "Uploaded exam '%s': +%d new, %d duplicates skipped, %d total stored.",
                exam_name,
                stats["added"],
                stats["skipped_duplicate"],
                len(final_data),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to write exam '%s' to Firebase: %s", exam_name, exc)
            stats["failed"] = stats["added"]
            stats["added"] = 0

        return stats


# ======================================================================
# MAIN PIPELINE
# ======================================================================

def validate_environment() -> bool:
    missing = []
    if not NEWSDATA_API_KEY:
        missing.append("NEWSDATA_API_KEY")
    if not FIREBASE_SERVICE_ACCOUNT:
        missing.append("FIREBASE_SERVICE_ACCOUNT")
    if not FIREBASE_DATABASE_URL:
        missing.append("FIREBASE_DATABASE_URL")

    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        return False
    return True


def main() -> None:
    start_time = time.time()
    logger.info("=" * 70)
    logger.info("ExamHub India Current Affairs Automation - Run Started")
    logger.info("=" * 70)

    if not validate_environment():
        logger.error("Aborting run due to missing configuration.")
        sys.exit(1)

    stats = {
        "fetched": 0,
        "filtered_out": 0,
        "duplicates_removed": 0,
        "final_articles": 0,
        "exam_uploads_added": 0,
        "exam_uploads_duplicate": 0,
        "exam_uploads_failed": 0,
    }

    # ---------------- STEP 1: FETCH ----------------
    try:
        fetcher = NewsDataFetcher(NEWSDATA_API_KEY)
        raw_articles = fetcher.fetch_all()
        stats["fetched"] = len(raw_articles)
        logger.info("STEP 1 COMPLETE: Fetched %d total raw articles.", stats["fetched"])
    except Exception as exc:  # noqa: BLE001
        logger.error("Fatal error during fetch stage: %s", exc)
        raw_articles = []

    if not raw_articles:
        logger.warning("No articles fetched. Ending run gracefully.")
        _log_final_summary(stats, start_time)
        return

    # ---------------- STEP 2: FILTER ----------------
    filtered_articles = []
    for article in raw_articles:
        try:
            if ContentFilter.is_allowed(article):
                filtered_articles.append(article)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping article due to filter error: %s", exc)

    stats["filtered_out"] = stats["fetched"] - len(filtered_articles)
    logger.info(
        "STEP 2 COMPLETE: %d articles passed filtering, %d rejected.",
        len(filtered_articles),
        stats["filtered_out"],
    )

    # ---------------- STEP 3: DEDUPLICATE (within batch) ----------------
    unique_articles = Deduplicator.dedupe_batch(filtered_articles)
    stats["duplicates_removed"] = len(filtered_articles) - len(unique_articles)
    logger.info(
        "STEP 3 COMPLETE: %d unique articles remain, %d duplicates removed.",
        len(unique_articles),
        stats["duplicates_removed"],
    )

    # ---------------- STEP 4: BUILD RECORDS (summary + keywords + exams) ----------------
    built_records = []
    for raw in unique_articles:
        try:
            record = build_article_record(raw)
            built_records.append(record)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping article '%s' due to build error: %s", raw.get("title"), exc)

    stats["final_articles"] = len(built_records)
    logger.info("STEP 4 COMPLETE: %d article records built.", stats["final_articles"])

    if not built_records:
        logger.warning("No valid articles to upload. Ending run gracefully.")
        _log_final_summary(stats, start_time)
        return

    # ---------------- STEP 5: GROUP BY EXAM ----------------
    exam_buckets: Dict[str, List[Dict[str, Any]]] = {exam: [] for exam in ALL_EXAM_NODES}
    for record in built_records:
        for exam_name in record["examNames"]:
            if exam_name in exam_buckets:
                exam_buckets[exam_name].append(record)

    # ---------------- STEP 6: UPLOAD TO FIREBASE ----------------
    try:
        uploader = FirebaseUploader(FIREBASE_SERVICE_ACCOUNT, FIREBASE_DATABASE_URL)
    except Exception as exc:  # noqa: BLE001
        logger.error("Fatal error initializing Firebase: %s", exc)
        _log_final_summary(stats, start_time)
        return

    for exam_name, articles in exam_buckets.items():
        if not articles:
            continue
        try:
            result = uploader.upload_articles_for_exam(exam_name, articles)
            stats["exam_uploads_added"] += result["added"]
            stats["exam_uploads_duplicate"] += result["skipped_duplicate"]
            stats["exam_uploads_failed"] += result["failed"]
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected failure uploading exam '%s': %s", exam_name, exc)
            stats["exam_uploads_failed"] += len(articles)

    logger.info("STEP 6 COMPLETE: Upload finished for all exam nodes.")

    _log_final_summary(stats, start_time)


def _log_final_summary(stats: Dict[str, int], start_time: float) -> None:
    elapsed = time.time() - start_time
    logger.info("=" * 70)
    logger.info("RUN SUMMARY")
    logger.info("-" * 70)
    logger.info("Fetched News            : %d", stats["fetched"])
    logger.info("Filtered Out (Rejected) : %d", stats["filtered_out"])
    logger.info("Duplicates Removed      : %d", stats["duplicates_removed"])
    logger.info("Final Unique Articles   : %d", stats["final_articles"])
    logger.info("Uploaded (per exam)     : %d", stats["exam_uploads_added"])
    logger.info("Skipped (already exist) : %d", stats["exam_uploads_duplicate"])
    logger.info("Failed Uploads          : %d", stats["exam_uploads_failed"])
    logger.info("Execution Time          : %.2f seconds", elapsed)
    logger.info("=" * 70)
    logger.info("ExamHub India Current Affairs Automation - Run Finished")
    logger.info("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - top-level safety net, never crash
        logger.exception("Unhandled exception in main execution: %s", exc)
        sys.exit(0)  # exit cleanly so scheduled workflow doesn't show hard failure spam
