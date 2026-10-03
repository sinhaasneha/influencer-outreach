"""Stage 1: find channels in the target follower range."""
import logging

from .youtube import YouTubeClient, QuotaExceeded

log = logging.getLogger(__name__)


def discover(client: YouTubeClient, cfg: dict) -> list[dict]:
    """Return raw channel resources whose subscriber count is within [min, max]."""
    seen: set[str] = set()
    found: dict[str, dict] = {}
    matched_by: dict[str, list[str]] = {}
    lo, hi = cfg["min_followers"], cfg["max_followers"]

    for kw in cfg["keywords"]:
        if len(found) >= cfg["target_candidates"]:
            break
        log.info("Searching: %r", kw)
        try:
            ids = list(client.search_channels(
                kw, pages=cfg["search_pages_per_keyword"],
                region_code=cfg.get("region_code"), language=cfg.get("relevance_language")))
            new_ids = [c for c in dict.fromkeys(ids) if c not in seen]
            seen.update(new_ids)
            for ch in client.get_channels(new_ids):
                stats = ch.get("statistics", {})
                if stats.get("hiddenSubscriberCount") or "subscriberCount" not in stats:
                    continue  # can't verify follower count -> skip rather than guess
                subs = int(stats["subscriberCount"])
                if lo <= subs <= hi:
                    found[ch["id"]] = ch
                    matched_by.setdefault(ch["id"], []).append(kw)
        except QuotaExceeded:
            log.warning("Quota exhausted - continuing with %d channels found so far", len(found))
            break
        except Exception as e:  # one bad keyword shouldn't kill the run
            log.error("Search for %r failed: %s", kw, e)

    for cid, ch in found.items():
        ch["_matched_keywords"] = matched_by[cid]
    log.info("Discovery done: %d in-range channels from %d unique candidates", len(found), len(seen))
    return list(found.values())
