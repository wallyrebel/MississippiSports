"""All evidence and WordPress operations are mocked: no live publication."""
import copy
import json
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import Mock
import runpy

import pytest
import requests
from PIL import Image

from rss_to_wp.editions.publisher import (
    EditionError, Publisher, SITE, expected_date, featured_image, identity,
    read_source, render, run, safe_url, validate, verify_sources, validate_article,
)

NOW = datetime(2026, 10, 2, 13, tzinfo=timezone.utc)


@pytest.fixture
def intake():
    # Synthetic fixture; these are not researched real games.
    return {
        "version": 1, "edition": "scores", "date": "2026-10-01",
        "verified_at": "2026-10-02T07:55:00-05:00", "publish": True,
        "checked_sports": ["football", "volleyball"], "related_links": [],
        "games": [{"sport": "football", "division": "boys", "state": "MS",
            "level": "high school varsity", "date": "2026-10-01",
            "home": "Synthetic Home", "away": "Synthetic Away", "status": "final",
            "home_score": 28, "away_score": 14,
            "evidence": {"url": "https://tippahsports.com/synthetic-fixture/",
                "excerpt": "October 1, 2026 Final Synthetic Home 28 Synthetic Away 14",
                "date_excerpt": "October 1, 2026"}}],
    }


def response(data=None, text="", code=200):
    value = Mock(status_code=code, text=text, content=text.encode(), headers={})
    value.json.return_value = data
    return value


def add_article(data):
    """Original fixture prose, not a researched or publishable real article."""
    game = data["games"][0]
    matchup = f"{game['away']} at {game['home']}"
    data["article"] = {
        "reviewed": True,
        "headline": "Synthetic Home and Synthetic Away lead the Mississippi selection",
        "headline_fact_ids": ["game-0"],
        "html": (f'<p data-facts="game-0">{matchup} leads this selection of verified Mississippi games.</p>'
                 '<h2 data-facts="game-0 record-home">The record behind the matchup</h2>'
                 '<p data-facts="record-home">Synthetic Home entered the game with a 5-0 record.</p>'
                 '<p data-facts="game-0">The verified matchup gives this article its focus; '
                 'the reporting is tied to the specific game rather than a statewide completeness claim.</p>'),
        "facts": [{"id": "record-home", "kind": "record", "claim": "Synthetic Home entered at 5-0",
                   "game_indexes": [0], "as_of_date": data["date"],
                   "evidence": {"url": "https://tippahsports.com/synthetic-record/",
                                "excerpt": "Synthetic Home entered the game 5-0 this season.",
                                "subjects": ["Synthetic Home"]}}],
    }
    return data


@pytest.fixture
def editorial(intake):
    return add_article(intake)


def draft(data, media=0):
    title, body = render(data)
    return {"id": 123, "slug": identity(data), "status": "draft",
            "content": {"raw": body}, "featured_media": media,
            "title": {"raw": title, "rendered": title}, "modified_gmt": "2026-10-02T12:00:00",
            "link": SITE + "/sports/" + identity(data) + "/"}


