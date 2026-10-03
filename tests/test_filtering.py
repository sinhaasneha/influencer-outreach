from datetime import datetime, timezone

import yaml

from src.filtering import evaluate, relevance, tier_for

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
CFG = yaml.safe_load(open("config.yaml"))


def good(**over):
    r = {"platform": "YouTube", "followers": 25_000, "engagement_rate_pct": 4.2,
         "last_upload": "2026-09-20T10:00:00Z", "country": "IN", "email": "a@b.com",
         "bio": "Skincare and makeup tutorials", "recent_titles": "My skincare night routine | Drugstore makeup haul",
         "content_themes": "skincare, makeup", "matched_keywords": "skincare routine"}
    r.update(over)
    return r


def test_good_record_passes_and_is_outreach_ready():
    r = evaluate(good(), CFG, NOW)
    assert r["status"] == "PASS" and r["fail_reasons"] == "" and r["outreach_ready"] == "Yes"
    assert r["category"] == "beauty" and r["tier"].startswith("micro")


def test_pass_without_email_is_not_outreach_ready():
    r = evaluate(good(email="Not Found"), CFG, NOW)
    assert r["status"] == "PASS" and r["outreach_ready"] == "No"


def test_low_engagement_fails_with_reason():
    r = evaluate(good(engagement_rate_pct=0.4), CFG, NOW)
    assert r["status"] == "FAIL" and "engagement 0.4%" in r["fail_reasons"]


def test_unavailable_engagement_fails():
    assert "unavailable" in evaluate(good(engagement_rate_pct="Not Available"), CFG, NOW)["fail_reasons"]


def test_inactive_channel_fails():
    r = evaluate(good(last_upload="2026-01-01T00:00:00Z"), CFG, NOW)
    assert "inactive" in r["fail_reasons"]


def test_off_niche_fails():
    r = evaluate(good(bio="Minecraft let's plays", recent_titles="Minecraft hardcore", content_themes="minecraft",
                      matched_keywords=""), CFG, NOW)
    assert "low niche relevance" in r["fail_reasons"]


def test_blocklist_fails():
    assert "brand-fit" in evaluate(good(bio="skincare and online casino tips"), CFG, NOW)["fail_reasons"]


def test_multiple_reasons_are_all_listed():
    r = evaluate(good(followers=500, engagement_rate_pct=0.1), CFG, NOW)
    assert r["fail_reasons"].count(";") >= 1


def test_geography_filter_and_unknown_flag():
    cfg = {**CFG, "filtering": {**CFG["filtering"], "allowed_countries": ["IN"]}}
    assert "country US" in evaluate(good(country="US"), cfg, NOW)["fail_reasons"]
    assert evaluate(good(country="Not Available"), cfg, NOW)["flags"] == "country unknown"


def test_dual_category():
    vocab = CFG["filtering"]["niche_vocab"]
    r = relevance({"bio": "fashion outfit style haul skincare makeup beauty"}, vocab)
    assert r["category"] == "beauty+fashion"


def test_tiers():
    assert tier_for(6000).startswith("nano") and tier_for(80000).startswith("upper")
