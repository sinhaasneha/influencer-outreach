"""Stage 4: LLM-generated, validated outreach (email + Instagram DM) grounded ONLY in collected data."""
import json
import logging
import re
 
log = logging.getLogger(__name__)
 
SYSTEM_PROMPT = """You write short, natural influencer outreach for a brand.
 
HARD RULES
- Use ONLY the facts provided in the influencer data. Never invent video titles, products, metrics, locations, or personal details.
- Reference at least one concrete signal from their recent video titles or content themes, paraphrased naturally.
- Never use praise words such as love, loved, adore, impressed, amazing, stunning or "great fit". Say you noticed or came across a video, and refer only to what the title says. Do not infer anything else about their style, budget, skin type, focus or niche beyond the title.
- Never describe their audience or followers (who they are, what they like). You may only say the code is "for your followers".
- If the channel name is not clearly a person's name or a brand (for example a generic phrase like "Makeup tutorial"), greet with "Hi there".
- Only offer what the OFFER line states. Never mention payment, fees or sponsorship money unless the OFFER says so.
- Open each email differently: vary the first sentence and never start with "We loved".
- No placeholders like [Name] or {brand}. No hashtags, no emojis in the email. At most one emoji in the DM.
- Greet by first name only if the channel name looks like a person's name.
- Mention the proposed collaboration angle and a clear value for them. End the email with a soft call to action and the sender sign-off "Team <brand>".
- Vary your phrasing; do not open with "I hope this email finds you well" or similar cliches.
 
OUTPUT: return ONLY a JSON object, no markdown fences:
{"email_subject": "...", "email_body": "...", "instagram_dm": "..."}"""
 
STOP = set("""the a an and or of to in on for with my your our is are was be this that these those it its i you we how what why
when new best top video videos vlog day week get look routine review from at by as up out all about easy simple full""".split())
 
EMOJI_RE = re.compile("[\U00010000-\U0010ffff\u2600-\u27bf\ufe0f\u200d]")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
CTA_RE = re.compile(r"subscribe|follow me|like and share|link in bio", re.I)
PRAISE_RE = re.compile(r"\b(loved|adored?|love (?:your|the|this|how)|impressed|impressive|amazing|stunning|"
                       r"fantastic|admire[ds]?|great fit|perfect fit)\b", re.I)
AUDIENCE_RE = re.compile(r"\byour (?:audience|followers|community|viewers)\b[^.!?]{0,25}\b"
                         r"(?:of|who|are|is|will|would|love|enjoy|appreciate)\b", re.I)
 
 
def clean_title(text: str) -> str:
    """Strip hashtags, phone numbers, URLs, emojis and subscribe-style calls to action from scraped text."""
    text = re.sub(r"https?://\S+|#\w+", " ", text or "")
    text = PHONE_RE.sub(" ", text)
    text = EMOJI_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip(" |-")
 
 
def clean_titles(joined: str) -> str:
    parts = [clean_title(t) for t in (joined or "").split(" | ")]
    return " | ".join(t for t in parts if len(t) >= 8 and not CTA_RE.search(t))
 
 
def count_words(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text or ""))
 
 
def pick_angle(record: dict, cfg: dict) -> str:
    tier = record.get("tier", "micro").split(" ")[0]
    angles = cfg["personalization"]["angle_by_tier"]
    return angles.get(tier, angles["micro"])
 
 
def build_user_prompt(record: dict, cfg: dict, angle: str, feedback: str = "") -> str:
    p = cfg["personalization"]
    brand = p["brand"]
    ew, dw = p["email_words"], p["dm_words"]
    prompt = f"""BRAND: {brand['name']} - {brand['product']}
OFFER: {brand['offer']}
COLLAB ANGLE: {angle}
 
INFLUENCER DATA
- Channel name: {record.get('name')}
- Platform: {record.get('platform')}
- Niche category: {record.get('category')}
- Followers: {record.get('followers'):,}
- Content themes: {record.get('content_themes')}
- Recent video titles: {clean_titles(record.get('recent_titles', ''))}
- Bio excerpt: {clean_title(record.get('bio', ''))}
 
LENGTH LIMITS (count words strictly)
- email_body: {ew[0]}-{ew[1]} words (including greeting and sign-off)
- instagram_dm: {dw[0]}-{dw[1]} words"""
    if feedback:
        prompt += f"\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED: {feedback}\nFix this and return the JSON again."
    return prompt
 
 
def parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start:end + 1])
 
 
def signal_words(record: dict) -> set:
    blob = f"{clean_titles(record.get('recent_titles', ''))} {record.get('content_themes', '')}".lower()
    return {w for w in re.findall(r"[a-z]{4,}", blob) if w not in STOP}
 
 
