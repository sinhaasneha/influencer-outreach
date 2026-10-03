Automated Micro-Influencer Outreach System

EDXSO AI Engineer Intern - Assignment 1

An end-to-end pipeline that discovers micro-influencers, filters and classifies them, enriches their profiles, writes personalized outreach with an LLM, and simulates delivery with a duplicate-safe outreach log.

Discovery -> Enrichment -> Filtering -> AI Personalization -> Review -> Sending -> Tracking
 (YouTube)    (metrics,     (rules,       (email + DM,         (approve)  (dry run /   (SQLite +
              emails)       reasons)      validated)                       SMTP)        CSV)

Niche: Fashion & Beauty. Platform: YouTube. Demo brand: "Lumera" is a fictional brand used to generate sample outreach. No real creator was contacted; all sending was a dry run.

Results of the test run
Stage	Result
Discovery (8 keyword searches)	750 unique channels scanned, 87 in the 5k-100k follower range
Enrichment	87 profiles enriched, 25 with a public contact email (29%)
Filtering	48 passed, 39 failed (each with a stated reason); 16 of the 48 passers have an email (outreach-ready)
Personalization	48 / 48 email + Instagram DM pairs generated, 0 failed validation
Sending (dry run)	16 simulated, 32 skipped (SKIPPED_NO_EMAIL), 0 failed. A second run simulated 0, proving duplicate prevention
Technology stack and tools
Python 3.11; requests, PyYAML, python-dotenv, sqlite3, smtplib, pytest
YouTube Data API v3: channel discovery and metrics (free quota)
Groq API (OpenAI-compatible /chat/completions), model openai/gpt-oss-120b. The provider is swappable in config.yaml (Groq, Gemini, OpenRouter, Ollama, or the Claude API)
SQLite: outreach log and duplicate prevention
Gmail SMTP (app password): live sending, implemented but used only in dry-run mode for this submission
Project structure
main.py                 CLI entry point (discover, enrich, filter, personalize, approve, send)
config.yaml             all niche keywords, thresholds, prompt settings and sending rules
src/youtube.py          API client: retries, backoff, quota detection
src/discovery.py        stage 1: find channels in the follower range
src/enrichment.py       stage 2: metrics, email and link extraction, themes
src/filtering.py        stage 3: PASS/FAIL rules with reasons, classification
src/personalization.py  stage 4: LLM prompt, validation, retry loop
src/sending.py          stage 5: approval gate, dry-run/SMTP, SQLite log, DM queue
tests/                  unit tests (pytest)
data/                   generated outputs
Setup
bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # Mac/Linux: cp .env.example .env

Fill in .env:

YOUTUBE_API_KEY=...        # Google Cloud Console -> enable "YouTube Data API v3" -> API key (public data)
LLM_API_KEY=...            # free key from Groq (or another OpenAI-compatible provider)
# SMTP_* values are only needed for `send --live`

Then in config.yaml, set personalization.model to a current model from your provider and edit the brand block.

Run
bash
python main.py discover      # -> data/candidates.json
python main.py enrich        # -> data/influencers_enriched.csv / .json
python main.py filter        # -> data/influencers_filtered.csv, data/shortlist.json
python main.py personalize   # -> data/messages.csv / .json   (--limit 5 to try a few first)
python main.py approve --all # human review gate (read data/messages.csv first)
python main.py send          # DRY RUN -> data/outreach_tracker.csv, data/dm_queue.csv
python -m pytest -q          # unit tests

python main.py run performs discover + enrich + filter. filter and send need no API key, so thresholds can be tuned and re-run instantly.

Data sources and discovery methodology

YouTube Data API v3 only. For each keyword in config.yaml (skincare routine, makeup tutorial, fashion haul, outfit ideas, beauty review, get ready with me, capsule wardrobe, hair care routine) the system runs a channel search (2 pages x 50), de-duplicates channel IDs, fetches channel statistics in batches of 50, and keeps channels with 5,000-100,000 subscribers. Channels that hide their subscriber count are skipped rather than guessed.

Enrichment process

For each candidate, using the last 10 uploads (2 API calls per channel):

