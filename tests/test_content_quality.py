import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from rss_to_wp import cli
from rss_to_wp.config import FeedConfig
from rss_to_wp.content_quality import article_problem, content_problem, source_hold_problem, source_problem
from rss_to_wp.feeds import parser
from rss_to_wp.rewriter.openai_client import OpenAIRewriter


FOOTER = ("About Press Copyright Contact us Creators Advertise Developers Terms Privacy "
          "Policy & Safety How YouTube works Test new features NFL Sunday Ticket © 2026 Google LLC")
SHORT = "Blue Mountain Christian beat William Carey 3-1 in volleyball Thursday."
SOURCE = ("Blue Mountain Christian volleyball took down William Carey in four sets. "
          "The Volley Toppers earned the 25-19, 19-25, 25-15, 25-20 victory. "
          "The Crusaders answered in the second with a 25-19 victory. "
          "Salice Speed and Marissa Gerleman led the BMCU attack with 12 kills apiece.")
TITLE = "Volley Toppers take down William Carey in four sets"


def article(body=SHORT, headline="BMCU wins in four sets", **extra):
    return {"headline": headline, "body": f"<p>{body}</p>", **extra}


@pytest.fixture
def rewriter(monkeypatch):
    client = OpenAIRewriter(api_key="offline-test")
    monkeypatch.setattr(client, "_rate_limit", lambda: None)
    client.client = Mock()
    return client


