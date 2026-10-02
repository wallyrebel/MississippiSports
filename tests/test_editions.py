"""All evidence and WordPress operations are mocked: no live publication."""
import copy
import json
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import Mock

import pytest
import requests
from PIL import Image

from rss_to_wp.editions.publisher import (
    EditionError, Publisher, SITE, expected_date, featured_image, identity,
    read_source, render, run, safe_url, validate, verify_sources,
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


def draft(data, media=0):
    title, body = render(data)
    return {"id": 123, "slug": identity(data), "status": "draft",
            "content": {"raw": body}, "featured_media": media,
            "title": {"rendered": title}, "link": SITE + "/sports/" + identity(data) + "/"}


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
            if "content" in payload:
                state["post"]["content"]["raw"] = payload["content"]
            if "featured_media" in payload:
                state["post"]["featured_media"] = payload["featured_media"]
            if "status" in payload:
                state["post"]["status"] = payload["status"]
                state["published"] += 1
                if lost_publish:
                    raise requests.Timeout()
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
        return response(text=f"<h1>{title}</h1>{body}")
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


def test_complete_publish_and_repeat(intake):
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
def test_lost_response_reconciles_same_id(intake, lost):
    worker, state = wp_client(intake, **{lost: True})
    assert worker.publish(intake, b"mock PNG", "date")["id"] == 123
    assert state["creates"] == state["uploads"] == state["published"] == 1


def test_uncertain_creation_never_creates_twice(intake):
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


def test_resume_draft_and_attached_media(intake):
    worker, state = wp_client(intake, initial=draft(intake), existing_media=True)
    assert worker.publish(intake, b"mock PNG", "date")["id"] == 123
    assert state["creates"] == state["uploads"] == 0


def test_uncertain_media_leaves_draft(intake):
    worker, state = wp_client(intake, media_error=True)
    with pytest.raises(EditionError, match="Media upload uncertain"):
        worker.publish(intake, b"mock PNG", "date")
    assert state["post"]["status"] == "draft" and state["published"] == 0


def test_post_published_but_public_verify_fails(intake):
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
