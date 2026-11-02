"""Instagram Reels must never stop silently again (2026-11-02: a week of Reels went missing with
nothing on record, because a refused Reel was logged as a quiet skip and a sent one was never
checked)."""
from pathlib import Path

from anchor import catalog
from anchor.pipeline import reel_outcome, warn
from anchor.publish import BufferError


class FakeBuffer:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def post(self, post_id):
        self.calls += 1
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, Exception):
            raise a
        return a


def test_a_sent_reel_keeps_its_instagram_link():
    buf = FakeBuffer([{"status": "sending"}, {"status": "sent", "externalLink": "https://www.instagram.com/reel/abc/",
                                              "sentAt": "2026-11-02T10:00:00Z"}])
    out = reel_outcome(buf, "p1", sleep=lambda s: None)
    assert out == {"status": "sent", "external_link": "https://www.instagram.com/reel/abc/",
                   "sent_at": "2026-11-02T10:00:00Z"}
    assert buf.calls == 2


def test_a_refused_reel_keeps_instagrams_reason():
    buf = FakeBuffer([{"status": "error", "error": {"message": "Instagram account is not a business account"}}])
    out = reel_outcome(buf, "p1", sleep=lambda s: None)
    assert out["status"] == "error" and "business account" in out["error"]


def test_the_wait_is_bounded():
    buf = FakeBuffer([{"status": "sending"}])
    slept = []
    out = reel_outcome(buf, "p1", wait_s=60, every_s=20, sleep=slept.append)
    assert out["status"] == "sending" and sum(slept) == 60 and buf.calls == 4


def test_a_failed_status_check_never_fails_the_release():
    assert reel_outcome(FakeBuffer([BufferError("network error")]), "p1", sleep=lambda s: None) == {}


def test_a_skipped_reel_is_a_run_warning_and_on_record(capsys):
    warn("Instagram Reel NOT posted: x")
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "::warning::Instagram Reel NOT posted: x"
    src = (Path(__file__).resolve().parents[1] / "anchor" / "pipeline.py").read_text()
    skip = src[src.index("require notification scheduling"):][:700]
    assert "warn(" in skip and '"error": str(exc)' in skip
    assert {"instagram_url", "instagram_status", "instagram_error"} <= set(catalog.DROP_FIELDS)