def wp_client(intake, *, initial=None, lost_create=False, lost_publish=False,
              lookup_error=False, media_error=False, existing_media=False, public_error=False):
    state = {"post": copy.deepcopy(initial), "creates": 0, "uploads": 0, "writes": [], "published": 0}
    title, body = render(intake)
    def api(method, url, **kwargs):
        endpoint = url.split("/wp/v2/")[1]
        if method == "GET" and endpoint == "posts":
            if lookup_error:
                return response(code=503)
            return response([copy.deepcopy(state["post"])] if state["post"] else [])
        if method == "GET" and endpoint == "categories":
            return response([{"id": 8}])
        if method == "GET" and endpoint == "media":
            return response([{"id": 456, "slug": identity(intake)}] if existing_media else [])
        if method == "GET" and endpoint == "posts/123":
            return response(copy.deepcopy(state["post"]))
        if method == "POST":
            state["writes"].append(endpoint)
        if method == "POST" and endpoint == "posts":
            state["creates"] += 1
            state["post"] = draft(intake)
            if lost_create:
                raise requests.Timeout("unprinted transport detail")
            return response(copy.deepcopy(state["post"]))
        if method == "POST" and endpoint == "media":
            state["uploads"] += 1
            if media_error:
                raise requests.Timeout()
            return response({"id": 456})
        if method == "POST" and endpoint == "media/456":
            return response({"id": 456})
        if method == "POST" and endpoint == "posts/123":
            payload = kwargs["json"]
            if "title" in payload:
                state["post"]["title"] = {"raw": payload["title"], "rendered": payload["title"]}
            if "content" in payload:
                state["post"]["content"]["raw"] = payload["content"]
            if "featured_media" in payload:
                state["post"]["featured_media"] = payload["featured_media"]
            if "status" in payload:
                state["post"]["status"] = payload["status"]
                state["published"] += 1
                if lost_publish:
                    raise requests.Timeout()
            state["post"]["modified_gmt"] = "2026-10-02T12:01:00"
            return response(copy.deepcopy(state["post"]))
        raise AssertionError((method, endpoint))
    auth = Mock()
    auth.request.side_effect = api
    def public_get(url, **kwargs):
        if public_error:
            return response(code=503)
        if url.endswith("/posts/123"):
            post = copy.deepcopy(state["post"])
            post["content"] = {"rendered": post["content"]["raw"]}
            return response(post)
        if url.endswith("/media/456"):
            return response({"source_url": SITE + "/wp-content/uploads/card.png"})
        current_title = state["post"]["title"]["rendered"] if state["post"] else title
        current_body = state["post"]["content"]["raw"] if state["post"] else body
        return response(text=f"<h1>{current_title}</h1>{current_body}")
    public = Mock()
    public.get.side_effect = public_get
    return Publisher(auth, public, sleeper=lambda seconds: None), state


def test_schema_and_render(intake):
    assert validate(intake, NOW) is intake
    title, body = render(intake)
    assert "October 1, 2026" in title
    assert "Synthetic Away 14, Synthetic Home 28 — Final" in body
    assert "Football — Boys" in body and "not a complete statewide" in body
    assert intake["games"][0]["evidence"]["url"] in body
    assert "sportsms-scores-2026-10-01" in body


@pytest.mark.parametrize("edit", [
    lambda x: x.update(date="2026-09-30"),
    lambda x: x.update(verified_at="2026-09-30T00:00:00Z"),
    lambda x: x.update(verified_at="2026-10-02T14:00:00Z"),
    lambda x: x.update(verified_at="2026-10-02T07:55:00"),
    lambda x: x["games"][0].update(status="pending"),
    lambda x: x["games"][0].update(home_score=None),
    lambda x: x["games"][0].update(home_score=True),
    lambda x: x["games"][0].update(level="college"),
    lambda x: x["games"][0].update(date="2026-10-02"),
    lambda x: x["games"][0]["evidence"].update(date_excerpt="October 2, 2026"),
    lambda x: x["games"][0]["evidence"].update(url="https://tippahsports.com.evil.invalid/test"),
    lambda x: x["games"].append(copy.deepcopy(x["games"][0])),
])
def test_reject_invalid(intake, edit):
    edit(intake)
    with pytest.raises(EditionError):
        validate(intake, NOW)


def test_reverse_duplicate(intake):
    second = copy.deepcopy(intake["games"][0])
    second["home"], second["away"] = second["away"], second["home"]
    intake["games"].append(second)
    with pytest.raises(EditionError, match="Duplicate"):
        validate(intake, NOW)


@pytest.mark.parametrize("stamp,expected", [
    ("2026-03-08T13:00:00+00:00", "2026-03-07"),
    ("2026-11-01T14:00:00+00:00", "2026-10-31"),
    ("2026-10-02T02:00:00+00:00", "2026-09-30"),
    ("2026-01-01T14:00:00+00:00", "2025-12-31"),
])
def test_central_calendar_dst_and_rollover(stamp, expected):
    now = datetime.fromisoformat(stamp)
    assert expected_date("scores", now).isoformat() == expected
    assert (expected_date("preview", now) - expected_date("scores", now)).days == 1