def validate(msg: dict, record: dict, cfg: dict) -> list[str]:
    """Return a list of problems (empty = valid)."""
    p = cfg["personalization"]
    problems = []
    for key in ("email_subject", "email_body", "instagram_dm"):
        if not isinstance(msg.get(key), str) or not msg[key].strip():
            problems.append(f"missing {key}")
    if problems:
        return problems
    ew, dw = p["email_words"], p["dm_words"]
    n_email, n_dm = count_words(msg["email_body"]), count_words(msg["instagram_dm"])
    if not ew[0] <= n_email <= ew[1]:
        problems.append(f"email_body has {n_email} words, must be {ew[0]}-{ew[1]}")
    if not dw[0] <= n_dm <= dw[1]:
        problems.append(f"instagram_dm has {n_dm} words, must be {dw[0]}-{dw[1]}")
    full = " ".join(msg.values())
    if re.search(r"\[[^\]]+\]|\{[^}]+\}|<[^>]+>", full):
        problems.append("contains a placeholder like [Name] or {brand}")
    if re.search(r"\bpaid\b|\bsponsorship\b|\bfee\b", full, re.I) and not re.search(
            r"paid|sponsor|fee", p["brand"]["offer"], re.I):
        problems.append("mentions payment/sponsorship which is not in the brand offer")
    if PRAISE_RE.search(full):
        problems.append("uses unsupported praise (love, impressed, amazing, great fit...) - just say you noticed the video")
    if re.search(r"\d{7,}", full.replace(" ", "")):
        problems.append("contains a phone-number-like digit sequence")
    if AUDIENCE_RE.search(full):
        problems.append("makes claims about the influencer's audience, which is not in the data")
    sigs = signal_words(record)
    if sigs and not (sigs & set(re.findall(r"[a-z]{4,}", msg["email_body"].lower()))):
        problems.append("email does not reference any of the influencer's actual content themes/titles")
    if sigs and not (sigs & set(re.findall(r"[a-z]{4,}", msg["instagram_dm"].lower()))):
        problems.append("DM does not reference any of the influencer's actual content themes/titles")
    return problems
 
 
class AnthropicLLM:
    def __init__(self, model: str, max_tokens: int = 700):
        import anthropic  # imported lazily so tests/other stages don't need it
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self.model, self.max_tokens = model, max_tokens
 
    def complete(self, system: str, user: str) -> str:
        resp = self.client.messages.create(model=self.model, max_tokens=self.max_tokens, system=system,
                                           messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
 
 
class OpenAICompatibleLLM:
    """Any /chat/completions endpoint (Groq, Gemini, OpenRouter, Ollama...). Retries on rate limits."""
 
    def __init__(self, base_url: str, model: str, api_key: str = "", delay: float = 2.0, max_tokens: int = 2500):
        import requests
        self.requests = requests
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model, self.delay, self.max_tokens = model, delay, max_tokens
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
 
    def complete(self, system: str, user: str) -> str:
        import time
        body = {"model": self.model, "max_tokens": self.max_tokens, "temperature": 0.7,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if "gpt-oss" in self.model:
            body["reasoning_effort"] = "low"  # stop the model burning its token budget on thinking
        resp = None
        for attempt in range(1, 5):
            resp = self.requests.post(self.url, headers=self.headers, json=body, timeout=60)
            if resp.status_code in (429, 500, 502, 503):  # rate limit / transient -> back off and retry
                time.sleep(5 * attempt)
                continue
            if resp.status_code >= 400:
                raise RuntimeError(f"LLM API error {resp.status_code}: {resp.text[:300]}")
            time.sleep(self.delay)
            choice = resp.json()["choices"][0]
            content = (choice["message"].get("content") or "").strip()
            if not content:
                raise RuntimeError(f"model returned empty content (finish_reason={choice.get('finish_reason')})")
            return content
        raise RuntimeError(f"LLM endpoint kept returning errors (last status {resp.status_code})")
 
 
def make_llm(cfg: dict):
    import os
    p = cfg["personalization"]
    if not p.get("model"):
        raise SystemExit("Set personalization.model in config.yaml (use a current model name from your provider).")
    if p.get("provider", "anthropic") == "anthropic":
        return AnthropicLLM(p["model"])
    key = os.getenv(p.get("api_key_env") or "", "") if p.get("api_key_env") else ""
    if p.get("api_key_env") and not key:
        raise SystemExit(f"Missing {p['api_key_env']} in .env")
    return OpenAICompatibleLLM(p["base_url"], p["model"], key, p.get("request_delay_seconds", 2))
 
 
def generate_for(record: dict, llm, cfg: dict) -> dict:
    """Generate + validate with retries. Never raises; failure is recorded in `message_status`."""
    angle = pick_angle(record, cfg)
    feedback, last_problems = "", []
    for attempt in range(1, cfg["personalization"]["max_retries"] + 1):
        try:
            raw = llm.complete(SYSTEM_PROMPT, build_user_prompt(record, cfg, angle, feedback))
            msg = parse_json(raw)
        except Exception as e:
            feedback = f"output was not valid JSON ({e})"
            last_problems = [feedback]
            continue
        last_problems = validate(msg, record, cfg)
        if not last_problems:
            return {"name": record["name"], "email": record.get("email"), "instagram": record.get("instagram"),
                    "profile_url": record.get("profile_url"), "collab_angle": angle,
                    "email_subject": msg["email_subject"].strip(), "email_body": msg["email_body"].strip(),
                    "instagram_dm": msg["instagram_dm"].strip(),
                    "email_words": count_words(msg["email_body"]), "dm_words": count_words(msg["instagram_dm"]),
                    "message_status": "GENERATED", "attempts": attempt}
        feedback = "; ".join(last_problems)
    log.warning("Giving up on %s: %s", record.get("name"), last_problems)
    return {"name": record["name"], "email": record.get("email"), "instagram": record.get("instagram"),
            "profile_url": record.get("profile_url"), "collab_angle": angle, "email_subject": "", "email_body": "",
            "instagram_dm": "", "email_words": 0, "dm_words": 0,
            "message_status": "FAILED: " + "; ".join(last_problems),
            "attempts": cfg["personalization"]["max_retries"]}
 