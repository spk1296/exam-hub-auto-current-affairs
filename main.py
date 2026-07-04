#!/usr/bin/env python3
"""
Current Affairs Auto-Updater
=============================

Fetches the latest India current affairs from NewsData.io (Free Plan),
automatically categorizes each news item into every relevant competitive
exam category, removes duplicates, and uploads the result to Firebase
Realtime Database using the Firebase Admin SDK.

Designed to run once a day via GitHub Actions, but safe to run manually
any number of times (it merges with existing data and never loses history
beyond the configured per-exam limit).

Author: Generated for automated Android app current-affairs pipeline.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import requests

try:
    import firebase_admin
    from firebase_admin import credentials, db
except ImportError as exc:  # pragma: no cover
    print(f"FATAL: firebase-admin is not installed: {exc}", file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

NEWSDATA_BASE_URL = "https://newsdata.io/api/1/latest"

# Free plan constraints: max 10 results per request, ~200 credits/day.
# We spread requests across a handful of categories relevant to Indian
# competitive exam current affairs, and stay well within the free quota.
NEWSDATA_CATEGORIES = [
    "top",
    "politics",
    "world",
    "business",
    "science",
    "education",
    "sports",
    "technology",
]

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5
REQUEST_TIMEOUT_SECONDS = 20
SLEEP_BETWEEN_REQUESTS_SECONDS = 1.5

MAX_ITEMS_PER_EXAM = 100
FIREBASE_ROOT_NODE = "current_affairs"
ALL_EXAMS_NODE = "All Exams"

# The complete list of exam nodes that must always exist in Firebase,
# even if no news matches them on a given day.
EXAM_LIST = [
    "UPSC",
    "SSC CGL",
    "SSC CHSL",
    "SSC GD",
    "Railway NTPC",
    "Railway Group D",
    "Bihar Police",
    "Bihar SI",
    "BPSC",
    "CTET",
    "STET",
    "UGC NET",
    "CDS",
    "NDA",
    "IBPS PO",
    "SBI PO",
    "JEE",
    "NEET",
    "CUET",
    ALL_EXAMS_NODE,
]

# --------------------------------------------------------------------------
# Categorization rules
# --------------------------------------------------------------------------
# Each rule maps a set of keywords (matched case-insensitively against the
# combined title + description of a news item) to the list of exams that
# the news item should be uploaded to. A single news item can match
# multiple rules, and will be uploaded to the union of all matched exams.
#
# Two tiers of rules are used:
#   1. EXAM_SPECIFIC_RULES  -> keywords that name a specific exam/recruitment
#      directly (e.g. "SSC CGL", "IBPS PO"). These map to that one exam.
#   2. TOPIC_RULES          -> broader current-affairs topics (government
#      schemes, defence, economy, science, sports, education policy, etc.)
#      that are generally relevant to a group of exams and are commonly
#      asked in their General Knowledge / Current Affairs sections.
# --------------------------------------------------------------------------

EXAM_SPECIFIC_RULES = {
    "UPSC": [
        "upsc", "civil services exam", "ias officer", "ips officer",
        "ifs officer", "union public service commission", "cse prelims",
        "cse mains", "civil services examination",
    ],
    "SSC CGL": [
        "ssc cgl", "combined graduate level",
    ],
    "SSC CHSL": [
        "ssc chsl", "combined higher secondary level",
    ],
    "SSC GD": [
        "ssc gd", "gd constable", "ssc constable",
    ],
    "Railway NTPC": [
        "railway ntpc", "rrb ntpc", "non technical popular categories",
    ],
    "Railway Group D": [
        "railway group d", "rrb group d", "rrc group d",
    ],
    "Bihar Police": [
        "bihar police", "bihar constable", "csbc",
    ],
    "Bihar SI": [
        "bihar si", "bihar sub inspector", "bpssc", "bihar police subordinate service commission",
    ],
    "BPSC": [
        "bpsc", "bihar public service commission",
    ],
    "CTET": [
        "ctet", "central teacher eligibility test",
    ],
    "STET": [
        "stet", "state teacher eligibility test", "bihar stet",
    ],
    "UGC NET": [
        "ugc net", "nta net", "national eligibility test", "jrf exam",
    ],
    "CDS": [
        "cds exam", "combined defence services",
    ],
    "NDA": [
        "nda exam", "national defence academy",
    ],
    "IBPS PO": [
        "ibps po", "ibps probationary officer", "institute of banking personnel selection",
    ],
    "SBI PO": [
        "sbi po", "state bank of india po", "sbi probationary officer",
    ],
    "JEE": [
        "jee main", "jee advanced", "joint entrance examination",
    ],
    "NEET": [
        "neet ug", "neet pg", "neet exam", "national eligibility cum entrance test",
    ],
    "CUET": [
        "cuet", "common university entrance test",
    ],
}

TOPIC_RULES = {
    # General polity, governance, and government schemes are core GK for
    # almost every competitive exam.
    "government_scheme": {
        "keywords": [
            "government scheme", "yojana", "cabinet approves", "union cabinet",
            "niti aayog", "budget 2026", "union budget", "parliament passes",
            "lok sabha", "rajya sabha", "new policy", "ministry of",
        ],
        "exams": [
            "UPSC", "BPSC", "SSC CGL", "SSC CHSL", "IBPS PO", "SBI PO",
            "CUET", "UGC NET",
        ],
    },
    "defence_security": {
        "keywords": [
            "indian army", "indian navy", "indian air force", "drdo",
            "defence ministry", "border security force", "isro launch",
            "missile test", "military exercise",
        ],
        "exams": ["UPSC", "CDS", "NDA", "BPSC", "SSC CGL", "SSC GD"],
    },
    "international_relations": {
        "keywords": [
            "united nations", "g20 summit", "bilateral talks", "foreign minister",
            "diplomatic", "international relations", "world bank", "imf report",
            "bilateral agreement", "summit meeting",
        ],
        "exams": ["UPSC", "BPSC", "CDS", "NDA"],
    },
    "banking_economy": {
        "keywords": [
            "reserve bank of india", "rbi monetary policy", "repo rate",
            "gdp growth", "inflation rate", "stock market", "sensex", "nifty",
            "banking sector", "economic survey",
        ],
        "exams": ["IBPS PO", "SBI PO", "UPSC", "BPSC", "SSC CGL"],
    },
    "science_technology": {
        "keywords": [
            "isro", "space mission", "chandrayaan", "gaganyaan", "artificial intelligence",
            "scientific research", "nasa", "satellite launch", "technology breakthrough",
        ],
        "exams": ["UPSC", "JEE", "NEET", "SSC CGL", "SSC CHSL", "CUET"],
    },
    "sports": {
        "keywords": [
            "olympics", "world cup", "cricket team", "asian games", "commonwealth games",
            "sports ministry", "khelo india", "medal tally",
        ],
        "exams": ["SSC CGL", "SSC CHSL", "Railway NTPC", "UPSC", "BPSC"],
    },
    "education_policy": {
        "keywords": [
            "education policy", "national education policy", "nep 2020",
            "university grants commission", "school education", "board exam results",
        ],
        "exams": ["CTET", "STET", "UGC NET", "CUET", "UPSC"],
    },
    "state_affairs_bihar": {
        "keywords": [
            "bihar government", "bihar cabinet", "bihar assembly", "patna high court",
            "bihar chief minister",
        ],
        "exams": ["BPSC", "Bihar Police", "Bihar SI", "STET"],
    },
    "awards_appointments": {
        "keywords": [
            "padma award", "nobel prize", "appointed as chief", "new governor",
            "new chief justice", "award ceremony",
        ],
        "exams": ["UPSC", "BPSC", "SSC CGL", "SSC CHSL", "IBPS PO", "SBI PO"],
    },
}


# --------------------------------------------------------------------------
# Logging setup
# --------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("current_affairs_updater")


# --------------------------------------------------------------------------
# Environment / configuration helpers
# --------------------------------------------------------------------------

def get_required_env(var_name: str) -> str:
    """Fetch a required environment variable or exit with a clear error."""
    value = os.environ.get(var_name)
    if not value:
        logger.error("Missing required environment variable: %s", var_name)
        sys.exit(1)
    return value


# --------------------------------------------------------------------------
# NewsData.io fetching with retry
# --------------------------------------------------------------------------

def fetch_category_with_retry(api_key: str, category: str):
    """
    Fetch a single category page from NewsData.io's 'latest' endpoint,
    retrying on transient failures (network errors, timeouts, 5xx, 429).
    Returns a list of raw article dicts, or an empty list if the category
    could not be fetched after all retries.
    """
    params = {
        "apikey": api_key,
        "country": "in",
        "language": "en",
        "category": category,
    }

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                "Fetching NewsData.io category='%s' (attempt %d/%d)",
                category, attempt, MAX_RETRIES,
            )
            response = requests.get(
                NEWSDATA_BASE_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS
            )

            if response.status_code == 429:
                logger.warning(
                    "Rate limited by NewsData.io on category '%s'. Backing off.",
                    category,
                )
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                last_error = "rate_limited"
                continue

            response.raise_for_status()
            payload = response.json()

            if payload.get("status") != "success":
                logger.warning(
                    "NewsData.io returned non-success status for '%s': %s",
                    category, payload.get("results", payload),
                )
                last_error = "api_error"
                time.sleep(RETRY_BACKOFF_SECONDS)
                continue

            articles = payload.get("results", []) or []
            logger.info(
                "Fetched %d articles for category '%s'", len(articles), category
            )
            return articles

        except requests.exceptions.Timeout as exc:
            last_error = exc
            logger.warning(
                "Timeout fetching category '%s' (attempt %d/%d): %s",
                category, attempt, MAX_RETRIES, exc,
            )
        except requests.exceptions.RequestException as exc:
            last_error = exc
            logger.warning(
                "Request error fetching category '%s' (attempt %d/%d): %s",
                category, attempt, MAX_RETRIES, exc,
            )
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning(
                "Invalid JSON from NewsData.io for category '%s' (attempt %d/%d): %s",
                category, attempt, MAX_RETRIES, exc,
            )

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    logger.error(
        "Giving up on category '%s' after %d attempts. Last error: %s",
        category, MAX_RETRIES, last_error,
    )
    return []


def fetch_all_news(api_key: str):
    """Fetch news across all configured categories and return the raw list."""
    all_articles = []
    for category in NEWSDATA_CATEGORIES:
        articles = fetch_category_with_retry(api_key, category)
        all_articles.extend(articles)
        time.sleep(SLEEP_BETWEEN_REQUESTS_SECONDS)
    return all_articles


# --------------------------------------------------------------------------
# Normalization, deduplication, categorization
# --------------------------------------------------------------------------

def normalize_article(raw: dict):
    """
    Convert a raw NewsData.io article dict into our standard schema:
    {title, date, category, description, source, url}
    Returns None if the article is missing essential fields.
    """
    title = (raw.get("title") or "").strip()
    url = (raw.get("link") or "").strip()

    if not title or not url:
        return None

    description = (raw.get("description") or raw.get("content") or "").strip()
    pub_date = (raw.get("pubDate") or "").strip()
    source = (raw.get("source_id") or raw.get("source_name") or "unknown").strip()

    raw_categories = raw.get("category") or []
    if isinstance(raw_categories, list):
        category_str = ", ".join(raw_categories)
    else:
        category_str = str(raw_categories)

    if not pub_date:
        pub_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    return {
        "title": title,
        "date": pub_date,
        "category": category_str,
        "description": description,
        "source": source,
        "url": url,
    }


def deduplicate_articles(articles):
    """Remove duplicate articles based on URL (falls back to title)."""
    seen_keys = set()
    unique_articles = []

    for article in articles:
        key = article["url"].lower() if article.get("url") else article["title"].lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique_articles.append(article)

    return unique_articles


def categorize_article(article: dict):
    """
    Determine the set of exam nodes this article should be uploaded to,
    based on EXAM_SPECIFIC_RULES and TOPIC_RULES. Always includes
    ALL_EXAMS_NODE.
    """
    text = f"{article.get('title', '')} {article.get('description', '')}".lower()
    matched_exams = set()

    for exam, keywords in EXAM_SPECIFIC_RULES.items():
        if any(keyword in text for keyword in keywords):
            matched_exams.add(exam)

    for _, rule in TOPIC_RULES.items():
        if any(keyword in text for keyword in rule["keywords"]):
            matched_exams.update(rule["exams"])

    matched_exams.add(ALL_EXAMS_NODE)
    return matched_exams


def parse_date_safe(date_str: str):
    """
    Parse a date string into a comparable datetime for sorting.
    Falls back to datetime.min (UTC-naive) if parsing fails, so
    unparseable dates sort to the bottom rather than crashing the run.
    """
    if not date_str:
        return datetime.min

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    logger.debug("Could not parse date '%s'; treating as oldest possible.", date_str)
    return datetime.min


def build_exam_buckets(articles):
    """
    Given a deduplicated list of normalized articles, return a dict:
        { exam_name: [article, article, ...] }
    covering every exam in EXAM_LIST (empty list if nothing matched).
    """
    buckets = {exam: [] for exam in EXAM_LIST}

    for article in articles:
        matched_exams = categorize_article(article)
        for exam in matched_exams:
            if exam in buckets:
                buckets[exam].append(article)

    return buckets


# --------------------------------------------------------------------------
# Firebase helpers
# --------------------------------------------------------------------------

def init_firebase(service_account_json: str, database_url: str):
    """Initialize the Firebase Admin SDK app from a service account JSON string."""
    try:
        service_account_info = json.loads(service_account_json)
    except json.JSONDecodeError as exc:
        logger.error("FIREBASE_SERVICE_ACCOUNT is not valid JSON: %s", exc)
        sys.exit(1)

    try:
        cred = credentials.Certificate(service_account_info)
        firebase_admin.initialize_app(cred, {"databaseURL": database_url})
        logger.info("Firebase Admin SDK initialized successfully.")
    except Exception as exc:  # noqa: BLE001 - we want to catch any init failure
        logger.error("Failed to initialize Firebase Admin SDK: %s", exc)
        sys.exit(1)


def upload_exam_bucket(exam_name: str, new_articles: list):
    """
    Merge new_articles with whatever already exists at
    current_affairs/{exam_name}, deduplicate, sort by date (latest first),
    truncate to MAX_ITEMS_PER_EXAM, and write the result back.
    """
    safe_path = f"{FIREBASE_ROOT_NODE}/{exam_name}"
    ref = db.reference(safe_path)

    try:
        existing_data = ref.get()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to read existing data for '%s': %s", exam_name, exc)
        existing_data = None

    existing_articles = []
    if isinstance(existing_data, list):
        existing_articles = [item for item in existing_data if item]
    elif isinstance(existing_data, dict):
        existing_articles = list(existing_data.values())

    combined = existing_articles + new_articles
    deduped = deduplicate_articles(combined)
    deduped.sort(key=lambda a: parse_date_safe(a.get("date", "")), reverse=True)
    trimmed = deduped[:MAX_ITEMS_PER_EXAM]

    try:
        ref.set(trimmed)
        logger.info(
            "Uploaded '%s': %d new, %d existing, %d after merge/dedup, %d stored.",
            exam_name, len(new_articles), len(existing_articles),
            len(deduped), len(trimmed),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to write data for '%s': %s", exam_name, exc)


# --------------------------------------------------------------------------
# Main pipeline
# --------------------------------------------------------------------------

def main():
    logger.info("=== Current Affairs Updater: run started ===")

    api_key = get_required_env("NEWSDATA_API_KEY")
    service_account_json = get_required_env("FIREBASE_SERVICE_ACCOUNT")
    database_url = get_required_env("FIREBASE_DATABASE_URL")

    init_firebase(service_account_json, database_url)

    logger.info("Fetching news from NewsData.io ...")
    raw_articles = fetch_all_news(api_key)
    logger.info("Total raw articles fetched: %d", len(raw_articles))

    if not raw_articles:
        logger.warning("No articles were fetched. Ending run without changes.")
        return

    normalized = []
    for raw in raw_articles:
        article = normalize_article(raw)
        if article:
            normalized.append(article)
    logger.info("Normalized articles: %d", len(normalized))

    deduped = deduplicate_articles(normalized)
    logger.info("Articles after deduplication: %d", len(deduped))

    deduped.sort(key=lambda a: parse_date_safe(a.get("date", "")), reverse=True)

    buckets = build_exam_buckets(deduped)

    for exam_name in EXAM_LIST:
        new_articles = buckets.get(exam_name, [])
        upload_exam_bucket(exam_name, new_articles)

    logger.info("=== Current Affairs Updater: run completed successfully ===")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - top-level safety net
        logger.exception("Unhandled fatal error: %s", exc)
        sys.exit(1)