def preview_data(intake):
    intake.update(edition="preview", date="2026-10-02")
    game = intake["games"][0]
    game.update(date="2026-10-02", status="scheduled", start_time="2026-10-02T19:00:00-05:00")
    del game["home_score"], game["away_score"]
    game["evidence"].update(excerpt="October 2, 2026 Synthetic Home vs Synthetic Away 7 p.m.",
                            date_excerpt="October 2, 2026", time_excerpt="7 p.m.")
    return intake


def test_preview_time_and_no_stats(intake):
    preview_data(intake)
    validate(intake, NOW)
    _, body = render(intake)
    assert "7:00 PM CDT" in body and "Final" not in body
    intake["games"][0]["start_time"] = "2026-10-02T07:00:00-05:00"
    with pytest.raises(EditionError, match="Stale game"):
        validate(intake, NOW)


def test_meet_results_and_preview(intake):
    intake["checked_sports"].append("cross country")
    game = {"format": "meet", "name": "Synthetic Invitational", "schools": ["Synthetic Home"],
            "sport": "cross country", "division": "girls", "state": "MS",
            "level": "high school varsity", "date": "2026-10-01", "status": "final",
            "results": [{"school": "Synthetic Home", "place": 1}],
            "evidence": {"url": "https://misshsaa.com/synthetic-fixture/", "date_excerpt": "October 1, 2026",
                         "excerpt": "October 1, 2026 Synthetic Invitational Final Synthetic Home team place 1"}}
    intake["games"] = [game]
    validate(intake, NOW)
    assert "Synthetic Home: team place 1" in render(intake)[1]
    intake.update(edition="preview", date="2026-10-02")
    game.update(status="scheduled", date="2026-10-02")
    del game["results"]
    game["evidence"].update(date_excerpt="October 2, 2026",
                            excerpt="October 2, 2026 Synthetic Invitational Synthetic Home")
    validate(intake, NOW)
    assert "start time not verified" in render(intake)[1]


def test_source_excerpt_rechecked(intake):
    public = Mock()
    public.get.return_value = response(text="<p>" + intake["games"][0]["evidence"]["excerpt"] + "</p>")
    verify_sources(intake, public)
    public.get.return_value = response(text="<p>Old or login-blocked report</p>")
    with pytest.raises(EditionError, match="Evidence no longer"):
        verify_sources(intake, public)


def test_source_redirect_does_not_leak_to_unapproved_host():
    public = Mock()
    public.get.return_value = response(code=302)
    public.get.return_value.headers = {"Location": "https://evil.invalid/"}
    with pytest.raises(EditionError, match="Unapproved"):
        read_source("https://maxpreps.com/test", public)
    assert public.get.call_count == 1


def test_empty_and_offline_never_publish(intake, tmp_path, monkeypatch):
    monkeypatch.setattr("rss_to_wp.editions.publisher.public_session", lambda: Mock())
    result = run(intake, tmp_path, dry_run=True, offline=True, now=NOW)
    assert result["state"] == "dry_run" and result["sources_checked"] is False
    assert (tmp_path / "featured.png").exists()
    with pytest.raises(EditionError, match="only with dry-run"):
        run(intake, tmp_path, offline=True, now=NOW)
    intake["games"] = []
    assert run(intake, tmp_path, now=NOW)["state"] == "skipped_no_verified_games"


@pytest.mark.parametrize("edition", ["scores", "preview"])
def test_original_card(intake, edition):
    if edition == "preview":
        preview_data(intake)
    png, alt = featured_image(intake)
    assert Image.open(BytesIO(png)).size == (1600, 900)
    assert ("Scores from last Night" if edition == "scores" else "Games To Watch") in alt
    assert "October" in alt


def test_complete_publish_and_repeat(editorial):
    intake = editorial
    worker, state = wp_client(intake)
    result = worker.publish(intake, b"mock PNG", "date")
    assert result["state"] == "published" and result["featured_media"] == 456
    assert state["creates"] == state["uploads"] == state["published"] == 1
    assert worker.publish(intake, b"mock PNG", "date")["id"] == 123
    assert state["creates"] == state["uploads"] == state["published"] == 1


def test_lookup_failure_zero_writes(intake):
    worker, state = wp_client(intake, lookup_error=True)
    with pytest.raises(EditionError):
        worker.publish(intake, b"mock PNG", "date")
    assert state["writes"] == []


