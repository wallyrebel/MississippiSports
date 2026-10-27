"""Four fixed unpublished chronology checks; no WordPress access."""
import json,os
from pathlib import Path
from openai import OpenAI
from rss_to_wp.rewriter.openai_client import OpenAIRewriter

assert os.environ.get('GITHUB_ACTIONS')=='true'
assert not os.environ.get('WORDPRESS_APP_PASSWORD')
r=OpenAIRewriter(os.environ['OPENAI_API_KEY'],model='gpt-6-luna',verify_facts=True)
r.client=OpenAI(api_key=os.environ['OPENAI_API_KEY'],timeout=60,max_retries=0)
responses=[];create=r.client.chat.completions.create
def tracked(**params):
    params['store']=False;reply=create(**params);choice=reply.choices[0]
    assert choice.finish_reason=='stop'
    verdict=json.loads(choice.message.content)
    assert isinstance(verdict.get('supported'),bool) and isinstance(verdict.get('issues'),list)
    responses.append({'verdict':verdict,'usage':reply.usage.model_dump()});return reply
r.client.chat.completions.create=tracked
reference='2026-10-27T11:30:00-05:00';published='Mon, 26 Oct 2026 12:00:00 +0000'
calendar='Monday, October 26: Mississippi Farm Bureau press conference at 11 a.m. The event will be streamed on Delta State’s YouTube channel. All media is invited.'
golf='The Judson final round is scheduled to tee off at 8 a.m. Tuesday in Hattiesburg. This report was published Monday, October 26.'
cases=[('past_press_conference_future',calendar,'The press conference will be streamed Monday at 11 a.m. Media members are invited to attend.',False),
       ('past_press_conference_attributed',calendar,'The calendar listed a press conference for 11 a.m. Monday, October 26, with streaming planned on Delta State’s YouTube channel and an invitation to media members.',True),
       ('past_golf_start_future',golf,'The final round will tee off at 8 a.m. Tuesday in Hattiesburg.',False),
       ('past_golf_start_attributed',golf,'The report listed an 8 a.m. Tuesday start for the final round in Hattiesburg.',True)]
out=[];root=Path('date-context-verification');root.mkdir(exist_ok=True)
for name,source,body,expected in cases:
    article={'headline':'Published athletics report','excerpt':'','body':'<p>'+body+'</p>'}
    actual=r._facts_supported(article,source,'Published athletics report','gpt-6-luna',reference,published)
    row={'case':name,'expected_supported':expected,'actual_supported':actual,**responses[-1],'writes':0}
    out.append(row);(root/'results.json').write_text(json.dumps(out,indent=2));print(json.dumps({'case':name,'expected':expected,'actual':actual,'writes':0}))
    assert actual is expected
    assert (responses[-1]['verdict']['issues']==[]) is expected
