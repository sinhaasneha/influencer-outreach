import json
 
import yaml
 
from src.personalization import count_words, generate_for, parse_json, pick_angle, validate
 
CFG = yaml.safe_load(open("config.yaml"))
REC = {"name": "Sarah Glow", "email": "s@glow.com", "instagram": "https://instagram.com/sarahglow",
       "profile_url": "https://youtube.com/@sarahglow", "platform": "YouTube", "followers": 25000,
       "tier": "micro (10k-50k)", "category": "beauty", "content_themes": "skincare, sunscreen",
       "recent_titles": "My night skincare routine | Best drugstore sunscreen", "bio": "Skincare lover"}
 
EMAIL = ("Hi Sarah, your recent breakdown of the best drugstore sunscreen options was genuinely useful, and your "
         "skincare audience looks like a perfect match for GlowLane's clean-ingredient range. We would love to send "
         "you a free product kit and set up an affiliate code so you earn commission on every sale your community "
         "makes. If that sounds interesting, reply here and we can share details. Warm regards, Team GlowLane")
DM = "Hi Sarah! Your drugstore sunscreen video was so helpful. Would you be open to an affiliate collab with GlowLane?"
 
 
class FakeLLM:
    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), 0
 
    def complete(self, system, user):
        self.calls += 1
        return self.outputs.pop(0)
 
 
def good_json():
    return json.dumps({"email_subject": "Collab idea for your skincare channel", "email_body": EMAIL, "instagram_dm": DM})
 
 
def test_fixture_lengths_are_valid():
    assert 60 <= count_words(EMAIL) <= 90 and 15 <= count_words(DM) <= 30
 
 
def test_happy_path():
    out = generate_for(REC, FakeLLM([good_json()]), CFG)
    assert out["message_status"] == "GENERATED" and out["attempts"] == 1
    assert "affiliate" in out["collab_angle"]  # micro tier -> affiliate angle
 
 
def test_json_in_code_fence_is_parsed():
    assert parse_json("```json\n{\"a\": 1}\n```") == {"a": 1}
 
 
def test_retry_after_bad_length_then_success():
    bad = json.dumps({"email_subject": "x", "email_body": "Too short.", "instagram_dm": DM})
    llm = FakeLLM([bad, good_json()])
    out = generate_for(REC, llm, CFG)
    assert out["message_status"] == "GENERATED" and llm.calls == 2
 
 
def test_gives_up_after_max_retries_without_raising():
    out = generate_for(REC, FakeLLM(["not json"] * 3), CFG)
    assert out["message_status"].startswith("FAILED") and out["email_body"] == ""
 
 
def test_placeholder_rejected():
    msg = {"email_subject": "s", "email_body": EMAIL.replace("Sarah", "[Name]"), "instagram_dm": DM}
    assert any("placeholder" in p for p in validate(msg, REC, CFG))
 
 
def test_generic_message_without_signal_rejected():
    generic = ("Hello there, we are a growing brand and think your audience would adore our products. We would like "
               "to send you a free kit and discuss how we can work together on something mutually beneficial in the "
               "coming weeks. Please reply if you are open to learning more about the opportunity. Kind regards, Team GlowLane")
    msg = {"email_subject": "s", "email_body": generic, "instagram_dm": DM}
    assert any("does not reference" in p for p in validate(msg, REC, CFG))
 
 
def test_angle_scales_with_tier():
    assert "barter" in pick_angle({"tier": "nano (5k-10k)"}, CFG)
    assert "ambassador" in pick_angle({"tier": "upper-micro (50k-100k)"}, CFG)
 
 
def test_openai_compatible_client_parses_response_and_retries_on_429():
    from src.personalization import OpenAICompatibleLLM
 
    class Resp:
        def __init__(self, code, data=None):
            self.status_code, self._d = code, data or {}
 
        def raise_for_status(self):
            assert self.status_code == 200
 
        def json(self):
            return self._d
 
    class FakeRequests:
        def __init__(self):
            self.calls = []
 
        def post(self, url, headers, json, timeout):
            self.calls.append((url, headers, json))
            if len(self.calls) == 1:
                return Resp(429)
            return Resp(200, {"choices": [{"message": {"content": "{\"ok\": 1}"}}]})
 
    import time
    time.sleep = lambda s: None  # don't actually wait in tests
    llm = OpenAICompatibleLLM("https://x.example/v1/", "m", "KEY", delay=0)
    llm.requests = FakeRequests()
    assert llm.complete("sys", "usr") == "{\"ok\": 1}"
    assert llm.requests.calls[0][0] == "https://x.example/v1/chat/completions"
    assert llm.requests.calls[0][1]["Authorization"] == "Bearer KEY" and len(llm.requests.calls) == 2
 
 
def test_make_llm_requires_model():
    import pytest
    from src.personalization import make_llm
    cfg = {**CFG, "personalization": {**CFG["personalization"], "model": ""}}
    with pytest.raises(SystemExit):
        make_llm(cfg)
 
 
def _msg(email=EMAIL, dm=DM):
    return {"email_subject": "s", "email_body": email, "instagram_dm": dm}
 
 
def test_love_loved_rejected():
    assert any("love" in p for p in validate(_msg(dm=DM.replace("was so helpful", "was so helpful, loved it")), REC, CFG))
 
 
def test_audience_claims_rejected():
    bad = EMAIL.replace("your skincare audience looks", "your audience of beginner makeup fans will appreciate")
    assert any("audience" in p for p in validate(_msg(email=bad), REC, CFG))
 
 
def test_phone_number_rejected():
    assert any("phone" in p for p in validate(_msg(email=EMAIL + " Call 8282826136"), REC, CFG))
 
 
def test_payment_words_rejected_when_not_in_offer():
    assert any("payment" in p for p in validate(_msg(email=EMAIL.replace("free product kit", "paid sponsorship")), REC, CFG))
 
 
def test_clean_titles_strips_phone_hashtags_and_cta():
    from src.personalization import clean_titles
    out = clean_titles("📞 8282826136 | Subscribe For More #makeuptutorial #makeup | Soft glam tutorial for beginners")
    assert "8282826136" not in out and "#" not in out and "Subscribe" not in out and "Soft glam" in out
 
 
def test_impressed_rejected():
    bad = EMAIL.replace("was genuinely useful", "left us impressed")
    assert any("praise" in p for p in validate(_msg(email=bad), REC, CFG))
 