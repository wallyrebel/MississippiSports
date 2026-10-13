import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import refresh_jones_cache as m


class FakeWorker:
    def __init__(self, output):
        self.output = output
        self.actions = []
        self.audit = {"queries": [], "statuses": []}
        baseline = json.loads((ROOT / "corrections/cache-refresh-baseline.json").read_text())
        self.post = {k: v for k, v in baseline.items() if not k.endswith("_raw")}
        for field in ("title", "content", "excerpt"):
            self.post[field] = {"rendered": baseline[field], "raw": baseline[field + "_raw"]}
        from correct_audited_posts import MEDIA_CORE
        self.media = {k: None for k in MEDIA_CORE}
        self.media.update(id=24509, author=1, status="inherit", alt_text=m.ALT, post=None,
                          source_url="https://sportsmississippi.com/image.webp")
        for field in ("title", "caption", "description"):
            self.media[field] = {"rendered": "same", "raw": "same"}
        self.writes = 0
        self.fail_write = False
        self.already_correct = False

    def save(self, name, value):
        (self.output / name).write_text(json.dumps(value))

    def schema(self, endpoint):
        values = ["publish", "future", "draft", "pending", "private", "trash"] if endpoint == "posts" else ["inherit", "private", "trash"]
        self.audit["statuses"].append({"endpoint": endpoint, "statuses": values})
        return values

    def collect(self, status, endpoint, ids):
        assert ids == ((24510,) if endpoint == "posts" else (24509,))
        self.audit["queries"].append({"endpoint": endpoint, "status": status})
        item = self.post if endpoint == "posts" else self.media
        return [copy.deepcopy(item)] if item["status"] == status else []

    def read(self, endpoint, **kwargs):
        if endpoint == "users/me":
            return {"id": 1, "capabilities": {"edit_posts": True, "edit_published_posts": True}}
        assert endpoint in ("posts/24510", "media/24509")
        return copy.deepcopy(self.post if endpoint.startswith("posts") else self.media)

    def request(self, method, endpoint, **kwargs):
        assert method == "POST" and endpoint == "posts/24510" and kwargs == {"json": {"title": m.TITLE}}
        self.writes += 1
        if self.fail_write:
            raise m.CorrectionError("Outcome unavailable")
        self.post["modified"] = self.post["modified_gmt"] = "later"

    def public_get(self, url):
        class R:
            pass
        r = R()
        if url.endswith("image.webp"):
            r.content = b"same image"
        else:
            alt = m.ALT if self.writes or self.already_correct else m.ALT.replace("No. 22", "No. 21")
            r.content = f'<article id="post-24510"><img class="wp-post-image" src="DSC00682_IOZnX.webp" alt="{alt}"></article>'.encode()
        return r


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "ROOT", tmp_path)
    monkeypatch.setattr(m, "IMAGE_SHA", m.hashlib.sha256(b"same image").hexdigest())
    for k, v in {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main", "GITHUB_RUN_ATTEMPT": "1",
                 "GITHUB_RUN_ID": "456", "GITHUB_SHA": "a" * 40}.items():
        monkeypatch.setenv(k, v)
    approval = json.loads((ROOT / "corrections/cache-refresh-control.json").read_text())
    return FakeWorker(tmp_path), approval


def test_exact_same_title_once_preserves_every_field_except_modified(tmp_path, monkeypatch):
    w, approval = setup(tmp_path, monkeypatch)
    result = m.run(w, approval)
    assert w.writes == 1 and result["ordinary_canonical_image_alt_verified"]
    assert w.actions == [{"method": "POST", "endpoint": "posts/24510", "payload": {"title": m.TITLE}, "state": "confirmed"}]
    assert len(w.audit["queries"]) == 9


@pytest.mark.parametrize("problem", ["snapshot", "alt", "approval", "rerun"])
def test_drift_or_wrong_approval_prevents_write(tmp_path, monkeypatch, problem):
    w, approval = setup(tmp_path, monkeypatch)
    if problem == "snapshot":
        w.post["modified_gmt"] = "changed"
    elif problem == "alt":
        w.media["alt_text"] = "No. 21"
    elif problem == "approval":
        approval["post_id"] = 24487
    else:
        monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    with pytest.raises(m.CorrectionError):
        m.run(w, approval)
    assert w.writes == 0


def test_uncertain_save_not_retried_reconciles_same_id(tmp_path, monkeypatch):
    w, approval = setup(tmp_path, monkeypatch)
    w.fail_write = True
    with pytest.raises(m.CorrectionError, match="Outcome unavailable"):
        m.run(w, approval)
    assert w.writes == 1
    assert (tmp_path / "uncertain-post.json").exists()
    assert w.actions[0]["state"] == "uncertain_or_failed"


def test_already_fresh_page_does_not_write(tmp_path, monkeypatch):
    w, approval = setup(tmp_path, monkeypatch)
    w.already_correct = True
    result = m.run(w, approval)
    assert result["already_correct_no_write"] and w.writes == 0
