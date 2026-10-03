from src.enrichment import (NOT_AVAILABLE, NOT_FOUND, compute_engagement, extract_email,
                            extract_links, extract_themes)


def test_email_found_and_lowercased():
    assert extract_email("Business: Hello@Sarah-Beauty.com, DM me") == "hello@sarah-beauty.com"


def test_email_not_found_is_marked_not_guessed():
    assert extract_email("no contact here, see my website") == NOT_FOUND
    assert extract_email("") == NOT_FOUND


def test_image_filenames_not_treated_as_email():
    assert extract_email("logo@2x.png") == NOT_FOUND


def test_links():
    d = "IG: https://instagram.com/sarah.glow shop https://sarahglow.com/links tiktok.com/@sarahglow"
    links = extract_links(d)
    assert links["instagram"].endswith("sarah.glow")
    assert links["website"].startswith("https://sarahglow.com")
    assert links["tiktok"].endswith("@sarahglow")


def test_engagement():
    vids = [{"statistics": {"viewCount": "1000", "likeCount": "80", "commentCount": "20"}},
            {"statistics": {"viewCount": "2000", "likeCount": "100", "commentCount": "100"}}]
    rate, avg, n = compute_engagement(vids)
    assert (rate, avg, n) == (10.0, 1500, 2)


def test_engagement_hidden_likes():
    assert compute_engagement([{"statistics": {"viewCount": "500"}}]) == (NOT_AVAILABLE, NOT_AVAILABLE, 0)


def test_themes():
    assert "skincare" in extract_themes(["My skincare night routine", "Skincare mistakes", "Budget skincare"])