@pytest.mark.parametrize("lost", ["lost_create", "lost_publish"])
def test_lost_response_reconciles_same_id(editorial, lost):
    intake = editorial
    worker, state = wp_client(intake, **{lost: True})
    assert worker.publish(intake, b"mock PNG", "date")["id"] == 123
    assert state["creates"] == state["uploads"] == state["published"] == 1


def test_uncertain_creation_never_creates_twice(editorial):
    intake = editorial
    worker, state = wp_client(intake)
    original = worker.session.request.side_effect
    def fail(method, url, **kwargs):
        if method == "POST" and url.endswith("/posts"):
            state["creates"] += 1
            raise requests.Timeout()
        return original(method, url, **kwargs)
    worker.session.request.side_effect = fail
    with pytest.raises(EditionError, match="Uncertain write"):
        worker.publish(intake, b"mock PNG", "date")
    assert state["creates"] == 1 and state["uploads"] == 0


def test_resume_draft_and_attached_media(editorial):
    intake = editorial
    worker, state = wp_client(intake, initial=draft(intake), existing_media=True)
    assert worker.publish(intake, b"mock PNG", "date")["id"] == 123
    assert state["creates"] == state["uploads"] == 0


def test_uncertain_media_leaves_draft(editorial):
    intake = editorial
    worker, state = wp_client(intake, media_error=True)
    with pytest.raises(EditionError, match="Media upload uncertain"):
        worker.publish(intake, b"mock PNG", "date")
    assert state["post"]["status"] == "draft" and state["published"] == 0


def test_post_published_but_public_verify_fails(editorial):
    intake = editorial
    worker, state = wp_client(intake, public_error=True)
    with pytest.raises(EditionError, match="may already be published"):
        worker.publish(intake, b"mock PNG", "date")
    assert state["post"]["status"] == "publish" and state["creates"] == 1


def test_foreign_slug_never_overwritten(intake):
    foreign = draft(intake)
    foreign["content"]["raw"] = "Another article"
    worker, state = wp_client(intake, initial=foreign)
    with pytest.raises(EditionError, match="different post"):
        worker.publish(intake, b"mock PNG", "date")
    assert state["writes"] == []


def test_multiple_matches_fail_closed(intake):
    worker, state = wp_client(intake)
    worker.session.request.side_effect = None
    second = draft(intake)
    second["id"] = 124
    worker.session.request.return_value = response([draft(intake), second])
    with pytest.raises(EditionError, match="Multiple edition"):
        worker.publish(intake, b"mock PNG", "date")
    assert state["writes"] == []


def test_wrong_destination_is_rejected_without_credentials(intake, tmp_path, monkeypatch):
    public = Mock()
    public.get.return_value = response(text=intake["games"][0]["evidence"]["excerpt"])
    monkeypatch.setattr("rss_to_wp.editions.publisher.public_session", lambda: public)
    monkeypatch.setenv("WORDPRESS_BASE_URL", "https://other.invalid")
    with pytest.raises(EditionError, match="destination"):
        run(intake, tmp_path, now=NOW)


def test_new_intake_does_not_retry_prior_uncertain_edition(tmp_path, monkeypatch):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"before": "a" * 40, "after": "b" * 40}))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    diff = Mock(stdout="editions/inbox/preview-2026-10-02.json\n")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: diff)
    paths = runpy.run_path("scripts/process_editions.py")["submitted_paths"]()
    assert paths == {"editions/inbox/preview-2026-10-02.json"}
    assert "editions/inbox/scores-2026-10-01.json" not in paths


@pytest.mark.parametrize("edition", ["scores", "preview"])
def test_reviewed_article_preserves_prose_and_traces_sources(intake, edition):
    if edition == "preview":
        preview_data(intake)
    add_article(intake)
    validate(intake, NOW)
    title, body = render(intake)
    assert title == intake["article"]["headline"]
    assert "entered the game with a 5-0 record" in body
    assert "data-facts" not in body and "Source: " not in body
    assert "Reporting sources:" in body
    assert intake["article"]["facts"][0]["evidence"]["url"] in body
    assert intake["games"][0]["evidence"]["url"] in body
    assert "Coverage:" in body and f"<!-- {identity(intake)} -->" in body


