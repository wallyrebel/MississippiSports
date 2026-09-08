from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pendulum
import pytest

from rss_to_wp import cli
from rss_to_wp.config import FeedConfig, load_feeds_config
from rss_to_wp.wordpress.client import WordPressClient


@pytest.fixture
def settings():
    return SimpleNamespace(timezone="UTC", pexels_api_key=None, unsplash_access_key=None)


@pytest.fixture
def no_images(monkeypatch):
    for name in ("find_rss_image", "scrape_image_from_url", "find_fallback_image"):
        monkeypatch.setattr(cli, name, Mock(return_value=None))


def test_all_configured_feeds_have_a_school_and_college_section():
    feeds = load_feeds_config(Path(__file__).parents[1] / "feeds.yaml").feeds
    assert len(feeds) == 253
    schools = set()
    for feed in feeds:
        assert feed.default_category == "Sports"
        assert "College" in feed.category_names
        school = set(feed.category_names) - {"Sports", "College", "Juco News"}
        assert len(school) == 1, feed.name
        schools.update(school)
    assert len(schools) == 18
    by_name = {feed.name: feed for feed in feeds}
    assert by_name["Ole Miss Football"].category_names == ["Sports", "College", "Ole Miss"]
    assert "Mississippi State" in by_name["MSU Football"].category_names
    assert "Jackson State" in by_name["JSU Football"].category_names
    assert "Juco News" in by_name["Hinds Football"].category_names


def test_legacy_config_remains_valid_and_category_names_are_deduplicated():
    feed = FeedConfig(name="Example", url="https://example.com/feed", category=" Sports ",
                      additional_categories=["Sports", " College ", "", "College"])
    assert feed.category_names == ["Sports", "College"]
    assert FeedConfig(name="Legacy", url="https://example.com/feed", category="Sports").category_names == ["Sports"]


@pytest.mark.parametrize("limit", [0, -1])
def test_invalid_run_budget_is_rejected(limit):
    with pytest.raises(ValueError):
        FeedConfig(name="Example", url="https://example.com/feed", max_per_run=limit)


def test_rewritten_story_sends_school_categories_independently_of_ai_tags(settings, no_images):
    feed = FeedConfig(name="Ole Miss Football", url="https://olemisssports.com/rss?path=football",
                      category="Sports", additional_categories=["College", "Ole Miss"])
    wp = Mock()
    wp.get_or_create_category.side_effect = {"Sports": 12, "College": 7, "Ole Miss": 4}.get
    rewriter = Mock()
    rewriter.rewrite.return_value = {"headline": "Rebels win", "body": "<p>Report.</p>",
                                   "excerpt": "A game report", "tags": ["Football"]}
    cli.process_entry({"title": "Original", "summary": "A report", "link": "https://example.com/story"},
                      feed, settings, rewriter, wp, False, Mock())
    payload = wp.create_post.call_args.kwargs
    assert payload["category_ids"] == [12, 7, 4]
    assert payload["source_url"] == "https://example.com/story"
    assert payload["excerpt"] == "A game report"


def test_category_lookup_failure_does_not_publish_an_uncategorized_story(settings, no_images):
    feed = FeedConfig(name="Example", url="https://example.com/feed", category="Sports",
                      additional_categories=["College"])
    wp = Mock()
    wp.get_or_create_category.side_effect = [12, None]
    rewriter = Mock()
    rewriter.rewrite.return_value = {"headline": "Report", "body": "<p>Report.</p>"}
    result = cli.process_entry({"title": "Original", "summary": "A report"}, feed, settings,
                               rewriter, wp, False, Mock())
    assert result is None
    wp.create_post.assert_not_called()


def test_dry_run_reports_categories_without_wordpress_writes(settings, no_images):
    feed = FeedConfig(name="Example", url="https://example.com/feed", category="Sports",
                      additional_categories=["College", "Ole Miss"])
    wp, logger, rewriter = Mock(), Mock(), Mock()
    rewriter.rewrite.return_value = {"headline": "Report", "body": "<p>Report.</p>"}
    cli.process_entry({"title": "Original", "summary": "A report"}, feed, settings,
                      rewriter, wp, True, logger)
    assert not wp.mock_calls
    preview = [call for call in logger.info.call_args_list if call.args[0] == "dry_run_would_publish"][0]
    assert preview.kwargs["categories"] == ["Sports", "College", "Ole Miss"]


def test_wordpress_payload_supports_multiple_and_legacy_categories(monkeypatch):
    wp = WordPressClient("https://example.com", "test", "test")
    monkeypatch.setattr(wp, "_rate_limit", lambda: None)
    wp.session = Mock()
    wp.session.post.return_value.json.return_value = {"id": 123}
    wp.create_post("Title", "<p>Body</p>", category_id=12, category_ids=[12, 7, 4])
    assert wp.session.post.call_args.kwargs["json"]["categories"] == [12, 7, 4]
    wp.create_post("Legacy", "<p>Body</p>", category_id=12)
    assert wp.session.post.call_args.kwargs["json"]["categories"] == [12]


@pytest.mark.parametrize("publish_succeeds", [True, False])
def test_processed_front_of_feed_does_not_starve_unseen_entries(monkeypatch, settings, publish_succeeds):
    entries = [{"id": str(i), "title": f"Story {i}", "link": f"https://example.com/{i}",
                "published": pendulum.now("UTC").subtract(minutes=i).to_iso8601_string()}
               for i in range(12)]
    monkeypatch.setattr(cli, "parse_feed", lambda _: SimpleNamespace(entries=entries))
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    process = Mock(return_value={"id": 10, "link": "https://example.com/published"} if publish_succeeds else None)
    monkeypatch.setattr(cli, "process_entry", process)
    dedupe = Mock()
    dedupe.is_processed.side_effect = lambda key: int(key.split(":", 1)[1]) < 5
    feed = FeedConfig(name="Busy school", url="https://example.com/feed", max_per_run=5)
    processed, skipped, errors = cli.process_feed(feed, settings, dedupe, Mock(), Mock(), False, 48, Mock())
    assert [call.kwargs["entry"]["id"] for call in process.call_args_list] == [str(i) for i in range(5, 10)]
    assert skipped == 5
    assert (processed, errors) == ((5, 0) if publish_succeeds else (0, 5))


def test_disabled_feed_is_not_fetched(monkeypatch, settings):
    parse = Mock()
    monkeypatch.setattr(cli, "parse_feed", parse)
    result = cli.process_feed(FeedConfig(name="Disabled", url="https://example.com/feed", enabled=False),
                              settings, Mock(), Mock(), Mock(), False, 48, Mock())
    assert result == (0, 0, 0)
    parse.assert_not_called()
