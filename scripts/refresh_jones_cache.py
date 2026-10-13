"""Parent-approved one-shot same-title save of post 24510; no cache settings."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from correct_audited_posts import CorrectionError, Worker, digest, edit_snapshot, media_snapshot, require

ROOT = Path(__file__).resolve().parents[1]
POST_ID = 24510
TITLE = "Jones College Volleyball Beats Pearl River 3-1 to Avenge Early-Season Loss"
BEFORE_SHA = "bcfbf04f9b41c4cea533c1300f31edc7ffdfac793b8f6ed931fdff5e7162f6d6"
MODIFIED = "2026-10-13T15:40:15"
ALT = "No. 22 Jones avenges early-season loss, downs No. 25 Pearl River 3-1"
IMAGE_SHA = "ccc5467f29820145ac97d0e8dad2ef6858d6787b062cf3a2934541a8184cb2f5"
SITE = "https://sportsmississippi.com"


def ordinary_page_verified(worker, url):
    page = worker.public_get(url)
    soup = BeautifulSoup(page.content, "html.parser")
    images = [img for img in soup.select("#post-24510 img.wp-post-image")
              if "DSC00682_IOZnX" in img.get("src", "") + img.get("data-lazy-src", "")]
    return bool(images) and all(img.get("alt") == ALT for img in images)


def run(worker, approval):
    require(approval == {"parent_approved": True, "post_id": POST_ID, "payload": {"title": TITLE},
                        "expected_edit_snapshot_sha256": BEFORE_SHA, "expected_modified_gmt": MODIFIED},
            "Cache refresh approval differs from the one parent-approved save")
    require(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_REF") == "refs/heads/main"
            and os.environ.get("GITHUB_RUN_ATTEMPT") == "1", "Only first managed Actions attempt on main")
    require(not (ROOT / "corrections/cache-refresh-receipt.json").exists(), "Cache refresh mutation retired")
    me = worker.read("users/me", params={"context": "edit", "_fields": "id,capabilities"})
    require(me.get("capabilities", {}).get("edit_posts") is True and
            me.get("capabilities", {}).get("edit_published_posts") is True, "Editing capability unavailable")
    posts = []
    for status in worker.schema("posts"):
        posts.extend(worker.collect(status, "posts", (POST_ID,)))
    media = []
    for status in worker.schema("media"):
        media.extend(worker.collect(status, "media", (24509,)))
    require(len(posts) == 1 and posts[0]["id"] == POST_ID and posts[0]["status"] == "publish",
            "Post identity/status differs")
    require(len(media) == 1 and media[0]["id"] == 24509 and media[0]["status"] == "inherit",
            "Media identity/status differs")
    before = edit_snapshot(posts[0])
    require(digest(before) == BEFORE_SHA and before["modified_gmt"] == MODIFIED and
            before["title_raw"] == TITLE and before["featured_media"] == 24509,
            "Fresh raw snapshot differs from parent-approved post; stop without writing")
    require(before["author"] == me.get("id") or me.get("capabilities", {}).get("edit_others_posts") is True,
            "Cannot edit another author's post")
    media_before = media_snapshot(media[0], edit=True)
    require(media_before["alt_text"] == ALT and media_before["post"] in (None, 0, POST_ID),
            "Jones media alt or association differs")
    require(hashlib.sha256(worker.public_get(media_before["source_url"]).content).hexdigest() == IMAGE_SHA,
            "Jones image file differs")
    worker.save("before-post.json", before)
    worker.save("before-media.json", media_before)
    worker.save("preflight.json", {"all_statuses_checked": True, **worker.audit})
    already_correct = ordinary_page_verified(worker, before["link"])
    if not already_correct:
        # Recheck both exact records immediately before the only allowed write.
        require(edit_snapshot(worker.read("posts/24510", params={"context": "edit"})) == before and
                media_snapshot(worker.read("media/24509", params={"context": "edit"}), edit=True) == media_before,
                "Record changed immediately before cache refresh")
        action = {"method": "POST", "endpoint": "posts/24510", "payload": {"title": TITLE}, "state": "attempted"}
        worker.actions.append(action)
        worker.save("actions.json", worker.actions)
        try:
            worker.request("POST", "posts/24510", json={"title": TITLE})
        except CorrectionError:
            action["state"] = "uncertain_or_failed"
            worker.save("actions.json", worker.actions)
            try:
                worker.save("uncertain-post.json", edit_snapshot(worker.read("posts/24510", params={"context": "edit"})))
            except CorrectionError:
                pass
            raise
    after = edit_snapshot(worker.read("posts/24510", params={"context": "edit"}))
    require(all(after[k] == v for k, v in before.items() if k not in ("modified", "modified_gmt")),
            "Post fields changed beyond normal modified timestamp")
    media_after = media_snapshot(worker.read("media/24509", params={"context": "edit"}), edit=True)
    require(media_after == media_before, "Media changed during post-only cache refresh")
    worker.save("after-post.json", after)
    worker.save("after-media.json", media_after)
    if worker.actions:
        worker.actions[0]["state"] = "confirmed"
        worker.save("actions.json", worker.actions)
    require(ordinary_page_verified(worker, before["link"]), "Ordinary canonical page image alt remains stale")
    require(hashlib.sha256(worker.public_get(media_after["source_url"]).content).hexdigest() == IMAGE_SHA,
            "Jones image bytes changed")
    receipt = {"post_id": POST_ID, "link": before["link"], "ordinary_canonical_image_alt_verified": True,
               "alt_text": ALT, "same_post_content_url_publication_dates_meta_and_media": True,
               "media_record_and_file_bytes_unchanged": True, "already_correct_no_write": already_correct,
               "writes": len(worker.actions), "run_id": os.environ.get("GITHUB_RUN_ID"),
               "commit": os.environ.get("GITHUB_SHA"), "retire_mutation_route": True}
    worker.save("cache-refresh-receipt.json", receipt)
    return receipt


def main():
    output = Path("cache-refresh-output")
    output.mkdir(exist_ok=True)
    worker = None
    try:
        require(os.environ.get("GITHUB_ACTIONS") == "true", "Existing credentials only inside Actions")
        require(os.environ.get("WORDPRESS_BASE_URL", "").rstrip("/") == SITE, "Managed site mismatch")
        require(os.environ.get("WORDPRESS_USERNAME") and os.environ.get("WORDPRESS_APP_PASSWORD"),
                "Existing managed credentials unavailable")
        auth, public = requests.Session(), requests.Session()
        auth.auth = (os.environ["WORDPRESS_USERNAME"], os.environ["WORDPRESS_APP_PASSWORD"])
        auth.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
        public.headers.update({"User-Agent": "curl/8.7.1"})
        worker = Worker(auth, public, output)
        control = json.loads((ROOT / "corrections/cache-refresh-control.json").read_text())
        run(worker, control)
        worker.save("result.json", {"ok": True, "writes": len(worker.actions)})
    except (CorrectionError, ValueError, KeyError, TypeError, FileNotFoundError):
        import sys
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, CorrectionError) else "Invalid cache-refresh data or REST response"
        (output / "result.json").write_text(json.dumps({"ok": False, "error": message,
                   "writes_attempted": len(worker.actions) if worker else 0}, indent=2) + "\n")
        print(message)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