@pytest.mark.parametrize("change,message", [
    (lambda x: x["article"].update(reviewed=False), "review"),
    (lambda x: x["article"].update(headline_fact_ids=["unknown"]), "unknown"),
    (lambda x: x["article"]["facts"][0].update(as_of_date="2026-09-01"), "stale"),
    (lambda x: x["article"]["facts"][0].update(claim="Synthetic Home entered 9-0"), "numeric claim"),
    (lambda x: x["article"]["facts"][0]["evidence"].update(subjects=["Other School"]), "subject"),
    (lambda x: x["article"]["facts"][0].update(game_indexes=[99]), "covered game"),
    (lambda x: x["article"]["facts"].append(copy.deepcopy(x["article"]["facts"][0])), "duplicate fact"),
    (lambda x: x["article"].update(html=x["article"]["html"].replace("5-0", "8-0")), "unsupported numeric"),
    (lambda x: x["article"].update(html=x["article"]["html"].replace('data-facts="record-home"', '')), "Missing"),
    (lambda x: x["article"].update(html=x["article"]["html"] + "<script>alert(1)</script>"), "referenced paragraphs"),
    (lambda x: x["article"].update(html=x["article"]["html"].replace("<p ", '<p onclick="x" ', 1)), "attribute"),
    (lambda x: x["article"].update(html=x["article"]["html"] + '<p data-facts="game-0"><a href="javascript:x">Click</a></p>'), "link"),
    (lambda x: x["article"].update(html=x["article"]["html"] + '<p data-facts="game-0"><a href="https://maxpreps.com/unresearched">Read</a></p>'), "link"),
    (lambda x: x["article"].update(html=x["article"]["html"] + '<strong>Unreferenced outside prose</strong>'), "referenced paragraphs"),
    (lambda x: x["article"].update(html=x["article"]["html"] + '<!-- hidden claim -->'), "referenced paragraphs"),
    (lambda x: x["article"].update(html='<p data-facts="game-0">' + 'short lede ' * 20 + '</p>'), "developed body"),
])
def test_editorial_gates(editorial, change, message):
    change(editorial)
    with pytest.raises(EditionError, match=message):
        validate(editorial, NOW)


def test_editorial_ledger_evidence_is_refetched(editorial):
    game_evidence = editorial["games"][0]["evidence"]
    extra = editorial["article"]["facts"][0]["evidence"]
    public = Mock()
    public.get.side_effect = lambda url, **kwargs: response(text=(
        game_evidence["excerpt"] if url == game_evidence["url"] else extra["excerpt"]))
    verify_sources(editorial, public)
    assert public.get.call_count == 2
    public.get.side_effect = lambda url, **kwargs: response(text=(
        game_evidence["excerpt"] if url == game_evidence["url"] else "Record no longer available"))
    with pytest.raises(EditionError, match="Evidence no longer"):
        verify_sources(editorial, public)


def add_calculated_fact(editorial):
    fact = editorial["article"]["facts"][0]
    fact.update(claim="Synthetic Home scored 87 points in its two wins.",
                calculation={"operation": "sum", "terms": [
                    {"value": 38, "excerpt": "First opponent W 38-6"},
                    {"value": 49, "excerpt": "Second opponent W 49-13"}], "result": 87})
    fact["evidence"]["excerpt"] = "Synthetic Home First opponent W 38-6 Second opponent W 49-13"
    editorial["article"]["html"] = editorial["article"]["html"].replace(
        "Synthetic Home entered the game with a 5-0 record.", fact["claim"])
    return fact


def test_reviewed_sourced_sum_preserves_derived_context(editorial):
    add_calculated_fact(editorial)
    validate(editorial, NOW)
    assert "scored 87 points" in render(editorial)[1]