Engagement rate = mean of (likes + comments) / views per video. Videos with hidden likes are excluded; if none remain the value is Not Available.
Contact email: regex over the channel description only. If none, the value is Not Found. Emails are never guessed or generated. (Optional scrape_websites: true also checks the creator's own website, respecting robots.txt.)
Links: website, Instagram and TikTok extracted from the description; otherwise Not Found.
Content themes: top keywords from recent video titles; recent titles, country, last upload date and bio excerpt are also stored.
Filtering and classification logic

Every influencer is evaluated against all rules, and all failed rules are listed in fail_reasons:

Rule	Default
Platform	YouTube
Follower range	5,000-100,000
Engagement	at least 1.5% (unavailable engagement = fail)
Recency	last upload within 60 days
Niche relevance	at least 3 niche-vocabulary hits across bio, titles and themes
Brand safety	blocklist of terms (gambling, betting, adult, ...)
Geography	optional country allow-list (unknown country is flagged, not failed)

Output columns include status (PASS/FAIL), fail_reasons, flags, category (beauty / fashion / beauty+fashion), tier (nano / micro / upper-micro), relevance_score and outreach_ready (passed and has an email).

AI personalization
Model: openai/gpt-oss-120b on Groq, temperature 0.7, low reasoning effort, JSON output.
Input: only collected data (channel name, niche, themes, cleaned recent video titles, bio excerpt, follower tier) plus the brand, offer and collaboration angle.
Dynamic angle by follower tier: nano = barter; micro = affiliate code / UGC; upper-micro = ambassador program with higher commission. So messages are not one template with a name swapped.
Title cleaning: phone numbers, hashtags, emojis, URLs and "subscribe" calls to action are stripped before the model sees titles.
Prompt rules: use only provided facts; no invented details; say the creator's video was "noticed" and describe only what the title says; no claims about their audience; offer only what the brand offer states; greet with "Hi there" if the channel name is not a person's name; vary openings.
Automatic validation (failure triggers regeneration with the reason fed back, up to max_retries): email 60-90 words; DM 15-30 words; no placeholders; no payment wording unless in the offer; no unsupported praise words (love, impressed, amazing, "great fit"...); no phone-number-like digits; no claims about the audience; must reference a real theme or title word from that creator's data.
A record that never passes validation is marked FAILED: <reason> and is never sent. Generation saves after each influencer, so interrupted runs resume where they stopped.
Sending layer
Eligibility: only a valid email address and a GENERATED message. Others are logged as SKIPPED_NO_EMAIL, SKIPPED_INVALID_EMAIL or SKIPPED_NO_MESSAGE.
Review gate: approve must be run before a live send.
Dry run by default: send simulates delivery and records SIMULATED; send --live sends through Gmail SMTP using an app password.
Duplicate prevention: SQLite UNIQUE constraints on profile URL and lowercase email. A shared inbox is only contacted once, and sent rows are never resent. Re-running send is idempotent (verified: second run simulated 0).
Safety: per-run cap, delay between live sends, suppression list (data/suppression.txt), opt-out footer on live emails. Failures are logged with the error and retried on the next live run.
Outreach log: data/outreach.db (source of truth) and data/outreach_tracker.csv with Influencer, Email, Message Generated, Sent, Date, Status, Error.
Instagram DMs are not auto-sent. The Meta API does not permit unsolicited creator DMs, and automating the app would breach its terms. DMs are written to data/dm_queue.csv as PENDING_MANUAL for copy-and-paste sending; where no handle was found the Instagram column says Not Found.
Error handling

API retries with exponential backoff; quota exhaustion saves partial results; one bad channel never stops a batch; missing data is explicitly marked Not Found / Not Available; LLM failures and invalid output are retried, then recorded as FAILED rather than crashing; sends are logged per row.

Scalability (50 to 500+ influencers)

Everything is driven by config.yaml: add keywords or pages to widen discovery. YouTube's free quota is 10,000 units per day; a search page costs 100 units and enrichment about 2 units per channel, so a few hundred channels fit in one day and larger runs can be spread across days. Personalization and sending are resumable and capped per run, and the SQLite log scales to large batches. The LLM provider can be swapped to a higher-throughput endpoint without code changes.

Limitations
Email coverage is partial (25 of 87 enriched profiles). Many creators hide business emails behind YouTube's "View email address" button, which the API cannot read. No emails were guessed.
YouTube only. Instagram and TikTok handles are only captured if they appear in the channel description, so most are Not Found.
Audience demographics (age, gender, geography) are not available from the YouTube API and are not collected; these are optional fields in the brief.
Engagement is an approximation from the last 10 videos, and is unavailable when a creator hides likes.
Relevance and brand-fit are keyword-based. Some non-creator channels (for example retail shops) or off-brand creators can pass; the blocklist and vocabulary in config.yaml can be tuned.
Personalization is based on video titles only. When a creator's titles are generic or hashtag-only, messages are accurate but less specific.
Live sending was implemented and unit-tested with a fake sender, but not used against real creators. The submission demonstrates dry-run delivery only.
Lumera is a fictional demo brand, so the sample offers are illustrative.
Screenshots

Add under docs/screenshots/: pipeline run output, influencers_filtered.csv (PASS/FAIL with reasons), messages.csv, outreach_tracker.csv, the two send runs (second run showing 0 new), and the passing pytest result. Mask any real email addresses before committing.#   i n f l u e n c e r - o u t r e a c h  
 