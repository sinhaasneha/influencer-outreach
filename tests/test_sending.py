import yaml

from src.sending import OutreachTracker, run_send

CFG = yaml.safe_load(open("config.yaml"))
CFG["sending"].update(delay_seconds=0, suppression_file="/nonexistent.txt")


def msg(name, email, status="GENERATED", ig="https://instagram.com/x"):
    return {"name": name, "email": email, "profile_url": f"https://yt/{name}", "message_status": status,
            "email_subject": "Hi", "email_body": "Body", "instagram_dm": "dm text", "instagram": ig}


class FakeSender:
    def __init__(self, fail_for=()):
        self.sent, self.fail_for = [], set(fail_for)

    def send(self, to, subject, body):
        if to in self.fail_for:
            raise RuntimeError("smtp down")
        self.sent.append((to, subject, body))


def tracker(*msgs):
    t = OutreachTracker(":memory:")
    t.register_all(list(msgs))
    return t


def test_statuses_for_missing_and_invalid_emails():
    t = tracker(msg("a", "Not Found"), msg("b", "bad@@x"), msg("c", "c@x.com", status="FAILED: x"))
    assert t.summary() == {"SKIPPED_NO_EMAIL": 1, "SKIPPED_INVALID_EMAIL": 1, "SKIPPED_NO_MESSAGE": 1}


def test_register_is_idempotent():
    t = tracker(msg("a", "a@x.com"))
    assert t.register(msg("a", "a@x.com")) is False


def test_duplicate_email_across_influencers_blocked():
    t = tracker(msg("a", "shared@agency.com"), msg("b", "Shared@Agency.com"))
    assert t.summary() == {"PENDING": 1, "SKIPPED_DUPLICATE_EMAIL": 1}


def test_dry_run_sends_nothing_and_records_simulated():
    t, s = tracker(msg("a", "a@x.com")), FakeSender()
    stats = run_send(t, s, CFG, live=False)
    assert stats["simulated"] == 1 and s.sent == [] and t.summary() == {"SIMULATED": 1}


def test_live_requires_approval():
    t, s = tracker(msg("a", "a@x.com")), FakeSender()
    assert run_send(t, s, CFG, live=True)["sent"] == 0
    t.approve()
    assert run_send(t, s, CFG, live=True)["sent"] == 1 and len(s.sent) == 1
    assert "reply 'no'" in s.sent[0][2]  # opt-out footer appended


def test_simulated_then_live_sends_once_and_never_twice():
    t, s = tracker(msg("a", "a@x.com")), FakeSender()
    run_send(t, s, CFG, live=False)
    t.approve()
    run_send(t, s, CFG, live=True)
    run_send(t, s, CFG, live=True)  # second live run must not resend
    assert len(s.sent) == 1 and t.summary() == {"SENT": 1}


def test_failure_is_logged_and_retried_next_run():
    t = tracker(msg("a", "a@x.com"), msg("b", "b@x.com"))
    t.approve()
    stats = run_send(t, FakeSender(fail_for={"a@x.com"}), CFG, live=True)
    assert stats == {"sent": 1, "simulated": 0, "failed": 1, "suppressed": 0}
    s2 = FakeSender()
    run_send(t, s2, CFG, live=True)
    assert [x[0] for x in s2.sent] == ["a@x.com"]


def test_suppression_list(tmp_path):
    f = tmp_path / "sup.txt"
    f.write_text("a@x.com\n")
    cfg = {**CFG, "sending": {**CFG["sending"], "suppression_file": str(f)}}
    t, s = tracker(msg("a", "a@x.com")), FakeSender()
    t.approve()
    assert run_send(t, s, cfg, live=True)["suppressed"] == 1 and s.sent == []


def test_max_per_run_cap():
    cfg = {**CFG, "sending": {**CFG["sending"], "max_per_run": 1}}
    t = tracker(msg("a", "a@x.com"), msg("b", "b@x.com"))
    assert run_send(t, FakeSender(), cfg, live=False)["simulated"] == 1


def test_exports_and_dm_queue(tmp_path):
    t = tracker(msg("a", "a@x.com"), msg("b", "Not Found"))
    assert t.export_tracker(str(tmp_path / "t.csv")) == 2
    assert t.export_dm_queue(str(tmp_path / "d.csv")) == 2  # DMs exist even without an email
    assert "Not Found" in (tmp_path / "t.csv").read_text(encoding="utf-8-sig")
