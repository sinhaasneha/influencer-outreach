"""CLI entry point.  Usage:
    python main.py discover      # find channels -> data/candidates.json
    python main.py enrich        # enrich candidates -> data/influencers_enriched.csv/json
    python main.py filter        # PASS/FAIL + reasons -> data/influencers_filtered.csv, data/shortlist.json
    python main.py personalize   # Claude writes email + DM for shortlist -> data/messages.csv/json
    python main.py approve --all # human review gate (or --name "Channel Name")
    python main.py send          # DRY RUN (default): simulates sending, logs to data/outreach.db
    python main.py send --live   # real SMTP send of approved emails
    python main.py run           # discover + enrich + filter
"""
import argparse
import logging
import os

import yaml
from dotenv import load_dotenv

from src.discovery import discover
from src.enrichment import enrich_channel
from src.filtering import filter_all
from src.io_utils import load_json, save_csv, save_json
from src.personalization import generate_for, make_llm
from src.sending import OutreachTracker, SMTPSender, run_send
from src.youtube import QuotaExceeded, YouTubeClient

CANDIDATES = "data/candidates.json"
ENRICHED_JSON = "data/influencers_enriched.json"
ENRICHED_CSV = "data/influencers_enriched.csv"
FILTERED_CSV = "data/influencers_filtered.csv"
SHORTLIST = "data/shortlist.json"
MESSAGES_JSON = "data/messages.json"
MESSAGES_CSV = "data/messages.csv"
TRACKER_CSV = "data/outreach_tracker.csv"
DM_QUEUE_CSV = "data/dm_queue.csv"


def cmd_discover(client, cfg):
    channels = discover(client, cfg)
    save_json(CANDIDATES, channels)
    print(f"Saved {len(channels)} candidates -> {CANDIDATES}")


def cmd_enrich(client, cfg):
    channels = load_json(CANDIDATES)
    records = []
    for i, ch in enumerate(channels, 1):
        try:
            records.append(enrich_channel(client, ch, cfg))
        except QuotaExceeded:
            logging.warning("Quota exhausted after %d channels - saving partial results", len(records))
            break
        except Exception as e:  # never let one bad profile stop the batch
            logging.error("Skipping %s: %s", ch.get("id"), e)
        if i % 10 == 0:
            logging.info("Enriched %d/%d", i, len(channels))
    save_json(ENRICHED_JSON, records)
    save_csv(ENRICHED_CSV, records)
    with_email = sum(1 for r in records if r["email"] != "Not Found")
    print(f"Enriched {len(records)} profiles ({with_email} with email) -> {ENRICHED_CSV}")


def cmd_filter(cfg):
    records = filter_all(load_json(ENRICHED_JSON), cfg)
    save_csv(FILTERED_CSV, records)
    shortlist = [r for r in records if r["status"] == "PASS"]
    save_json(SHORTLIST, shortlist)
    ready = sum(1 for r in shortlist if r["outreach_ready"] == "Yes")
    print(f"{len(shortlist)}/{len(records)} passed ({ready} outreach-ready with email) -> {FILTERED_CSV}")


def cmd_personalize(cfg, limit=None):
    shortlist = load_json(SHORTLIST)
    try:
        done = {m["name"]: m for m in load_json(MESSAGES_JSON)}
    except FileNotFoundError:
        done = {}
    llm = make_llm(cfg)
    todo = [r for r in shortlist if done.get(r["name"], {}).get("message_status") != "GENERATED"]
    for r in todo[:limit]:
        done[r["name"]] = generate_for(r, llm, cfg)
        save_json(MESSAGES_JSON, list(done.values()))  # save as we go -> safe to interrupt and resume
    messages = list(done.values())
    save_json(MESSAGES_JSON, messages)
    save_csv(MESSAGES_CSV, messages)
    ok = sum(1 for m in messages if m["message_status"] == "GENERATED")
    print(f"{ok}/{len(messages)} message pairs generated -> {MESSAGES_CSV}")


def _tracker(cfg):
    t = OutreachTracker(cfg["sending"]["db_path"])
    t.register_all(load_json(MESSAGES_JSON))
    return t


def cmd_approve(cfg, name=None, approve_all=False):
    if not (name or approve_all):
        raise SystemExit("Use --all or --name \"Channel Name\" (review data/messages.csv first!)")
    n = _tracker(cfg).approve(name)
    print(f"Approved {n} message(s)")


def cmd_send(cfg, live=False, limit=None):
    tracker = _tracker(cfg)
    sender = SMTPSender.from_env() if live else None
    stats = run_send(tracker, sender, cfg, live, limit)
    tracker.export_tracker(TRACKER_CSV)
    tracker.export_dm_queue(DM_QUEUE_CSV)
    mode = "LIVE" if live else "DRY RUN"
    print(f"[{mode}] {stats} | log summary: {tracker.summary()}")
    print(f"Tracker -> {TRACKER_CSV} | Instagram DMs to send manually -> {DM_QUEUE_CSV}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["discover", "enrich", "filter", "personalize", "approve", "send", "run"])
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--limit", type=int, default=None, help="max influencers to process (cost/safety control)")
    parser.add_argument("--live", action="store_true", help="actually send emails (default is dry run)")
    parser.add_argument("--all", action="store_true", help="approve all pending messages")
    parser.add_argument("--name", default=None, help="approve one influencer by channel name")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv()
    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if args.command == "filter":  # no API key needed
        return cmd_filter(cfg)
    if args.command == "personalize":  # needs only your LLM provider key
        return cmd_personalize(cfg, args.limit)
    if args.command == "approve":
        return cmd_approve(cfg, args.name, args.all)
    if args.command == "send":
        return cmd_send(cfg, args.live, args.limit)

    client = YouTubeClient(os.getenv("YOUTUBE_API_KEY", ""))
    if args.command in ("discover", "run"):
        cmd_discover(client, cfg)
    if args.command in ("enrich", "run"):
        cmd_enrich(client, cfg)
    if args.command == "run":
        cmd_filter(cfg)


if __name__ == "__main__":
    main()