def completion(payload, finish_reason="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=json.dumps(payload)), finish_reason=finish_reason)])


@pytest.mark.parametrize("bad", ["", " \n ", "<p>&nbsp;</p>", "<img alt='Game photo'>",
    "<iframe src='video'></iframe>", "<script>Sports report</script>", FOOTER,
    "No content available for Football vs. Alabama Hype Video",
    "The provided text contains only a YouTube footer and no actual story content.",
    "Unable to extract the article from the source.", "Just a moment... Verify you are human.",
    "Access denied", "Service unavailable", "Page not found", "Coming soon",
    "Content unavailable", "Cannot access the source",
    "Privacy Policy Terms of Service All rights reserved", "Ad Blocker Detected"])
def test_known_non_articles_are_rejected(bad):
    assert content_problem(bad)


@pytest.mark.parametrize("good", [SHORT, "Rebels win 3-1.",
    "State keeping an internal focus as outside excitement builds.",
    "Mississippi State posted an Alabama hype video on YouTube Friday.",
    "The Bulldogs host Alabama at 11 a.m. Saturday on ESPN."])
def test_short_and_video_related_real_updates_are_retained(good):
    assert content_problem(good) is None
    assert article_problem(article(good)) is None


@pytest.mark.parametrize("payload", [None, [], {}, {"headline": None, "body": "Text"},
    {"headline": "Title", "body": []}, {"headline": "Title", "body": ""},
    article("<img src='photo'>"), article(FOOTER), article(excerpt=FOOTER),
    article(tags="Volleyball"), article(tags=[None])])
@pytest.mark.parametrize("fenced", [False, True])
def test_all_json_paths_reject_invalid_outputs(rewriter, payload, fenced):
    response = json.dumps(payload)
    if fenced:
        response = "```json\n" + response + "\n```"
    assert rewriter._parse_response(response) is None


def test_missing_model_message_fails_closed(rewriter):
    assert rewriter._parse_response(None) is None


@pytest.mark.parametrize("fenced", [False, True])
def test_valid_short_json_is_normalized(rewriter, fenced):
    text = json.dumps(article())
    if fenced:
        text = "```json\n" + text + "\n```"
    assert rewriter._parse_response(text) == {**article(), "excerpt": "", "tags": []}


def test_empty_source_never_calls_model(rewriter):
    assert rewriter.rewrite(FOOTER, "Hype video") is None
    rewriter.client.chat.completions.create.assert_not_called()


def test_valid_short_source_calls_unchanged_model(rewriter):
    rewriter.client.chat.completions.create.return_value = completion(article())
    assert rewriter.rewrite(SHORT, TITLE)
    assert rewriter.client.chat.completions.create.call_args.kwargs["model"] == rewriter.model


def test_final_title_override_is_checked(rewriter):
    rewriter.client.chat.completions.create.return_value = completion(article())
    assert rewriter.rewrite(SHORT, "No content available", use_original_title=True) is None


def test_truncated_model_completion_is_rejected_even_if_json_is_valid(rewriter):
    rewriter.client.chat.completions.create.return_value = completion(article(), "length")
    assert rewriter.rewrite(SHORT, TITLE) is None


def test_fallback_model_passes_same_content_gate(rewriter):
    rewriter.client.chat.completions.create.side_effect = [RuntimeError("offline API failure"),
                                                         completion(article(FOOTER))]
    assert rewriter.rewrite(SHORT, TITLE) is None
    assert rewriter.client.chat.completions.create.call_count == 2
    assert rewriter.client.chat.completions.create.call_args.kwargs["model"] == rewriter.fallback_model


@pytest.mark.parametrize("result", [
    article(headline="BMCU sweeps William Carey in four sets"),
    article(headline="BMCU swept William Carey"),
    article("BMCU won 3-0 against William Carey."),
    article("BMCU won in five sets against William Carey."),
    article("BMCU won 25-19, 19-25, 25-22, 25-20."),
    article("BMCU won 25-19, 25-15, 19-25, 25-20."),
    article("BMCU won the first two sets before winning 3-1."),
])
def test_volleyball_source_contradictions_are_blocked(result):
    assert article_problem(result, SOURCE, TITLE)


@pytest.mark.parametrize("result", [article(),
    article("BMCU won 25-19, 19-25, 25-15, 25-20 against William Carey."),
    article("William Carey lost 19-25, 25-19, 15-25, 20-25 against BMCU."),
    article("BMCU won the opening set before dropping the second."),
    article("BMCU won 3-1. It swept its previous opponent last week."),
])
def test_source_supported_volleyball_updates_pass(result):
    # Previous-match claims belong in a subsequent paragraph, not the match lead.
    if "previous" in result["body"]:
        result["body"] = "<p>BMCU won 3-1.</p><p>It swept its previous opponent last week.</p>"
    assert article_problem(result, SOURCE, TITLE) is None


def test_four_set_rss_summary_alone_rejects_sweep():
    assert article_problem(article(headline="BMCU sweeps Carey in four sets"), SHORT, TITLE)


def test_other_sports_are_not_mistaken_for_volleyball():
    assert article_problem(article("BMCU won 3-0.", headline="Toppers sweep soccer games"),
                           "BMCU soccer won 3-1.", "Soccer wins") is None


def test_volleyball_season_record_is_not_treated_as_set_score():
    assert article_problem(article("BMCU won in four sets. Its record improved to 25-10."),
                           SOURCE, TITLE) is None


def test_volleyball_small_season_record_is_not_a_match_result():
    assert article_problem(article("BMCU won in four sets. Its season record improved to 3-0."),
                           SOURCE, TITLE) is None


def test_source_self_contradiction_is_held_before_rewriting(rewriter):
    bad = SOURCE + " BMCU won the first two sets."
    assert source_problem(bad, TITLE)
    assert rewriter.rewrite(bad, TITLE) is None
    rewriter.client.chat.completions.create.assert_not_called()


@pytest.mark.parametrize("url", [
    "https://bmcusports.com/news/2026/10/2/womens-volleyball-volley-toppers-take-down-william-carey-in-four-sets.aspx",
    "https://www.bmcusports.com/news/2026/10/2/womens-volleyball-volley-toppers-take-down-william-carey-in-four-sets.aspx?print=true",
    "https://alcornsports.com/news/2026/10/2/womens-volleyball-alcorn-state-drops-three-set-match-to-texas-southern.aspx#story",
])
def test_confirmed_source_conflicts_are_held_without_any_fetch_or_write(monkeypatch, url):
    assert source_hold_problem(url)
    fetch, wp, rewrite = Mock(), Mock(), Mock()
    monkeypatch.setattr(cli, "get_entry_content", fetch)
    assert cli.process_entry({"title": TITLE, "link": url},
        FeedConfig(name="Volleyball", url="https://example.com/feed"),
        Mock(), rewrite, wp, False, Mock()) is None
    assert not wp.mock_calls
    fetch.assert_not_called()
    rewrite.rewrite.assert_not_called()


def test_source_holds_do_not_block_another_game():
    assert source_hold_problem("https://bmcusports.com/news/2026/10/3/womens-volleyball-another-game.aspx") is None


def response(html, url="https://example.com/story"):
    return SimpleNamespace(content=html.encode(), url=url, headers={}, raise_for_status=Mock())


def test_youtube_redirect_is_not_scraped(monkeypatch):
    monkeypatch.setattr(parser.requests, "get", Mock(return_value=response(
        f"<body><main>{FOOTER}</main></body>", "https://www.youtube.com/watch?v=example")))
    assert parser.scrape_article_content("https://hailstate.com/news/hype-video") is None


def test_whole_body_navigation_cannot_be_promoted_to_article(monkeypatch):
    monkeypatch.setattr(parser.requests, "get", Mock(return_value=response(
        "<body>" + "Teams Schedules Rosters Tickets Privacy Terms " * 20 + "</body>")))
    assert parser.scrape_article_content("https://example.com/story") is None


def test_empty_story_body_does_not_fall_through_to_article_chrome(monkeypatch):
    monkeypatch.setattr(parser.requests, "get", Mock(return_value=response(
        f"<article>Related stories <div class='sidearm-story-template-text'><iframe/></div>{SHORT}</article>")))
    assert parser.scrape_article_content("https://example.com/story") is None


def test_scraped_short_story_is_kept(monkeypatch):
    monkeypatch.setattr(parser.requests, "get", Mock(return_value=response(
        f"<body><h1>{TITLE}</h1><div class='sidearm-story-template-text'>{SHORT}</div></body>")))
    assert parser.scrape_article_content("https://example.com/story") == SHORT


def test_boilerplate_scrape_does_not_replace_valid_short_rss(monkeypatch):
    monkeypatch.setattr(parser, "scrape_article_content", Mock(return_value=FOOTER * 4))
    assert parser.get_entry_content({"summary": SHORT, "link": "https://example.com/story"}) == SHORT


def test_image_only_hype_video_stays_empty(monkeypatch):
    monkeypatch.setattr(parser, "scrape_article_content", Mock(return_value=None))
    content = parser.get_entry_content({"summary": "<img alt='Alabama hype'><br><br>",
                                       "link": "https://hailstate.com/news/hype-video"})
    assert content_problem(content) == "empty_content"


@pytest.mark.parametrize("xml", [
    '<rss version="2.0"><channel><title>BMCU Archery</title><link>https://bmcusports.com</link><description>News</description></channel></rss>',
    '<feed xmlns="http://www.w3.org/2005/Atom"><title>Archery</title></feed>',
])
def test_valid_empty_feeds_are_distinct_from_errors(monkeypatch, xml):
    monkeypatch.setattr(parser.requests, "get", Mock(return_value=response(xml)))
    feed = parser.parse_feed("https://example.com/feed")
    assert feed is not None and feed.entries == []
    monkeypatch.setattr(cli, "parse_feed", lambda _: feed)
    assert cli.process_feed(FeedConfig(name="Archery", url="https://example.com/feed"),
                            Mock(), Mock(), Mock(), Mock(), False, 48, Mock()) == (0, 0, 0)


@pytest.mark.parametrize("xml", ["", "<html><body>Service unavailable</body></html>",
                                '<rss version="2.0"><channel>'])
def test_invalid_200_responses_are_errors(monkeypatch, xml):
    monkeypatch.setattr(parser.requests, "get", Mock(return_value=response(xml)))
    assert parser.parse_feed("https://example.com/feed") is None


def test_feed_relative_links_keep_the_final_http_base(monkeypatch):
    xml = ('<rss version="2.0"><channel><title>Sports</title><link>https://example.com/</link>'
           '<description>News</description><item><title>Rebels win</title>'
           '<link>news/recap</link><description>Rebels win 3-1.</description>'
           '</item></channel></rss>')
    monkeypatch.setattr(parser.requests, "get", Mock(return_value=response(
        xml, "https://example.com/athletics/feed")))
    feed = parser.parse_feed("https://example.com/old-feed")
    assert feed.entries[0]["link"] == "https://example.com/athletics/news/recap"


def test_valid_empty_xml_with_wrong_mime_type_remains_a_feed(monkeypatch):
    result = response('<rss version="2.0"><channel><title>Archery</title></channel></rss>')
    result.headers = {"Content-Type": "text/html"}
    monkeypatch.setattr(parser.requests, "get", Mock(return_value=result))
    feed = parser.parse_feed("https://example.com/feed")
    assert feed is not None and feed.entries == []


@pytest.mark.parametrize("failure", [requests.HTTPError("404"), requests.HTTPError("503"),
                                     requests.Timeout("timeout")])
def test_feed_fetch_errors_remain_errors(monkeypatch, failure):
    monkeypatch.setattr(parser.requests, "get", Mock(side_effect=failure))
    assert parser.parse_feed("https://example.com/feed") is None
    monkeypatch.setattr(cli, "parse_feed", lambda _: None)
    assert cli.process_feed(FeedConfig(name="Archery", url="https://example.com/feed"),
                            Mock(), Mock(), Mock(), Mock(), False, 48, Mock()) == (0, 0, 1)


@pytest.mark.parametrize("source,result", [(FOOTER, article()), (SHORT, article(FOOTER)),
    (SHORT, {"headline": "Title", "body": ""}),
    (SOURCE, article(headline="BMCU sweeps Carey in four sets"))])
def test_rejected_entries_perform_no_wp_or_image_writes(monkeypatch, source, result):
    monkeypatch.setattr(cli, "get_entry_content", lambda _: source)
    image = Mock()
    monkeypatch.setattr(cli, "find_rss_image", image)
    wp, rewrite = Mock(), Mock()
    rewrite.rewrite.return_value = result
    outcome = cli.process_entry({"title": TITLE},
        FeedConfig(name="BMCU Volleyball", url="https://example.com/feed"),
        Mock(), rewrite, wp, False, Mock())
    assert outcome is None
    assert not wp.mock_calls
    image.assert_not_called()
    if source == FOOTER:
        rewrite.rewrite.assert_not_called()


def test_valid_short_entry_reaches_publisher(monkeypatch):
    monkeypatch.setattr(cli, "get_entry_content", lambda _: SHORT)
    for name in ("find_rss_image", "scrape_image_from_url", "find_fallback_image"):
        monkeypatch.setattr(cli, name, Mock(return_value=None))
    wp, rewrite = Mock(), Mock()
    rewrite.rewrite.return_value = article()
    wp.create_post.return_value = {"id": 1, "link": "https://example.com/valid"}
    outcome = cli.process_entry({"title": TITLE},
        FeedConfig(name="BMCU Volleyball", url="https://example.com/feed"),
        Mock(), rewrite, wp, False, Mock())
    assert outcome["id"] == 1
    assert wp.create_post.call_args.kwargs["content"] == article()["body"]
