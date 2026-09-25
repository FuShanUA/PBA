"""Reliable publication-date extraction for Palantir website pages."""

import json
import re
from datetime import datetime

from bs4 import BeautifulSoup


NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.I | re.S,
)
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
MONTH_RE = "|".join(MONTHS)
CONTENT_DATE_PATTERNS = (
    re.compile(rf"\b({MONTH_RE})\s+(\d{{1,2}}),\s*(20\d{{2}})\b", re.I),
    re.compile(rf"\b(\d{{1,2}})\s+({MONTH_RE})\s+(20\d{{2}})\b", re.I),
)


def normalize_date(value):
    """Return YYYY-MM-DD for an ISO date, or an empty string."""
    if not value or not isinstance(value, str):
        return ""
    value = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            parsed = datetime.strptime(value, "%Y-%m-%d")
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.year < 1998 or parsed.year > 2100:
        return ""
    return parsed.strftime("%Y-%m-%d")


def extract_next_data(html):
    match = NEXT_DATA_RE.search(html or "")
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def extract_content_date(content_html):
    """Extract an explicit date shown near the start of the page body."""
    if not content_html:
        return ""
    soup = BeautifulSoup(content_html, "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.find("body") or soup
    text = root.get_text(" ", strip=True)[:5000]
    for pattern in CONTENT_DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        groups = match.groups()
        if groups[0].lower() in MONTHS:
            month = MONTHS[groups[0].lower()]
            day = int(groups[1])
            year = int(groups[2])
        else:
            day = int(groups[0])
            month = MONTHS[groups[1].lower()]
            year = int(groups[2])
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def extract_page_publish_date(html, content_html=None):
    """Extract a page-level publication date without using scan timestamps."""
    page = extract_next_data(html).get("props", {}).get("pageProps", {}).get("page", {})
    fields = page.get("fields", {}) or {}
    sys_info = page.get("sys", {}) or {}

    date = normalize_date(fields.get("publishDate"))
    if date:
        return date, "publishDate"

    # An explicit date in the page body is more useful than a generic CMS
    # creation timestamp when both are available.
    date = extract_content_date(content_html or html)
    if date:
        return date, "content"

    for field_name in ("firstPublishedAt", "publishedAt", "createdAt"):
        date = normalize_date(sys_info.get(field_name))
        if date:
            return date, field_name
    return "", ""


def build_date_counts(articles):
    counts = {}
    for article in articles:
        date = article.get("pd", "")
        if not date:
            continue
        year, month = date[:4], date[5:7]
        counts.setdefault(year, {}).setdefault(month, 0)
        counts[year][month] += 1
    return counts
