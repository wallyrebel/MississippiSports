import copy
import importlib.util
import json
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("corrections", ROOT / "scripts/correct_audited_posts.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Response:
    def __init__(self, data, total=0, pages=0, status=200, text=""):
        self.data, self.status_code, self.text = data, status, text
        self.headers = {"X-WP-Total": str(total), "X-WP-TotalPages": str(pages)}
        self.content = b"unchanged-image-bytes"

    def json(self):
        return copy.deepcopy(self.data)


class Auth:
    def __init__(self, data):
        self.posts = {}
        self.calls = []
        self.fail_post = False
        self.bad_total = False
        self.caps = True
        for p in data["posts"]:
            post = copy.deepcopy(p["expected_public"])
            for f in ("title", "content", "excerpt"):
                post[f] = {"raw": post[f], "rendered": post[f]}
            self.posts[p["id"]] = post
        self.media = copy.deepcopy(data["media"]["expected_public"])
        for field in ("title", "caption", "description"):
            self.media[field]["raw"] = self.media[field]["rendered"]

    def request(self, method, url, **kwargs):
        endpoint = url.split("/wp/v2/")[1]
        self.calls.append((method, endpoint, kwargs))
        if method == "OPTIONS":
            statuses = ["inherit", "private", "trash", "any"] if endpoint == "media" else ["publish", "future", "draft", "pending", "private", "trash", "any"]
            return Response({"endpoints": [{"methods": ["GET"], "args": {"status": {"items": {
                "enum": statuses}}}}],
                "schema": {"properties": {"meta": {"properties": {k: {} for k in m.SEO}}}}})
        if endpoint == "users/me":
            return Response({"id": 1, "capabilities": {"edit_posts": self.caps, "edit_published_posts": self.caps}})
        if endpoint.startswith("tags/"):
            id = int(endpoint.split("/")[1])
            return Response({"id": id, "name": m.TAG_NAMES[id]})
        if endpoint in ("posts", "media"):
            status = dict(kwargs["params"])["status"]
            values = [p for p in (self.posts.values() if endpoint == "posts" else [self.media]) if p["status"] == status]
            return Response(values, len(values) + int(self.bad_total), int(bool(values)))
        if endpoint == "media/24509":
            if method == "POST":
                self.media.update(kwargs["json"])
            return Response(self.media)
        id = int(endpoint.split("/")[1])
        if method == "POST":
            if self.fail_post:
                raise requests.ConnectionError("private credential-bearing error must not appear")
            for k, v in kwargs["json"].items():
                if k in ("title", "content", "excerpt"):
                    self.posts[id][k] = {"raw": v, "rendered": v}
                elif k == "meta":
                    self.posts[id][k].update(v)
                else:
                    self.posts[id][k] = v
        return Response(self.posts[id])


def setup(tmp_path, monkeypatch):
    data = m.load_manifest(ROOT / "corrections/2026-10-13.json")
    # Exercise the historical worker in isolation from the real retired receipt.
    monkeypatch.setattr(m, "ROOT", tmp_path)
    # Original source digests are checked live; the transport fixture uses one
    # immutable body to exercise the failure boundaries without network calls.
    for p in data["posts"]:
        p["source"]["article_sha256"] = m.hashlib.sha256(b"source body").hexdigest()
        p["source"].pop("required_page_text", None)
    auth = Auth(data)
    w = m.Worker(auth, None, tmp_path)
    monkeypatch.setattr(w, "public_get", lambda url: Response({}, text='<div id="storyPageContentBody">source body</div>'))
    return data, auth, w


def approve(plan, monkeypatch):
    for k, v in {"GITHUB_ACTIONS": "true", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REF": "refs/heads/main",
                 "GITHUB_RUN_ID": "123", "GITHUB_SHA": "a" * 40}.items():
        monkeypatch.setenv(k, v)
    return {"apply": True, "parent_reviewed": True, "parent_priority_released": True,
            "approved_plan_sha256": m.digest(plan), "preflight_run_id": "122", "preflight_commit": "b" * 40}


def test_immutable_scope_rejects_other_post_and_seo(tmp_path):
    data = json.loads((ROOT / "corrections/2026-10-13.json").read_text())
    for change in (lambda d: d["posts"][0].update(id=24487),
                   lambda d: d["posts"][0]["patch"].update(meta={"_seopress_robots_index": "yes"})):
        value = copy.deepcopy(data)
        change(value)
        p = tmp_path / "changed.json"
        p.write_text(json.dumps(value))
        with pytest.raises(m.CorrectionError, match="Manifest differs"):
            m.load_manifest(p)


def test_dry_run_all_statuses_and_exact_payload_no_writes(tmp_path, monkeypatch):
    data, auth, w = setup(tmp_path, monkeypatch)
    plan = w.preflight(data)
    assert [p["id"] for p in plan["posts"]] == list(m.IDS)
    assert len(w.audit["queries"]) == 9
    assert {q["status"] for q in w.audit["queries"]} == {s for x in w.audit["statuses"] for s in x["statuses"]}
    assert not any(c[0] == "POST" for c in auth.calls)
    assert json.loads((tmp_path / "actions.json").read_text()) == []
    assert plan["posts"][0]["patch"]["tags"] == [1724, 55, 1019, 135]


@pytest.mark.parametrize("problem", ["capability", "drift", "trash", "pagination", "source"])
def test_preflight_failures_stop_before_mutation(tmp_path, monkeypatch, problem):
    data, auth, w = setup(tmp_path, monkeypatch)
    if problem == "capability":
        auth.caps = False
    elif problem == "drift":
        auth.posts[24483]["featured_media"] = 999
    elif problem == "trash":
        auth.posts[24483]["status"] = "trash"
    elif problem == "pagination":
        auth.bad_total = True
    else:
        data["posts"][0]["source"]["article_sha256"] = "0" * 64
    with pytest.raises(m.CorrectionError):
        w.preflight(data)
    assert not any(c[0] == "POST" for c in auth.calls)


@pytest.mark.parametrize("gate", ["parent_reviewed", "parent_priority_released", "approved_plan_sha256", "rerun"])
def test_review_digest_priority_and_rerun_gates(tmp_path, monkeypatch, gate):
    data, auth, w = setup(tmp_path, monkeypatch)
    plan = w.preflight(data)
    control = approve(plan, monkeypatch)
    if gate == "rerun":
        monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    else:
        control[gate] = False
    with pytest.raises(m.CorrectionError):
        w.apply(plan, control)
    assert not any(c[0] == "POST" for c in auth.calls)


def test_all_post_recheck_before_first_write(tmp_path, monkeypatch):
    data, auth, w = setup(tmp_path, monkeypatch)
    plan = w.preflight(data)
    control = approve(plan, monkeypatch)
    auth.posts[24433]["modified_gmt"] = "changed"
    with pytest.raises(m.CorrectionError, match="no writes"):
        w.apply(plan, control)
    assert not any(c[0] == "POST" for c in auth.calls)


def test_unknown_mutation_stops_once_and_reconciles_same_id(tmp_path, monkeypatch):
    data, auth, w = setup(tmp_path, monkeypatch)
    plan = w.preflight(data)
    control = approve(plan, monkeypatch)
    auth.fail_post = True
    with pytest.raises(m.CorrectionError, match="outcome unavailable"):
        w.apply(plan, control)
    assert [(c[0], c[1]) for c in auth.calls if c[0] == "POST"] == [("POST", "posts/24483")]
    assert (tmp_path / "uncertain-24483.json").exists()
    assert w.actions[0]["state"] == "uncertain_or_failed"
    assert "private credential" not in (tmp_path / "actions.json").read_text()


def test_six_exact_updates_preserve_identity_dates_media_meta(tmp_path, monkeypatch):
    data, auth, w = setup(tmp_path, monkeypatch)
    plan = w.preflight(data)
    control = approve(plan, monkeypatch)
    monkeypatch.setattr(w, "verify_public", lambda item: {"id": item["id"]})
    monkeypatch.setattr(w, "public_get", lambda url: Response(auth.media))
    monkeypatch.setattr(w, "verify_surfaces", lambda plan: [])
    result = w.apply(plan, control)
    assert [p["id"] for p in result["posts"]] == list(m.IDS)
    assert [c[1] for c in auth.calls if c[0] == "POST"] == [f"posts/{id}" for id in m.IDS] + ["media/24509"]
    assert (tmp_path / "completion-receipt.json").exists()
    for item in plan["posts"]:
        w.validate_after(auth.posts[item["id"]], item)
    wrong = copy.deepcopy(auth.posts[24483])
    wrong["meta"]["_seopress_robots_index"] = "yes"
    with pytest.raises(m.CorrectionError, match="metadata changed"):
        w.validate_after(wrong, plan["posts"][0])


def test_never_post_to_collection_media_or_unrelated_id(tmp_path):
    w = m.Worker(None, None, tmp_path)
    for endpoint in ("posts", "posts/24487", "media/24482", "tags"):
        with pytest.raises(m.CorrectionError, match="outside six"):
            w.request("POST", endpoint, json={})


def test_media_drift_prevents_all_post_writes(tmp_path, monkeypatch):
    data, auth, w = setup(tmp_path, monkeypatch)
    plan = w.preflight(data)
    control = approve(plan, monkeypatch)
    auth.media["source_url"] = "https://sportsmississippi.com/unrelated.jpg"
    with pytest.raises(m.CorrectionError, match="media changed"):
        w.apply(plan, control)
    assert not any(c[0] == "POST" for c in auth.calls)


def test_completed_receipt_retires_mutation(tmp_path, monkeypatch):
    data, auth, w = setup(tmp_path, monkeypatch)
    plan = w.preflight(data)
    control = approve(plan, monkeypatch)
    (tmp_path / "corrections").mkdir()
    (tmp_path / "corrections/completion-receipt.json").write_text('{}')
    monkeypatch.setattr(m, "ROOT", tmp_path)
    with pytest.raises(m.CorrectionError, match="retired"):
        w.apply(plan, control)
    assert not any(c[0] == "POST" for c in auth.calls)
