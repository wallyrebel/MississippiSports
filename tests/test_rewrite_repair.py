"""Bounded repair of held drafts and the cross-run attempt limit (all offline)."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pendulum
import pytest

from rss_to_wp import cli
from rss_to_wp.config import FeedConfig
from rss_to_wp.rewriter.depth import article_depth_problem, article_depth_report
from rss_to_wp.rewriter.openai_client import OpenAIRewriter
from rss_to_wp.rewriter.repair import repair_feedback
from rss_to_wp.storage.dedupe import DedupeStore

CASES = json.loads((Path(__file__).parent / "fixtures/athletics_depth_cases.json").read_text(encoding="utf-8"))
SOURCE = CASES[3]["story"]


def supported_article():
    sentences = [s.strip(". ") for s in reversed(SOURCE.split(". "))]
    body = "".join("<p>" + ". ".join(sentences[i:i + 4]) + ".</p>" for i in range(0, len(sentences), 4))
    return {"headline": "Belhaven game report", "excerpt": "", "body": body, "tags": []}


def invented_article():
    article = supported_article()
    article["body"] += "<p>The team scored 999 points.</p>"
    return article


def completion(value, finish_reason="stop"):
    return SimpleNamespace(usage=None, choices=[SimpleNamespace(
        finish_reason=finish_reason, message=SimpleNamespace(content=json.dumps(value)))])


def rewriter(monkeypatch, **options):
    r = OpenAIRewriter("offline-test", model="gpt-6-luna", **options)
    r.client = Mock()
    monkeypatch.setattr(r, "_rate_limit", lambda: None)
    return r


def test_report_names_the_unsupported_number_and_matches_the_existing_check():
    problem, details = article_depth_report(invented_article(), SOURCE)
    assert problem == "unsupported_numeric_detail" == article_depth_problem(invented_article(), SOURCE)
    assert details == {"numbers": ["999"]}
    assert article_depth_report(supported_article(), SOURCE) == (None, {})


def test_report_spells_a_number_the_way_the_draft_wrote_it():
    article = {"headline": "Brief", "excerpt": "", "body": "<p>Fourteen players earned honors.</p>"}
    problem, details = article_depth_report(article, "Players earned honors.")
    assert problem == "unsupported_numeric_detail" and details["numbers"] == ["fourteen"]


@pytest.mark.parametrize("problem,details,expected", [
    ("unsupported_numeric_detail", {"numbers": ["999"]}, '"999"'),
    ("unsupported_time_or_play_interval", {"intervals": ["final 2 minute"]}, "final 2 minute"),
    ("substantive_source_undercovered", {"body_words": 40, "minimum_words": 180}, "180"),
    ("substantive_source_needs_paragraphs", {"paragraphs": 1, "minimum_paragraphs": 4}, "4"),
    ("thin_source_overexpanded", {"source_words": 50, "body_words": 200, "maximum_words": 80}, "80"),
    ("near_verbatim_source_passage", {"matching_words": 31, "passage_starts": "the Blazers led"}, "the Blazers led"),
    ("repeated_sentence_padding", {}, "repeats"),
    ("volleyball_set_score_not_in_source", {}, "set score"),
])
def test_repairable_holds_explain_the_specific_problem(problem, details, expected):
    feedback = repair_feedback(problem, details)
    assert expected in feedback
    assert "do not calculate" in feedback and "null for headline and body" in feedback


@pytest.mark.parametrize("problem", ["content_unavailable", "placeholder_content", "platform_failure",
                                     "invalid_article_field", "fact_check_rejected", None])
def test_missing_content_and_fact_check_holds_are_never_repaired(problem):
    assert repair_feedback(problem, {}) is None


def test_held_draft_is_repaired_once_with_the_offending_value_named(monkeypatch):
    r = rewriter(monkeypatch)
    r.client.chat.completions.create.side_effect = [completion(invented_article()),
                                                    completion(supported_article())]
    result = r.rewrite(SOURCE, "Belhaven game report")
    assert result and "999" not in result["body"]
    assert r.last_rejection is None
    calls = r.client.chat.completions.create.call_args_list
    assert len(calls) == 2
    messages = calls[1].kwargs["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1] == calls[0].kwargs["messages"][1]
    assert '"999"' in messages[3]["content"]


def test_repair_is_bounded_and_the_hold_is_recorded(monkeypatch):
    r = rewriter(monkeypatch)
    r.client.chat.completions.create.return_value = completion(invented_article())
    assert r.rewrite(SOURCE, "Belhaven game report") is None
    assert r.client.chat.completions.create.call_count == 2
    assert r.last_rejection["reason"] == "unsupported_numeric_detail"
    assert r.last_rejection["details"] == {"numbers": ["999"]}


def test_repairs_can_be_disabled(monkeypatch):
    r = rewriter(monkeypatch, max_repairs=0)
    r.client.chat.completions.create.return_value = completion(invented_article())
    assert r.rewrite(SOURCE, "Belhaven game report") is None
    assert r.client.chat.completions.create.call_count == 1


def test_repaired_draft_still_faces_the_independent_fact_check(monkeypatch):
    r = rewriter(monkeypatch, verify_facts=True)
    issue = {"claim": "led by five", "reason": "mismatch", "evidence": "35-32"}
    r.client.chat.completions.create.side_effect = [
        completion(invented_article()), completion(supported_article()),
        completion({"supported": False, "issues": [issue]})]
    assert r.rewrite(SOURCE, "Belhaven game report") is None
    # Draft, one repair, one fact check: a fact-check hold is never repaired.
    assert r.client.chat.completions.create.call_count == 3
    assert r.last_rejection["reason"] == "fact_check_rejected"
    assert r.last_rejection["details"] == {"issues": [issue]}


def test_api_failure_is_not_recorded_as_a_content_hold(monkeypatch):
    r = rewriter(monkeypatch)
    r.client.chat.completions.create.side_effect = RuntimeError("offline API failure")
    assert r.rewrite(SOURCE, "Belhaven game report") is None
    assert r.last_rejection is None


def test_store_counts_holds_separately_from_published_entries(tmp_path):
    store = DedupeStore(tmp_path / "processed.db")
    assert store.rejection_state("id:1") == (0, None)
    assert store.record_rejection("id:1", "feed", "Title", "https://example.com/1", "first") == 1
    assert store.record_rejection("id:1", "feed", "Title", "https://example.com/1", "second") == 2
    assert store.rejection_state("id:1") == (2, "second")
    assert not store.is_processed("id:1")
    assert store.get_processed_count() == 0


@pytest.fixture
def settings():
    return SimpleNamespace(timezone="UTC", article_max_rewrite_attempts=3)


def feed_entries(count):
    return [{"id": str(i), "title": f"Story {i}", "link": f"https://example.com/{i}",
             "published": pendulum.now("UTC").subtract(minutes=i).to_iso8601_string()}
            for i in range(count)]


def test_story_held_three_times_is_not_sent_to_the_model_again(monkeypatch, tmp_path, settings):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "parse_feed", lambda _: SimpleNamespace(entries=feed_entries(2)))
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)

    def held(**kwargs):
        kwargs["outcome"]["rejection"] = {"reason": "unsupported_numeric_detail",
                                          "details": {"numbers": ["999"]}, "headline": "Draft"}
        return None

    process = Mock(side_effect=held)
    monkeypatch.setattr(cli, "process_entry", process)
    store = DedupeStore(tmp_path / "processed.db")
    feed = FeedConfig(name="School", url="https://example.com/feed", max_per_run=1)
    for _ in range(3):
        assert cli.process_feed(feed, settings, store, Mock(), Mock(), False, 48, Mock()) == (0, 0, 1)
    # Story 0 used the one-per-run budget three times and is now held, so the
    # next run moves on to story 1 instead of starving it.
    assert [c.kwargs["entry"]["id"] for c in process.call_args_list] == ["0", "0", "0"]
    assert cli.process_feed(feed, settings, store, Mock(), Mock(), False, 48, Mock()) == (0, 1, 1)
    assert process.call_args_list[-1].kwargs["entry"]["id"] == "1"

    audit = [json.loads(line) for line in
             (tmp_path / "data" / "rewrite-audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [a["decision"] for a in audit[:3]] == ["rejected", "rejected", "held"]
    assert audit[2]["details"] == {"numbers": ["999"]} and audit[2]["attempts"] == 3


def test_dry_run_and_api_failures_do_not_count_toward_the_hold_limit(monkeypatch, tmp_path, settings):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "parse_feed", lambda _: SimpleNamespace(entries=feed_entries(1)))
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    store = DedupeStore(tmp_path / "processed.db")
    feed = FeedConfig(name="School", url="https://example.com/feed", max_per_run=1)

    monkeypatch.setattr(cli, "process_entry", Mock(return_value=None))  # API/network failure
    cli.process_feed(feed, settings, store, Mock(), Mock(), False, 48, Mock())
    assert store.rejection_state("id:0")[0] == 0

    def held(**kwargs):
        kwargs["outcome"]["rejection"] = {"reason": "thin_source_overexpanded", "details": {}}
        return None

    monkeypatch.setattr(cli, "process_entry", Mock(side_effect=held))
    cli.process_feed(feed, settings, store, Mock(), None, True, 48, Mock())
    assert store.rejection_state("id:0")[0] == 0
