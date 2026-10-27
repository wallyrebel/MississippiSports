import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from rss_to_wp.feeds import parser
from rss_to_wp.rewriter.depth import DepthPolicy, article_depth_problem, numeric_details
from rss_to_wp.rewriter.openai_client import OpenAIRewriter

CASES = json.loads((Path(__file__).parent / 'fixtures/athletics_depth_cases.json').read_text())


def response(html, host='careyathletics.com'):
    return SimpleNamespace(content=html.encode(), url=f'https://{host}/news/story',
                           raise_for_status=Mock())


@pytest.mark.parametrize('case', CASES, ids=lambda c:str(c['post_id']))
def test_diagnosed_six_athletics_stories_survive_structural_forms(monkeypatch, case):
    html = ("<form><nav>Schedule tickets newsletter</nav><main><article>"
            f"<div class='{case['selector']}'><aside>Wrong next game 999-888</aside>"
            "<h2>Game report</h2><form><input value='tracking'><button>Subscribe</button>"
            f"{case['story']}</form><div class='advertisement'>Buy tickets</div>"
            "<div class='print-friendly-story-button'>Print Friendly Version</div></div>"
            "Related story with different score 99-98</article></main></form>")
    monkeypatch.setattr(parser.requests,'get',Mock(return_value=response(html,case['host'])))
    result=parser.scrape_article_content(f"https://{case['host']}/news/story")
    for fact in case['required']: assert fact in result
    for noise in ['Subscribe','Buy tickets','999-888','99-98','Print Friendly']: assert noise not in result
    assert 'Game report' in result


def test_long_athletics_teaser_uses_full_story_without_expanding_unrelated_hosts(monkeypatch):
    teaser='A factual teaser sentence about the scheduled game. '*15
    full=teaser+'The official report names the leading scorer and explains the winning play.'
    scrape=Mock(return_value=full);monkeypatch.setattr(parser,'scrape_article_content',scrape)
    assert parser.get_entry_content({'summary':teaser,'link':'https://sports.hindscc.edu/news/story'})==full
    scrape.reset_mock()
    assert parser.get_entry_content({'summary':teaser,'link':'https://other.example/story'})==teaser
    scrape.assert_not_called()


def test_modern_sidearm_story_id_excludes_page_chrome(monkeypatch):
    html='<form><nav>Menu</nav><div id="storyPageContentBody"><p>Hubbard was named to the watch list.</p></div></form>'
    monkeypatch.setattr(parser.requests,'get',Mock(return_value=response(html)))
    assert parser.scrape_article_content('https://careyathletics.com/story')=='Hubbard was named to the watch list.'


def test_authorized_source_cannot_redirect_to_unrelated_article(monkeypatch):
    monkeypatch.setattr(parser.requests,'get',Mock(return_value=response('<article>Other story</article>','other.example')))
    assert parser.scrape_article_content('https://careyathletics.com/story') is None


def test_substantive_source_cannot_be_reduced_to_one_sentence():
    rich=CASES[3]['story']
    assert article_depth_problem({'body':'<p>Southern Virginia defeated Belhaven 23-19.</p>'},rich)=='substantive_source_undercovered'
    assert 'meaningful paragraphs' in DepthPolicy().instruction(rich)


def test_thin_award_source_does_not_require_padding():
    thin=CASES[-1]['story']
    brief="MUW's Reagan Shinn earned Owl of the Week recognition for October 19-25. Her seventh goal came in the 3-2 defeat by Westminster. She has one match remaining and is tied for third in school history for season goals."
    assert article_depth_problem({'body':f'<p>{brief}</p>'},thin) is None
    assert 'Do not stretch' in DepthPolicy().instruction(thin)
    padded={'body':'<p>'+thin+' '+('The program continues its important work within the community. '*8)+'</p>'}
    assert article_depth_problem(padded,thin)=='thin_source_overexpanded'


def test_rich_report_keeps_supported_facts_and_rejects_padding_and_invented_statistics():
    source=CASES[3]['story'];sentences=[s.strip('. ') for s in reversed(source.split('. '))]
    result={'body':''.join('<p>'+'. '.join(sentences[i:i+4])+'.</p>' for i in range(0,len(sentences),4))}
    assert article_depth_problem(result,source) is None
    invented={**result,'body':result['body']+'<p>The team scored 999 points.</p>'}
    assert article_depth_problem(invented,source)=='unsupported_numeric_detail'
    repeated={**result,'body':result['body']+f'<p>{sentences[0]}.</p>'}
    assert article_depth_problem(repeated,source)=='repeated_sentence_padding'


