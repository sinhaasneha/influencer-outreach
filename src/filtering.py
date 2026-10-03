"""Stage 3: rule-based filtering + classification. Every decision carries a human-readable reason."""
import re
from datetime import datetime, timezone

NA = ("Not Found", "Not Available", "", None)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", (text or "").lower())


def tier_for(followers: int) -> str:
    if followers < 10_000:
        return "nano (5k-10k)"
    if followers < 50_000:
        return "micro (10k-50k)"
    return "upper-micro (50k-100k)"


def relevance(record: dict, vocab: dict) -> dict:
    """Count niche-vocabulary hits per sub-niche across bio, recent titles and themes."""
    blob = " ".join(str(record.get(k, "")) for k in ("bio", "recent_titles", "content_themes", "matched_keywords"))
    tokens = _words(blob)
    hits = {sub: sum(tokens.count(w) for w in words) for sub, words in vocab.items()}
    total = sum(hits.values())
    ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
    if total == 0:
        category = "unclassified"
    elif len(ranked) > 1 and ranked[1][1] >= 0.5 * ranked[0][1]:
        category = "+".join(sorted(k for k, v in ranked if v >= 0.5 * ranked[0][1]))
    else:
        category = ranked[0][0]
    return {"score": total, "category": category}


def days_since(iso_ts: str, now: datetime | None = None):
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return ((now or datetime.now(timezone.utc)) - dt).days


def evaluate(record: dict, cfg: dict, now: datetime | None = None) -> dict:
    """Return the record plus status (PASS/FAIL), fail_reasons, flags, category, tier, relevance_score."""
    f = cfg["filtering"]
    fails, flags = [], []

    # platform
    if record.get("platform") not in f["allowed_platforms"]:
        fails.append(f"platform {record.get('platform')} not allowed")

    # follower range
    n = record.get("followers", 0)
    if not (cfg["min_followers"] <= n <= cfg["max_followers"]):
        fails.append(f"followers {n:,} outside {cfg['min_followers']:,}-{cfg['max_followers']:,}")

    # engagement
    eng = record.get("engagement_rate_pct")
    if eng in NA:
        fails.append("engagement unavailable (likes hidden or no videos)")
    elif float(eng) < f["min_engagement_pct"]:
        fails.append(f"engagement {eng}% below {f['min_engagement_pct']}%")

    # recency
    d = days_since(record.get("last_upload"), now)
    if d is None:
        fails.append("last upload date unknown")
    elif d > f["max_days_since_upload"]:
        fails.append(f"inactive: last upload {d} days ago")

    # niche relevance
    rel = relevance(record, f["niche_vocab"])
    if rel["score"] < f["min_relevance_hits"]:
        fails.append(f"low niche relevance ({rel['score']} hits < {f['min_relevance_hits']})")

    # brand safety
    blob = " ".join(str(record.get(k, "")) for k in ("bio", "recent_titles")).lower()
    bad = [w for w in f["brand_blocklist"] if w in blob]
    if bad:
        fails.append(f"brand-fit: contains blocked terms {bad}")

    # geography
    country = record.get("country")
    if f["allowed_countries"]:
        if country in NA:
            flags.append("country unknown")
        elif country not in f["allowed_countries"]:
            fails.append(f"country {country} not in {f['allowed_countries']}")

    out = dict(record)
    out.update({
        "category": rel["category"],
        "tier": tier_for(n),
        "relevance_score": rel["score"],
        "status": "PASS" if not fails else "FAIL",
        "fail_reasons": "; ".join(fails),
        "flags": "; ".join(flags),
        "outreach_ready": "Yes" if (not fails and record.get("email") not in NA) else "No",
    })
    return out


def filter_all(records: list[dict], cfg: dict, now: datetime | None = None) -> list[dict]:
    return [evaluate(r, cfg, now) for r in records]