@pytest.mark.parametrize("change,message", [
    (lambda f: f["calculation"].update(result=88), "Incorrect"),
    (lambda f: f["calculation"].update(operation="eval"), "Unsupported"),
    (lambda f: f["calculation"]["terms"][0].update(value=True), "Invalid calculation term"),
    (lambda f: f["calculation"]["terms"][0].update(value=99999), "Invalid calculation term"),
    (lambda f: f["calculation"]["terms"][0].update(value=39), "term value absent"),
    (lambda f: f["calculation"]["terms"][0].update(excerpt="Synthetic Home invented 38"), "term excerpt absent"),
    (lambda f: f["calculation"].update(terms=[]), "bounded source terms"),
    (lambda f: f["calculation"].update(terms=[f["calculation"]["terms"][0]] * 2, result=76), "Repeated"),
    (lambda f: f.update(claim="Synthetic Home scored 88 points"), "result absent"),
    (lambda f: f.update(claim="Synthetic Home scored 87 points and had 999 rebounds"), "numeric claim absent"),
])
def test_calculation_rejects_wrong_math_and_unsourced_terms(editorial, change, message):
    fact = add_calculated_fact(editorial)
    change(fact)
    with pytest.raises(EditionError, match=message):
        validate(editorial, NOW)


def test_historical_context_uses_real_old_date_without_stale_game_date(editorial):
    fact = editorial["article"]["facts"][0]
    fact.update(kind="history", fact_date="2025-10-01", claim="Synthetic Home won the 2025 meeting 21-14")
    fact["evidence"].update(excerpt="October 1, 2025 Synthetic Home won 21-14",
                             date_excerpt="October 1, 2025")
    editorial["article"]["html"] = editorial["article"]["html"].replace(
        "Synthetic Home entered the game with a 5-0 record.", "Synthetic Home won the 2025 meeting 21-14.")
    validate(editorial, NOW)
    fact["fact_date"] = "2027-10-01"
    with pytest.raises(EditionError, match="Future historical"):
        validate(editorial, NOW)


def test_new_publication_requires_article_but_legacy_rerun_does_not(intake):
    worker, state = wp_client(intake)
    with pytest.raises(EditionError, match="developed editorial"):
        worker.publish(intake, b"PNG", "date")
    assert state["writes"] == []
    existing = draft(intake, media=456)
    existing["status"] = "publish"
    worker, state = wp_client(intake, initial=existing)
    assert worker.publish(intake, b"PNG", "date")["id"] == 123
    assert state["writes"] == []


def authorized_revision(editorial, post_id=123):
    editorial["revision"] = {"authorized": True, "post_id": post_id,
        "expected_featured_media": 456,
        "id": "editorial-upgrade-v1", "reason": "User requested a researched article format",
        "expected_modified_gmt": "2026-10-02T12:00:00"}
    return editorial


def original_published_post(editorial):
    original = copy.deepcopy(editorial)
    original.pop("article", None)
    original.pop("revision", None)
    post = draft(original, media=456)
    post["status"] = "publish"
    return post


def test_explicit_revision_same_post_media_with_backup_and_idempotency(editorial, tmp_path):
    authorized_revision(editorial)
    original = original_published_post(editorial)
    worker, state = wp_client(editorial, initial=original)
    worker.recovery = tmp_path
    result = worker.publish(editorial, b"never upload", "same date")
    assert result["state"] == "published" and result["operation"] == "revised"
    assert result["id"] == 123 and result["featured_media"] == 456
    assert state["writes"] == ["posts/123"]
    assert state["creates"] == state["uploads"] == state["published"] == 0
    assert json.loads((tmp_path / "previous-post.json").read_text())["content"] == original["content"]
    revision_request = next(call for call in worker.session.request.call_args_list
                            if call.args[0] == "POST")
    assert set(revision_request.kwargs["json"]) == {"title", "content"}
    assert worker.publish(editorial, b"never upload", "same date")["operation"] == "revision_already_applied"
    assert state["writes"] == ["posts/123"]


@pytest.mark.parametrize("change,message", [
    (lambda x: x["revision"].update(authorized=False), "authorization"),
    (lambda x: x["revision"].pop("expected_modified_gmt"), "snapshot"),
    (lambda x: x["revision"].update(post_id=True), "exact target"),
    (lambda x: x["revision"].update(expected_featured_media=0), "featured media ID"),
    (lambda x: x["revision"].update(id="bad id"), "revision ID"),
])
def test_revision_schema_gates(editorial, change, message):
    authorized_revision(editorial)
    change(editorial)
    with pytest.raises(EditionError, match=message):
        validate(editorial, NOW)