def test_extended_copied_source_passage_is_held():
    source=CASES[3]['story'];chunks=source.split();body=''.join('<p>'+' '.join(chunks[i:i+35])+'</p>' for i in range(0,len(chunks),35))
    assert article_depth_problem({'body':body},source)=='near_verbatim_source_passage'


def test_numeric_guard_accepts_ap_number_and_ordinal_formatting():
    assert numeric_details('seventh goal, 7th goal, seven goals')=={'7'}


def test_over_budget_source_is_held_without_silent_truncation_or_model_call(monkeypatch):
    r=OpenAIRewriter('offline-test',max_input_chars=2000);r.client=Mock()
    monkeypatch.setattr(r,'_rate_limit',lambda:None)
    assert r.rewrite('A source fact. '*200,'Game report') is None
    r.client.chat.completions.create.assert_not_called()


def test_full_source_facts_and_depth_contract_reach_model_and_thin_response_is_rejected(monkeypatch):
    r=OpenAIRewriter('offline-test');r.client=Mock();monkeypatch.setattr(r,'_rate_limit',lambda:None)
    result={'headline':'Belhaven falls','excerpt':'Belhaven lost.','body':'<p>Belhaven lost 23-19.</p>','tags':[]}
    r.client.chat.completions.create.return_value=SimpleNamespace(usage=None,choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=json.dumps(result)))])
    assert r.rewrite(CASES[3]['story'],'Belhaven game report') is None
    params=r.client.chat.completions.create.call_args.kwargs
    for fact in CASES[3]['required']:assert fact in params['messages'][1]['content']
    assert 'DEPTH AND COVERAGE' in params['messages'][1]['content']


@pytest.mark.parametrize('bad',[{'headline':None,'body':None}, {'headline':'Title','body':[]},
 {'headline':'No schedule details provided for the team','body':'The supplied text does not provide details.'}])
def test_bad_or_placeholder_payload_still_rejected(monkeypatch,bad):
    r=OpenAIRewriter('offline-test',model='gpt-6-luna');r.client=Mock();monkeypatch.setattr(r,'_rate_limit',lambda:None)
    r.client.chat.completions.create.return_value=SimpleNamespace(usage=None,choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=json.dumps(bad)))])
    assert r.rewrite(CASES[3]['story'],'Belhaven game report') is None


@pytest.mark.parametrize('verdict,accepted', [
 ({'supported':True,'issues':[]},True),
 ({'supported':False,'issues':[{'claim':'five-point halftime lead','evidence':'35-32'}]},False),
 ({'supported':False,'issues':[{'claim':'overcame penalties','evidence':'penalties extended drive'}]},False),
 ({'supported':True,'issues':['conflict']},False), ({'supported':'true','issues':[]},False),
 ([],False), ({},False)])
def test_fact_check_holds_relational_errors_and_malformed_verdicts(verdict,accepted):
    r=OpenAIRewriter('offline-test',model='gpt-6-luna',verify_facts=True);r.client=Mock()
    r.client.chat.completions.create.return_value=SimpleNamespace(usage=None,choices=[SimpleNamespace(
        finish_reason='stop',message=SimpleNamespace(content=json.dumps(verdict)))])
    article={'headline':'Result','excerpt':'A game report','body':'<p>Belhaven lost.</p>'}
    assert r._facts_supported(article,CASES[3]['story'],'Game','gpt-6-luna') is accepted
    params=r.client.chat.completions.create.call_args.kwargs
    assert params['max_completion_tokens']==800 and params['reasoning_effort']=='none'
    assert 'headline' in params['messages'][1]['content'] and 'excerpt' in params['messages'][1]['content']


def test_truncated_fact_check_cannot_approve_article():
    r=OpenAIRewriter('offline-test',model='gpt-6-luna',verify_facts=True);r.client=Mock()
    r.client.chat.completions.create.return_value=SimpleNamespace(usage=None,choices=[SimpleNamespace(
        finish_reason='length',message=SimpleNamespace(content='{"supported":true,"issues":[]}'))])
    assert not r._facts_supported({'headline':'Result','excerpt':'','body':'<p>Report</p>'},
                                  CASES[3]['story'],'Game','gpt-6-luna')
