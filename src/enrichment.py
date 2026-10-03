"""Stage 2: turn raw channel data into a complete influencer record.

Rule: never guess. Anything we cannot find is stored as "Not Found" / "Not Available".
"""
import logging
import re
from collections import Counter
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from .youtube import YouTubeClient, QuotaExceeded

log = logging.getLogger(__name__)

NOT_FOUND = "Not Found"
NOT_AVAILABLE = "Not Available"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s)>\]\"']+")
IG_RE = re.compile(r"instagram\.com/([A-Za-z0-9_.]+)", re.I)
TT_RE = re.compile(r"tiktok\.com/@([A-Za-z0-9_.]+)", re.I)
SOCIAL_HOSTS = ("youtube.com", "youtu.be", "instagram.com", "tiktok.com", "facebook.com",
                "twitter.com", "x.com", "pinterest.com", "snapchat.com")
BAD_EMAIL_SUFFIX = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
STOPWORDS = set("""a an the and or of to in on for with my your our is are was be this that these those it its i you we
how what why when new best top video videos vlog day week get look looks routine review haul vs from at by
as up out all about easy simple full part ep episode shorts short official""".split())


def extract_email(text: str) -> str:
    """First plausible email in text, or NOT_FOUND."""
    for m in EMAIL_RE.findall(text or ""):
        e = m.strip(".,;:").lower()
        if not e.endswith(BAD_EMAIL_SUFFIX):
            return e
    return NOT_FOUND


def extract_links(text: str) -> dict:
    text = text or ""
    ig = IG_RE.search(text)
    tt = TT_RE.search(text)
    website = ""
    for u in URL_RE.findall(text):
        host = urlparse(u).netloc.lower().removeprefix("www.")
        if host and not any(host == s or host.endswith("." + s) for s in SOCIAL_HOSTS):
            website = u.rstrip(".,;")
            break
    return {
        "instagram": f"https://instagram.com/{ig.group(1)}" if ig else NOT_FOUND,
        "tiktok": f"https://tiktok.com/@{tt.group(1)}" if tt else NOT_FOUND,
        "website": website or NOT_FOUND,
    }


def compute_engagement(videos: list[dict]) -> tuple:
    """Mean (likes+comments)/views over videos with usable stats. Returns (rate_pct, avg_views, n_used)."""
    rates, views_list = [], []
    for v in videos:
        s = v.get("statistics", {})
        views = int(s.get("viewCount", 0))
        if views <= 0 or "likeCount" not in s:  # likes can be hidden by the creator
            continue
        interactions = int(s["likeCount"]) + int(s.get("commentCount", 0))
        rates.append(interactions / views)
        views_list.append(views)
    if not rates:
        return NOT_AVAILABLE, NOT_AVAILABLE, 0
    return round(100 * sum(rates) / len(rates), 2), int(sum(views_list) / len(views_list)), len(rates)


def extract_themes(titles: list[str], top_n: int = 6) -> list[str]:
    """Cheap keyword-frequency themes from recent titles (LLM theming comes in the personalization stage)."""
    words = []
    for t in titles:
        words += [w for w in re.findall(r"[a-zA-Z]{3,}", t.lower()) if w not in STOPWORDS]
    return [w for w, _ in Counter(words).most_common(top_n)]


def scrape_website_email(url: str, user_agent: str = "OutreachResearchBot/0.1", timeout: int = 8) -> str:
    """Look for a public email on the creator's own site (homepage, /contact, /about). Respects robots.txt."""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    rp = RobotFileParser()
    try:
        rp.set_url(base + "/robots.txt")
        rp.read()
    except Exception:
        pass
    for path in ("", "/contact", "/about"):
        target = (url if path == "" else base + path)
        try:
            if not rp.can_fetch(user_agent, target):
                continue
            r = requests.get(target, headers={"User-Agent": user_agent}, timeout=timeout)
            if r.ok:
                mailto = re.findall(r"mailto:([^\"'?>\s]+)", r.text)
                email = extract_email(" ".join(mailto) or r.text)
                if email != NOT_FOUND:
                    return email
        except requests.RequestException:
            continue
    return NOT_FOUND


def enrich_channel(client: YouTubeClient, ch: dict, cfg: dict) -> dict:
    snippet, stats = ch.get("snippet", {}), ch.get("statistics", {})
    desc = snippet.get("description", "")
    handle = snippet.get("customUrl")
    record = {
        "name": snippet.get("title", NOT_FOUND),
        "platform": "YouTube",
        "profile_url": f"https://www.youtube.com/{handle}" if handle else f"https://www.youtube.com/channel/{ch['id']}",
        "channel_id": ch["id"],
        "followers": int(stats.get("subscriberCount", 0)),
        "total_videos": int(stats.get("videoCount", 0)),
        "country": snippet.get("country", NOT_AVAILABLE),
        "matched_keywords": "; ".join(ch.get("_matched_keywords", [])),
        "bio": " ".join(desc.split())[:300],
    }

    record["email"] = extract_email(desc)
    record["email_source"] = "channel_description" if record["email"] != NOT_FOUND else ""
    record.update(extract_links(desc))

    videos = []
    uploads = ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if uploads:
        try:
            videos = client.get_recent_videos(uploads, cfg["videos_to_analyze"])
        except QuotaExceeded:
            raise
        except Exception as e:
            log.warning("Could not fetch videos for %s: %s", record["name"], e)

    rate, avg_views, n = compute_engagement(videos)
    titles = [v["snippet"]["title"] for v in videos if "snippet" in v]
    record.update({
        "engagement_rate_pct": rate,
        "avg_views": avg_views,
        "videos_analyzed": n,
        "last_upload": max((v["snippet"]["publishedAt"] for v in videos if "snippet" in v), default=NOT_AVAILABLE),
        "recent_titles": " | ".join(titles[:5]),
        "content_themes": ", ".join(extract_themes(titles)) or NOT_AVAILABLE,
    })

    if record["email"] == NOT_FOUND and cfg.get("scrape_websites") and record["website"] != NOT_FOUND:
        email = scrape_website_email(record["website"])
        if email != NOT_FOUND:
            record["email"], record["email_source"] = email, "website"
    return record