@pytest.mark.parametrize("scenario,message", [
    ("wrong_id", "target does not match"),
    ("newer_edit", "snapshot changed"),
    ("missing", "target not found"),
    ("draft", "published edition"),
    ("no_media", "existing featured"),
    ("changed_media", "image differs"),
])
def test_revision_refuses_wrong_target_or_changed_snapshot(editorial, scenario, message):
    authorized_revision(editorial)
    original = original_published_post(editorial)
    if scenario == "wrong_id":
        editorial["revision"]["post_id"] = 23916
    if scenario == "newer_edit":
        original["modified_gmt"] = "2026-10-02T12:00:01"
    if scenario == "draft":
        original["status"] = "draft"
    if scenario == "no_media":
        original["featured_media"] = 0
    if scenario == "changed_media":
        original["featured_media"] = 789
    worker, state = wp_client(editorial, initial=None if scenario == "missing" else original)
    with pytest.raises(EditionError, match=message):
        worker.publish(editorial, b"never upload", "date")
    assert state["writes"] == []


def test_lost_revision_response_reconciles_without_another_update(editorial):
    authorized_revision(editorial)
    worker, state = wp_client(editorial, initial=original_published_post(editorial))
    api = worker.session.request.side_effect
    def lost(method, url, **kwargs):
        reply = api(method, url, **kwargs)
        if method == "POST" and url.endswith("/posts/123"):
            raise requests.Timeout()
        return reply
    worker.session.request.side_effect = lost
    assert worker.publish(editorial, b"never upload", "date")["operation"] == "revised"
    assert state["writes"] == ["posts/123"]


def test_uncertain_revision_never_blindly_updates_or_creates_again(editorial):
    authorized_revision(editorial)
    worker, state = wp_client(editorial, initial=original_published_post(editorial))
    api = worker.session.request.side_effect
    def lost(method, url, **kwargs):
        if method == "POST" and url.endswith("/posts/123"):
            state["writes"].append("posts/123")
            raise requests.Timeout()
        return api(method, url, **kwargs)
    worker.session.request.side_effect = lost
    with pytest.raises(EditionError, match="Revision outcome uncertain"):
        worker.publish(editorial, b"never upload", "date")
    assert state["writes"] == ["posts/123"] and state["creates"] == state["uploads"] == 0


def test_changed_body_with_reused_revision_id_is_refused(editorial):
    authorized_revision(editorial)
    worker, state = wp_client(editorial, initial=original_published_post(editorial))
    worker.publish(editorial, b"PNG", "date")
    editorial["article"]["headline"] = "A changed headline using the same revision ID"
    with pytest.raises(EditionError, match="already exists with different content"):
        worker.publish(editorial, b"PNG", "date")
    assert state["writes"] == ["posts/123"]


def test_plain_scheduled_rerun_keeps_published_article_unchanged(editorial):
    published = original_published_post(editorial)
    worker, state = wp_client(editorial, initial=published)
    worker.publish(editorial, b"PNG", "date")
    assert state["writes"] == [] and state["post"]["content"] == published["content"]


def test_editorial_local_time_and_date_formatting(intake):
    preview_data(intake)
    add_article(intake)
    intake["article"]["html"] += '<p data-facts="game-0">The October 2 game is scheduled for 7:00 p.m. Central.</p>'
    validate(intake, NOW)
    assert "7:00 p.m." in render(intake)[1]


def test_verified_thousands_formatting_and_new_local_sources(editorial):
    fact = editorial["article"]["facts"][0]
    fact.update(claim="Synthetic Home recorded 1,245 yards")
    fact["evidence"].update(url="https://www.wdam.com/synthetic-test/",
                             excerpt="Synthetic Home recorded 1245 yards.")
    editorial["article"]["html"] = editorial["article"]["html"].replace(
        "Synthetic Home entered the game with a 5-0 record.", "Synthetic Home recorded 1,245 yards.")
    validate(editorial, NOW)
    assert safe_url("https://mississippiscoreboard.com/synthetic-test/")
