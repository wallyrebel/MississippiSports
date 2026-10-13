"""One-shot, digest-bound corrections of six existing audited posts.

No publication discovery, credential provisioning, new posts, media operations,
taxonomy creation, or retry of mutations. Credentials are injected by Actions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

SITE = "https://sportsmississippi.com"
IDS = (24483, 24473, 24451, 24445, 24510, 24433)
MANIFEST_SHA = "6c9e8ca9227c6be9a5a2e22867b39da8865c0e9d8fb32dcc0fed6704639cbd65"
SEO = {"_seopress_titles_title", "_seopress_titles_desc"}
REMOVALS = {24483: [179], 24473: [5878], 24451: [1869]}
TAG_NAMES = {179: "Football", 5878: "Zachary University", 1869: "William Carey"}
CORE = ("id", "slug", "status", "type", "link", "date", "date_gmt", "modified",
        "modified_gmt", "author", "featured_media", "categories", "tags",
        "comment_status", "ping_status", "sticky", "template", "format", "meta")
PRESERVED = tuple(k for k in CORE if k not in ("modified", "modified_gmt", "tags", "meta"))
MEDIA_CORE = ("id", "author", "date", "date_gmt", "modified", "modified_gmt", "slug", "status",
              "type", "link", "post", "alt_text", "source_url", "media_details", "meta")
ROOT = Path(__file__).resolve().parents[1]


class CorrectionError(Exception):
    pass


def require(ok, message):
    if not ok:
        raise CorrectionError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode()).hexdigest()


def plain(html):
    return re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" ", strip=True)).strip()


def typography(text):
    return text.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'}))


def public_snapshot(post):
    require(all(k in post for k in CORE), "Incomplete post identity snapshot")
    snap = {k: post[k] for k in CORE}
    for k in ("title", "content", "excerpt"):
        require(isinstance(post.get(k, {}).get("rendered"), str), "Rendered field unavailable")
        snap[k] = post[k]["rendered"]
    return snap


def edit_snapshot(post):
    result = public_snapshot(post)
    for k in ("title", "content", "excerpt"):
        require(isinstance(post[k].get("raw"), str), "Edit-context field unavailable")
        result[k + "_raw"] = post[k]["raw"]
    return result


def media_snapshot(media, edit=False):
    require(all(k in media for k in MEDIA_CORE), "Incomplete media identity snapshot")
    result = {k: media[k] for k in MEDIA_CORE}
    for k in ("title", "caption", "description"):
        result[k] = {"rendered": media[k]["rendered"]}
        if edit:
            require(isinstance(media[k].get("raw"), str), "Media edit field unavailable")
            result[k + "_raw"] = media[k]["raw"]
    return result


def load_manifest(path):
    data = json.loads(Path(path).read_text())
    require(digest(data) == MANIFEST_SHA, "Manifest differs from the six reviewed corrections")
    require(data["site"] == SITE and tuple(p["id"] for p in data["posts"]) == IDS,
            "Post scope or site changed")
    for p in data["posts"]:
        patch = p["patch"]
        require(set(patch) <= {"title", "excerpt", "content", "tags"}, "Forbidden patch field")
        require(p["removed_tags"] == REMOVALS.get(p["id"], []), "Unreviewed tag removal")
        if "tags" in patch:
            require(patch["tags"] == [t for t in p["expected_public"]["tags"]
                                      if t not in REMOVALS[p["id"]]], "Unreviewed tag change")
    require(data["media"]["id"] == 24509 and set(data["media"]["patch"]) == {"alt_text"},
            "Only the reviewed Jones attachment alt text may change")
    return data


class Worker:
    def __init__(self, auth, public, output):
        self.auth, self.public = auth, public
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.actions, self.audit = [], {"queries": [], "statuses": []}
        self.save("actions.json", self.actions)

    def save(self, name, value):
        (self.output / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")

    def request(self, method, endpoint, **kwargs):
        require(method in ("GET", "OPTIONS", "POST"), "Unsupported request")
        require(method != "POST" or endpoint in {f"posts/{id}" for id in IDS} | {"media/24509"},
                "Mutation outside six existing posts and reviewed Jones media")
        try:
            response = self.auth.request(method, f"{SITE}/wp-json/wp/v2/{endpoint}",
                                         timeout=(10, 45), allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise CorrectionError(f"WordPress {method} {endpoint} outcome unavailable") from None
        require(200 <= response.status_code < 300,
                f"WordPress {method} {endpoint} failed (HTTP {response.status_code})")
        return response

    def read(self, endpoint, **kwargs):
        try:
            return self.request("GET", endpoint, **kwargs).json()
        except ValueError:
            raise CorrectionError("WordPress read returned invalid JSON") from None

    def public_get(self, url):
        require(urlparse(url).scheme == "https" and not urlparse(url).username,
                "Unsafe public source URL")
        require(urlparse(url).netloc in {"sportsmississippi.com", "hailstate.com",
                    "owlsathletics.com", "alcornsports.com", "jcbobcats.com"}, "Unexpected source host")
        try:
            r = self.public.get(url, timeout=(10, 45), allow_redirects=False)
        except requests.RequestException:
            raise CorrectionError("Public source or verification read unavailable") from None
        require(r.status_code == 200, f"Public source or verification failed (HTTP {r.status_code})")
        return r

    def schema(self, endpoint="posts"):
        schema = self.request("OPTIONS", endpoint).json()
        statuses = []
        for route in schema.get("endpoints", []):
            if "GET" in route.get("methods", []) and "status" in route.get("args", {}):
                statuses = [s for s in route["args"]["status"].get("items", {}).get("enum", [])
                            if s != "any"]
                break
        needed = {"publish", "future", "draft", "pending", "private", "trash"} if endpoint == "posts" else {"inherit", "private", "trash"}
        require(needed <= set(statuses),
                "All supported statuses could not be established")
        if endpoint == "posts":
            properties = schema.get("schema", {}).get("properties", {})
            require(SEO <= set(properties.get("meta", {}).get("properties", {})),
                    "SEO registration could not be audited")
        self.audit["statuses"].append({"endpoint": endpoint, "statuses": statuses})
        return statuses

    def collect(self, status, endpoint="posts", ids=IDS):
        # Include only the six IDs, but explicitly cover every supported status.
        params = [("include[]", id) for id in ids] + [("status", status), ("context", "edit"),
                  ("per_page", 100), ("orderby", "id"), ("order", "asc")]
        values, total, pages, page = [], None, None, 1
        while True:
            r = self.request("GET", endpoint, params=params + [("page", page)])
            try:
                batch = r.json()
                now = int(r.headers["X-WP-Total"]), int(r.headers["X-WP-TotalPages"])
            except (KeyError, ValueError, TypeError):
                raise CorrectionError("All-status pagination unavailable") from None
            require(isinstance(batch, list) and 0 <= now[1] <= 1000, "Invalid pagination")
            if total is None:
                total, pages = now
            require((total, pages) == now, "Posts changed during pagination")
            values.extend(batch)
            if page >= pages:
                break
            page += 1
        require(len(values) == total and len({p["id"] for p in values}) == total,
                "Incomplete all-status preflight")
        require(all(p["id"] in ids and p["status"] == status for p in values), "Unexpected record result")
        self.audit["queries"].append({"endpoint": endpoint, "status": status, "ids": [p["id"] for p in values],
                                       "total": total, "pages": pages})
        return values

    def preflight(self, data):
        me = self.read("users/me", params={"context": "edit", "_fields": "id,capabilities"})
        require(all(me.get("capabilities", {}).get(k) is True
                    for k in ("edit_posts", "edit_published_posts")), "Managed account lacks editing capability")
        self.save("capability-check.json", {"account_id": me.get("id"),
                  "capabilities": {k: me.get("capabilities", {}).get(k) for k in
                      ("edit_posts", "edit_published_posts", "edit_others_posts")}})
        statuses = self.schema()
        found = {}
        for status in statuses:
            for post in self.collect(status):
                require(post["id"] not in found, "Post appears in multiple statuses")
                found[post["id"]] = post
        require(set(found) == set(IDS), "A required post is missing from all-status preflight")
        require(all(post["author"] == me.get("id") or me.get("capabilities", {}).get("edit_others_posts") is True
                    for post in found.values()), "Managed account cannot edit another author's post")
        for tag, name in TAG_NAMES.items():
            term = self.read(f"tags/{tag}")
            require(term.get("id") == tag and term.get("name") == name,
                    "Erroneous tag identity changed")
        plan = {"manifest_sha256": digest(data),
                "worker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "posts": []}
        for p in data["posts"]:
            post = found[p["id"]]
            require(public_snapshot(post) == p["expected_public"],
                    f"Post {p['id']} differs from audited public baseline; re-review")
            require(post["status"] == "publish", "Correction is limited to the original published post")
            before = edit_snapshot(post)
            require(edit_snapshot(self.read(f"posts/{p['id']}", params={"context": "edit"})) == before,
                    "Post changed during preflight")
            source = self.public_get(p["source"]["url"])
            soup = BeautifulSoup(source.text, "html.parser")
            body = soup.select_one("#storyPageContentBody, .sidearm-story-template-text")
            require(body is not None, "Original report body unavailable")
            text = plain(str(body))
            require(hashlib.sha256(text.encode()).hexdigest() == p["source"]["article_sha256"],
                    f"Original report for {p['id']} changed; re-check facts")
            for token in p["source"].get("required_page_text", []):
                require(token in plain(str(soup)), "Official scoreboard/statistics changed; re-check facts")
            (self.output / f"source-{p['id']}.txt").write_text(text + "\n")
            plan["posts"].append({"id": p["id"], "before": before, "patch": p["patch"],
                                  "source": p["source"]})
        media_found = []
        for status in self.schema("media"):
            media_found.extend(self.collect(status, "media", (24509,)))
        require(len(media_found) == 1 and media_found[0]["status"] == "inherit",
                "Reviewed Jones attachment absent, duplicated or not inherited")
        media = media_found[0]
        require(media_snapshot(media) == data["media"]["expected_public"], "Jones media differs from audited baseline")
        require(found[24510]["featured_media"] == 24509 and media.get("post") in (None, 0, 24510),
                "Reviewed attachment is not the existing Jones featured image")
        require(media["author"] == me.get("id") or me.get("capabilities", {}).get("edit_others_posts") is True,
                "Managed account cannot edit another author's media")
        image_sha = hashlib.sha256(self.public_get(media["source_url"]).content).hexdigest()
        plan["media"] = {"id": 24509, "before": media_snapshot(media, edit=True), "patch": data["media"]["patch"],
                         "file_sha256": image_sha}
        self.save("preflight.json", {"all_statuses_checked": True, **self.audit})
        self.save("plan.json", plan)
        self.save("review.json", {"plan_sha256": digest(plan), "manifest_sha256": digest(data),
                   "run_id": os.environ.get("GITHUB_RUN_ID", ""),
                   "commit": os.environ.get("GITHUB_SHA", ""), "writes": 0})
        return plan

    def validate_after(self, post, item):
        before, patch = item["before"], item["patch"]
        require(all(post.get(k) == before[k] for k in PRESERVED),
                "Preserved identity/status/URL/date/media/taxonomy changed")
        require(post.get("tags") == patch.get("tags", before["tags"]), "Post tags differ from review")
        require(post.get("meta") == before["meta"], "Unrelated SEO or metadata changed")
        for field in ("title", "excerpt", "content"):
            require(post.get(field, {}).get("raw") == patch[field], f"Corrected {field} not confirmed")

    def verify_public(self, item):
        post = self.public_get(f"{SITE}/wp-json/wp/v2/posts/{item['id']}").json()
        before, patch = item["before"], item["patch"]
        require(all(post.get(k) == before[k] for k in PRESERVED), "Public post identity changed")
        require(post.get("tags") == patch.get("tags", before["tags"]), "Public tags differ")
        for field in ("title", "excerpt", "content"):
            require(plain(post.get(field, {}).get("rendered", "")) == plain(patch[field]),
                    f"Public {field} not confirmed")
        require(post.get("meta") == before["meta"], "Public SEO overrides changed")
        soup = BeautifulSoup(self.public_get(before["link"]).text, "html.parser")
        h1 = soup.find("h1")
        desc = soup.find("meta", attrs={"name": "description"})
        canonical = soup.find("link", rel="canonical")
        require(h1 is not None and typography(plain(str(h1))) == typography(patch["title"]), "Canonical page H1 not confirmed")
        require(desc is not None and desc.get("content") == patch["excerpt"], "Page SEO description not confirmed")
        require(soup.title is not None and typography(patch["title"]) in typography(plain(str(soup.title))), "Page SEO title not confirmed")
        for name in ("dc.description", "og:description", "twitter:description"):
            tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
            require(tag is not None and typography(tag.get("content", "")) == typography(patch["excerpt"]),
                    f"Generated {name} not confirmed")
        for name in ("og:title", "twitter:title"):
            tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
            require(tag is not None and typography(patch["title"]) in typography(tag.get("content", "")),
                    f"Generated {name} not confirmed")
        require(canonical is not None and canonical.get("href", "").rstrip("/") == before["link"].rstrip("/"),
                "Canonical URL not confirmed")
        article = soup.select_one(f"#post-{item['id']}")
        require(article is not None and plain(patch["content"]) in plain(str(article)),
                "Canonical page corrected body not confirmed")
        return {"id": post["id"], "link": post["link"], "featured_media": post["featured_media"],
                "same_identity_dates_media": True, "public_body_title_excerpt_seo_social_canonical": True}

    def apply(self, plan, control):
        require(control.get("apply") is True and control.get("parent_reviewed") is True
                and control.get("parent_priority_released") is True, "Parent review/priority gate is not complete")
        require(control.get("approved_plan_sha256") == digest(plan), "Fresh plan differs from parent-reviewed dry-run")
        require(re.fullmatch(r"[0-9]+", control.get("preflight_run_id", "")) is not None
                and re.fullmatch(r"[0-9a-f]{40}", control.get("preflight_commit", "")) is not None,
                "Parent-reviewed preflight provenance missing")
        require(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_RUN_ATTEMPT") == "1",
                "Mutation only on first managed Actions attempt")
        require(os.environ.get("GITHUB_REF") == "refs/heads/main", "Mutation only on main")
        require(not (ROOT / "corrections/completion-receipt.json").exists(), "One-shot mutations retired")
        # Confirm every before snapshot again before the first mutation.
        for item in plan["posts"]:
            require(edit_snapshot(self.read(f"posts/{item['id']}", params={"context": "edit"})) == item["before"],
                    "A post changed since full preflight; no writes")
        require(media_snapshot(self.read("media/24509", params={"context": "edit"}), edit=True) == plan["media"]["before"],
                "Jones media changed since full preflight; no writes")
        receipts = []
        for item in plan["posts"]:
            endpoint = f"posts/{item['id']}"
            require(edit_snapshot(self.read(endpoint, params={"context": "edit"})) == item["before"],
                    "Post changed immediately before correction")
            action = {"method": "POST", "endpoint": endpoint, "patch_sha256": digest(item["patch"]),
                      "state": "attempted"}
            self.actions.append(action)
            self.save("actions.json", self.actions)
            try:
                self.request("POST", endpoint, json=item["patch"])
            except CorrectionError:
                action["state"] = "uncertain_or_failed"
                self.save("actions.json", self.actions)
                # Never blindly retry; preserve a read-only observation of the same ID.
                try:
                    self.save(f"uncertain-{item['id']}.json", edit_snapshot(
                        self.read(endpoint, params={"context": "edit"})))
                except CorrectionError:
                    pass
                raise
            observed = self.read(endpoint, params={"context": "edit"})
            self.validate_after(observed, item)
            action["state"] = "confirmed"
            self.save("actions.json", self.actions)
            self.save(f"after-{item['id']}.json", edit_snapshot(observed))
            receipts.append(self.verify_public(item))
            self.save("partial-receipt.json", receipts)
        media_receipt = self.correct_media(plan["media"])
        surfaces = self.verify_surfaces(plan)
        receipt = {"plan_sha256": digest(plan), "run_id": os.environ["GITHUB_RUN_ID"],
                   "commit": os.environ["GITHUB_SHA"], "posts": receipts,
                   "media": media_receipt,
                   "surfaces": surfaces,
                   "retire_workflow_and_commit_receipt": True}
        self.save("completion-receipt.json", receipt)
        return receipt

    def correct_media(self, item):
        endpoint = "media/24509"
        require(media_snapshot(self.read(endpoint, params={"context": "edit"}), edit=True) == item["before"],
                "Jones media changed before alt correction")
        action = {"method": "POST", "endpoint": endpoint, "state": "attempted",
                  "patch_sha256": digest(item["patch"])}
        self.actions.append(action)
        self.save("actions.json", self.actions)
        try:
            self.request("POST", endpoint, json=item["patch"])
        except CorrectionError:
            action["state"] = "uncertain_or_failed"
            self.save("actions.json", self.actions)
            try:
                self.save("uncertain-media-24509.json", media_snapshot(self.read(endpoint, params={"context": "edit"}), edit=True))
            except CorrectionError:
                pass
            raise
        observed = media_snapshot(self.read(endpoint, params={"context": "edit"}), edit=True)
        require(observed["alt_text"] == item["patch"]["alt_text"], "Jones media alt not confirmed")
        require(all(observed[k] == v for k, v in item["before"].items()
                    if k not in ("modified", "modified_gmt", "alt_text")), "Unrelated media field changed")
        public_media = media_snapshot(self.public_get(f"{SITE}/wp-json/wp/v2/{endpoint}").json())
        require(public_media["alt_text"] == item["patch"]["alt_text"] and
                all(public_media[k] == v for k, v in item["before"].items()
                    if k not in ("modified", "modified_gmt", "alt_text") and not k.endswith("_raw")),
                "Public media identity or alt not confirmed")
        require(hashlib.sha256(self.public_get(observed["source_url"]).content).hexdigest() == item["file_sha256"],
                "Media file bytes changed")
        action["state"] = "confirmed"
        self.save("actions.json", self.actions)
        self.save("after-media-24509.json", observed)
        return {"id": 24509, "alt_text": observed["alt_text"], "same_file_url_ownership": True}

    def verify_surfaces(self, plan):
        from xml.etree import ElementTree
        home = BeautifulSoup(self.public_get(SITE + "/").text, "html.parser")
        feed = ElementTree.fromstring(self.public_get(SITE + "/feed/").content)
        items = {node.findtext("link", "").rstrip("/"): node for node in feed.findall("./channel/item")}
        result = []
        for item in plan["posts"]:
            link, title = item["before"]["link"], item["patch"]["title"]
            anchors = [a for a in home.find_all("a", href=link) if plain(str(a))]
            require(all(typography(plain(str(a))) == typography(title) for a in anchors),
                    "Homepage card headline is stale")
            node = items.get(link.rstrip("/"))
            if node is not None:
                require(typography(node.findtext("title", "")) == typography(title), "Feed headline is stale")
                description = node.findtext("description", "")
                require(typography(plain(description)) == typography(item["patch"]["excerpt"]), "Feed description is stale")
            result.append({"id": item["id"], "homepage_title_verified_if_present": bool(anchors),
                           "feed_title_excerpt_verified_if_present": node is not None})
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output", default="correction-output")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    worker = None
    try:
        data = load_manifest(ROOT / "corrections/2026-10-13.json")
        if not args.offline:
            require(not (ROOT / "corrections/completion-receipt.json").exists(), "One-shot mutations retired")
        if args.offline:
            (output / "result.json").write_text(json.dumps({"offline_valid": True,
                 "manifest_sha256": digest(data), "post_ids": IDS, "writes": 0}, indent=2) + "\n")
            return
        control = json.loads((ROOT / "corrections/control.json").read_text())
        require(os.environ.get("GITHUB_ACTIONS") == "true", "Credentials only in managed Actions")
        require(os.environ.get("WORDPRESS_BASE_URL", "").rstrip("/") == SITE, "Managed site mismatch")
        auth, public = requests.Session(), requests.Session()
        # Match the anonymous client used for the independent source review;
        # Sidearm returns a false 404 to the default Python requests header.
        public.headers.update({"User-Agent": "curl/8.7.1"})
        require(os.environ.get("WORDPRESS_USERNAME") and os.environ.get("WORDPRESS_APP_PASSWORD"),
                "Existing managed credentials unavailable")
        auth.auth = (os.environ["WORDPRESS_USERNAME"], os.environ["WORDPRESS_APP_PASSWORD"])
        auth.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        worker = Worker(auth, public, output)
        plan = worker.preflight(data)
        if control.get("apply") is True:
            worker.apply(plan, control)
        worker.save("result.json", {"ok": True, "dry_run": control.get("apply") is not True,
                                   "plan_sha256": digest(plan), "writes": len(worker.actions)})
    except (CorrectionError, ValueError, KeyError, TypeError):
        # Never emit exception repr, response bodies or credential-bearing URLs.
        import sys
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, CorrectionError) else "Invalid correction data or REST response"
        (output / "result.json").write_text(json.dumps({"ok": False, "error": message,
                         "writes_attempted": len(worker.actions) if worker else 0}, indent=2) + "\n")
        print(message)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
