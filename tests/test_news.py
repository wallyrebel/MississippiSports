"""Meaningful offline safety/recovery scenarios; no real WordPress operations."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from rss_to_wp.news.publisher import (
    ALT, BODY, BODY_SHA, EVENT, EXCERPT, HEADLINE, MARKER, MEDIA_SLUG, PHOTO_PATH,
    PHOTO_SHA, POLICE, Publisher, NewsError, SLUG, WTVA, pixels, run, validate,
)


@pytest.fixture
def data():
    result = json.loads(Path("news/inbox/alden-wade-2026-10-11.json").read_text())
    result.update(publish=False, parent_reviewed=False,
                  verified_at=datetime.now(timezone.utc).isoformat(), recovery_post_id=None)
    result.pop("preflight", None)
    result.pop("image_repair", None)
    return result


def response(value, *, total=0, pages=0, code=200):
    r = Mock(status_code=code, headers={"X-WP-Total": str(total), "X-WP-TotalPages": str(pages)})
    r.json.return_value = value
    return r


def schema(statuses):
    return {"endpoints": [{"methods": ["GET"], "args": {"status": {"items": {"enum": statuses + ["any"]}}}}]}


def post(status="draft", media=0):
    return {"id": 77, "slug": SLUG, "status": status, "modified_gmt": "2026-10-12T12:00:00",
            "title": {"raw": HEADLINE}, "content": {"raw": BODY + "\n" + MARKER},
            "featured_media": media, "link": "https://sportsmississippi.com/prep-sports/" + SLUG + "/"}


def publisher(tmp_path):
    photo = Path(PHOTO_PATH).read_bytes()
    return Publisher(Mock(), Mock(), tmp_path, photo)


def test_scope_copy_and_provenance_locked(data):
    validate(data)
    for field, value in [("event_id", "another-event"), ("headline", "Different headline"),
                         ("html", BODY + "<p>Unverified claim.</p>"),
                         ("image_sha256", "0" * 64), ("quote_provenance", "verified_social_post")]:
        bad = copy.deepcopy(data)
        bad[field] = value
        with pytest.raises(NewsError):
            validate(bad)


def test_parent_review_and_matching_managed_preflight_required(data):
    data["publish"] = True
    with pytest.raises(NewsError, match="Parent"):
        validate(data)
    data["parent_reviewed"] = True
    with pytest.raises(NewsError, match="preflight"):
        validate(data)
    data["preflight"] = {"run_id": 1, "commit": "a" * 40,
                         "article_sha256": BODY_SHA, "image_sha256": PHOTO_SHA}
    validate(data)


def test_offline_never_authenticates_or_writes(data, tmp_path):
    auth = Mock()
    result = run(data, tmp_path, offline=True, auth=auth)
    assert result["state"] == "offline_validated"
    assert not auth.request.called
    data.update(publish=True, parent_reviewed=True,
                preflight={"run_id": 1, "commit": "a" * 40, "article_sha256": BODY_SHA, "image_sha256": PHOTO_SHA})
    with pytest.raises(NewsError, match="Offline"):
        run(data, tmp_path, offline=True, auth=auth)
    assert not auth.request.called


def test_all_status_array_and_exhaustive_pagination(tmp_path):
    p = publisher(tmp_path)
    p.auth.request.side_effect = [response([{"id": 1}], total=2, pages=2),
                                  response([{"id": 2}], total=2, pages=2)]
    result = p.collect("posts", {"search": "Alden Wade"}, ["publish", "draft", "trash"])
    assert [item["id"] for item in result] == [1, 2]
    for call in p.auth.request.call_args_list:
        params = call.kwargs["params"]
        assert [("status[]", s) for s in ["publish", "draft", "trash"]] == params[:3]
        assert ("context", "edit") in params


def test_incomplete_or_changing_pagination_fails_closed(tmp_path):
    p = publisher(tmp_path)
    p.auth.request.return_value = response([{"id": 1}], total=2, pages=1)
    with pytest.raises(NewsError, match="Incomplete"):
        p.collect("posts", {}, ["publish"])
    p.auth.request.side_effect = [response([{"id": 1}], total=2, pages=2),
                                  response([], total=0, pages=0)]
    with pytest.raises(NewsError, match="changed"):
        p.collect("posts", {}, ["publish"])


def test_lookup_permission_error_never_writes(data, tmp_path):
    p = publisher(tmp_path)
    p.auth.request.return_value = response({}, code=403)
    with pytest.raises(NewsError):
        p.reconcile()
    assert p.actions == []
    assert all(call.args[0] != "POST" for call in p.auth.request.call_args_list)


def test_missing_status_schema_fails_closed(tmp_path):
    p = publisher(tmp_path)
    p.auth.request.return_value = response(schema(["publish"]))
    with pytest.raises(NewsError, match="statuses"):
        p.discover_statuses("posts")


def test_renamed_private_source_event_is_found(tmp_path):
    p = publisher(tmp_path)
    existing = post("private")
    existing["slug"] = "renamed-private-post"
    existing["content"]["raw"] = "<p>Alden Wade died in a crash.</p>"
    p.discover_statuses = Mock(return_value=["publish", "private", "trash"])
    p.collect = Mock(side_effect=lambda endpoint, query, statuses: [existing] if endpoint == "posts" and query.get("search") == "Alden Wade" else [])
    result = p.reconcile()
    assert result["matching_post_ids"] == [77]
    assert result["all_statuses_checked"] is True
    assert not p.auth.request.called


def test_multiple_event_matches_stop(tmp_path):
    p = publisher(tmp_path)
    p.discover_statuses = Mock(return_value=["publish", "private", "trash"])
    other = post("trash")
    other["id"] = 78
    p.collect = Mock(return_value=[post(), other])
    with pytest.raises(NewsError, match="Multiple event"):
        p.reconcile()
    assert p.actions == []


def test_matching_portrait_reused_by_original_bytes(tmp_path):
    p = publisher(tmp_path)
    media = {"id": 88, "status": "inherit", "slug": "old-original-name"}
    p.discover_statuses = Mock(return_value=["publish", "private", "trash"])
    p.collect = Mock(side_effect=lambda endpoint, query, statuses: [media] if endpoint == "media" and query.get("search") == "Alden Wade" else [])
    p.original_image = Mock(return_value=p.photo)
    result = p.reconcile()
    assert result["matching_media_ids"] == [88]
    assert p.actions == []


def test_duplicate_portraits_or_changed_deterministic_media_stop(tmp_path):
    p = publisher(tmp_path)
    p.discover_statuses = Mock(return_value=["inherit", "private", "trash"])
    media = [{"id": 88, "status": "inherit", "slug": MEDIA_SLUG}, {"id": 89, "status": "inherit", "slug": "other"}]
    p.collect = Mock(side_effect=lambda endpoint, query, statuses: media if endpoint == "media" else [])
    p.original_image = Mock(return_value=p.photo)
    with pytest.raises(NewsError, match="Multiple matching"):
        p.reconcile()
    p.collect = Mock(side_effect=lambda endpoint, query, statuses: media[:1] if endpoint == "media" else [])
    p.original_image = Mock(return_value=b"changed")
    with pytest.raises(NewsError, match="different original bytes"):
        p.reconcile()


def test_lost_create_response_does_not_repeat_post(data, tmp_path):
    p = publisher(tmp_path)
    p.category = Mock(return_value=4)
    p.auth.request.side_effect = requests.Timeout("secret transport details must not appear")
    p.reconcile = Mock(return_value={"post": post()})
    with pytest.raises(NewsError, match="reconcile") as caught:
        p.publish(data, {"post": None, "media": None})
    assert "secret" not in str(caught.value)
    assert p.auth.request.call_count == 1
    assert p.actions[0]["state"] == "uncertain_or_failed"
    p.reconcile.assert_called_once()


def test_existing_draft_requires_same_post_recovery(data, tmp_path):
    p = publisher(tmp_path)
    with pytest.raises(NewsError, match="recovery ID"):
        p.publish(data, {"post": post(), "media": None})
    assert p.actions == []
    data["recovery_post_id"] = 77
    wrong = post()
    wrong["content"]["raw"] += "changed"
    with pytest.raises(NewsError, match="differs"):
        p.publish(data, {"post": wrong, "media": None})
    assert p.actions == []


def test_missing_recovery_post_never_creates(data, tmp_path):
    p = publisher(tmp_path)
    data["recovery_post_id"] = 77
    with pytest.raises(NewsError, match="never create"):
        p.publish(data, {"post": None, "media": None})
    assert p.actions == []


def test_published_source_match_is_not_overwritten(data, tmp_path):
    p = publisher(tmp_path)
    existing = post("publish", 88)
    existing["content"]["raw"] = "Independent article about Alden Wade."
    with pytest.raises(NewsError, match="no overwrite"):
        p.publish(data, {"post": existing, "media": None})
    assert p.actions == []


def test_success_uses_draft_then_same_id_and_original_photo(data, tmp_path):
    p = publisher(tmp_path)
    state = post()
    media = {"id": 88, "slug": MEDIA_SLUG, "post": 77, "status": "inherit", "alt_text": ""}
    p.category = Mock(return_value=4)
    p.original_image = Mock(return_value=p.photo)
    p.verify_public = Mock(return_value={"state": "published", "post_id": 77})
    def api(method, url, **kwargs):
        endpoint = url.split("/wp/v2/")[1]
        if endpoint == "posts" and method == "POST":
            assert kwargs["json"]["status"] == "draft"
            return response(copy.deepcopy(state))
        if endpoint == "media" and method == "POST":
            assert kwargs["data"] == p.photo
            assert kwargs["params"]["post"] == 77
            return response(copy.deepcopy(media))
        if endpoint == "media/88" and method == "POST":
            media.update(kwargs["json"])
            return response(copy.deepcopy(media))
        if endpoint == "posts/77":
            if method == "POST": state.update(kwargs["json"])
            return response(copy.deepcopy(state))
        pytest.fail("Unexpected operation")
    p.auth.request.side_effect = api
    assert p.publish(data, {"post": None, "media": None})["post_id"] == 77
    assert [a["endpoint"] for a in p.actions] == ["posts", "media", "media/88", "posts/77", "posts/77"]
    assert state["status"] == "publish" and state["featured_media"] == 88
    assert state["meta"]["_seopress_titles_desc"] == EXCERPT


def test_alt_update_failure_stops_before_publish(data, tmp_path):
    p = publisher(tmp_path)
    data["recovery_post_id"] = 77
    media = {"id": 88, "slug": MEDIA_SLUG, "post": 77, "status": "inherit", "alt_text": ""}
    p.original_image = Mock(return_value=p.photo)
    p.auth.request.return_value = response({}, code=500)
    with pytest.raises(NewsError):
        p.publish(data, {"post": post(), "media": media})
    assert len(p.actions) == 1 and p.actions[0]["endpoint"] == "media/88"


def test_lost_publish_response_reads_same_id_without_retry(data, tmp_path):
    p = publisher(tmp_path)
    data["recovery_post_id"] = 77
    state = post()
    media = {"id": 88, "post": 77, "status": "inherit", "alt_text": ALT}
    p.original_image = Mock(return_value=p.photo)
    def api(method, url, **kwargs):
        if method == "POST":
            state.update(kwargs["json"])
            if kwargs["json"].get("status") == "publish": raise requests.Timeout()
        return response(copy.deepcopy(state))
    p.auth.request.side_effect = api
    with pytest.raises(NewsError, match="uncertain"):
        p.publish(data, {"post": post(), "media": media})
    assert state["status"] == "publish"
    assert sum(call.kwargs.get("json", {}).get("status") == "publish" for call in p.auth.request.call_args_list) == 1
    assert json.loads((tmp_path / "uncertain-post.json").read_text())["id"] == 77


def test_public_verification_rejects_wrong_body_before_success(tmp_path):
    p = publisher(tmp_path)
    value = post("publish", 88)
    p.public.get.return_value = response({"status": "publish", "slug": SLUG, "featured_media": 88,
                            "title": {"rendered": HEADLINE}, "content": {"rendered": "Wrong story"}})
    with pytest.raises(NewsError, match="Public REST"):
        p.verify_public(value, 88, "published")


def test_public_verification_checks_canonical_seo_links_and_pixels(tmp_path):
    p = publisher(tmp_path)
    value = post("publish", 88)
    image_url = "https://sportsmississippi.com/wp-content/uploads/2026/10/" + MEDIA_SLUG + ".jpg"
    media = {"id": 88, "source_url": image_url, "alt_text": ALT, "media_details": {}}
    html_page = (f'<html><head><title>{HEADLINE}</title><meta name="description" content="{EXCERPT}">'
                 f'<link rel="canonical" href="{value["link"]}"></head><body><h1>{HEADLINE}</h1>'
                 f'{BODY}<img src="{image_url}" alt="{ALT}"></body></html>')
    def get(url, **kwargs):
        if "/wp/v2/posts/" in url:
            return response({"status": "publish", "slug": SLUG, "featured_media": 88,
                    "title": {"rendered": HEADLINE}, "content": {"rendered": BODY}})
        if "/wp/v2/media/" in url: return response(media)
        if url == image_url:
            r = response({})
            r.content = p.photo
            return r
        r = response({})
        r.text = "User-agent: *\nDisallow: /wp-admin/" if url.endswith("robots.txt") else html_page
        r.content = r.text.encode()
        return r
    p.public.get.side_effect = get
    result = p.verify_public(value, 88, "published")
    assert result["public_verification"]["original_image_bytes_and_pixels"] is True
    html_page = html_page.replace(f'href="{value["link"]}"', 'href="https://sportsmississippi.com/wrong/"')
    with pytest.raises(NewsError, match="canonical"):
        p.verify_public(value, 88, "published")


def test_repair_scope_cannot_target_another_post_or_media(data):
    from rss_to_wp.news.publisher import RECOMPRESSED_SHA
    data["image_repair"] = {"post_id": 24460, "media_id": 24461,
        "observed_image_sha256": RECOMPRESSED_SHA, "expected_modified_gmt": "2026-10-12T13:34:20"}
    validate(data)
    data["image_repair"]["post_id"] = 999
    with pytest.raises(NewsError, match="exact known"):
        validate(data)


def test_original_restoration_is_same_attachment_no_conversion_and_post_only_style(data, tmp_path):
    from rss_to_wp.news.publisher import REPAIR_POST, REPAIR_MEDIA, RECOMPRESSED_SHA, PORTRAIT_STYLE
    p = publisher(tmp_path)
    data["image_repair"] = {"post_id": REPAIR_POST, "media_id": REPAIR_MEDIA,
        "observed_image_sha256": RECOMPRESSED_SHA, "expected_modified_gmt": "2026-10-12T12:00:00"}
    state = post("publish", REPAIR_MEDIA)
    state["id"] = REPAIR_POST
    media = {"id": REPAIR_MEDIA, "post": REPAIR_POST, "source_url": "https://sportsmississippi.com/restored.jpg"}
    # Already restored original: never upload again, only apply the scoped style.
    p.original_image = Mock(return_value=p.photo)
    p.verify_public = Mock(return_value={"state": "published", "post_id": REPAIR_POST})
    def api(method, url, **kwargs):
        endpoint = url.split("/wp/v2/")[1]
        if endpoint == "users/me": return response({"capabilities": {"unfiltered_html": True}})
        if method == "OPTIONS":
            return response({"endpoints": [{"methods": ["POST"], "args": {"image_size": {}, "convert_format": {}}}]})
        if endpoint == f"posts/{REPAIR_POST}":
            if method == "POST":
                assert list(kwargs["json"]) == ["content"]
                state["content"] = {"raw": kwargs["json"]["content"]}
            return response(copy.deepcopy(state))
        if endpoint == f"media/{REPAIR_MEDIA}": return response(media)
        pytest.fail("Unexpected image recreation")
    p.auth.request.side_effect = api
    result = p.restore_portrait(data, {"post": copy.deepcopy(state), "media": media})
    assert result["post_id"] == REPAIR_POST
    assert len(p.actions) == 1 and p.actions[0]["endpoint"] == "posts/24460"
    assert state["content"]["raw"] == BODY + "\n" + MARKER + "\n" + PORTRAIT_STYLE


def test_recompressed_image_replaced_once_on_same_attachment(data, tmp_path, monkeypatch):
    import rss_to_wp.news.publisher as news
    p = publisher(tmp_path)
    data["image_repair"] = {"post_id": 24460, "media_id": 24461,
        "observed_image_sha256": news.RECOMPRESSED_SHA, "expected_modified_gmt": "2026-10-12T12:00:00"}
    state = post("publish", 24461)
    state["id"] = 24460
    media = {"id": 24461, "post": 24460, "source_url": "https://sportsmississippi.com/restored.jpg"}
    uploaded = False
    real_digest = news.digest
    monkeypatch.setattr(news, "digest", lambda b: news.RECOMPRESSED_SHA if b == b"recompressed-fixture" else real_digest(b))
    p.original_image = Mock(side_effect=lambda value: p.photo if uploaded else b"recompressed-fixture")
    p.verify_public = Mock(return_value={"state": "published", "post_id": 24460})
    receipt = {"image_size": "original", "width": 765, "height": 906, "filesize": len(p.photo),
               "file": "2026/10/" + MEDIA_SLUG + "-restored-original.jpg", "original_image": MEDIA_SLUG + ".jpg"}
    def api(method, url, **kwargs):
        nonlocal uploaded
        endpoint = url.split("/wp/v2/")[1]
        if endpoint == "users/me": return response({"capabilities": {"unfiltered_html": True}})
        if method == "OPTIONS": return response({"endpoints": [{"methods": ["POST"], "args": {"image_size": {}, "convert_format": {}}}]})
        if endpoint == "media/24461/sideload":
            assert kwargs["data"] == p.photo
            assert kwargs["params"] == {"image_size": "original", "convert_format": "false"}
            uploaded = True
            return response(receipt)
        if endpoint == "media/24461/finalize":
            assert kwargs["json"] == {"sub_sizes": [receipt]}
            return response(media)
        if endpoint == "media/24461": return response(media)
        if endpoint == "posts/24460":
            if method == "POST": state["content"] = {"raw": kwargs["json"]["content"]}
            return response(copy.deepcopy(state))
        pytest.fail("New post or attachment not authorized")
    p.auth.request.side_effect = api
    assert p.restore_portrait(data, {"post": copy.deepcopy(state), "media": media})["post_id"] == 24460
    assert [a["endpoint"] for a in p.actions] == ["media/24461/sideload", "media/24461/finalize", "posts/24460"]
