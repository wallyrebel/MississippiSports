"""Six fixed unpublished source comparisons; public GETs and bounded LLM calls only."""
import hashlib,json,os,re
from pathlib import Path
import requests
from openai import OpenAI
from bs4 import BeautifulSoup
from rss_to_wp.feeds.parser import get_entry_content,parse_feed,authorized_athletics_url
from rss_to_wp.rewriter.openai_client import OpenAIRewriter
from rss_to_wp.rewriter.depth import words

IDS=(25130,25134,25148,25204,25220,25216)
FEEDS=('https://careyathletics.com/rss.aspx?path=msoc','https://bmcusports.com/rss.aspx?path=wbball',
       'https://gostatesmen.com/rss.aspx?path=football','https://blazers.belhaven.edu/rss.aspx?path=football',
       'https://sports.hindscc.edu/rss.aspx?path=msoc','https://owlsathletics.com/rss.aspx?path=wsoc')
ROOT=Path('depth-verification');ROOT.mkdir(exist_ok=True)
assert os.environ.get('GITHUB_ACTIONS')=='true'
assert not any(os.environ.get(k) for k in ['WORDPRESS_APP_PASSWORD','WORDPRESS_USERNAME'])
def get(url):
    r=requests.get(url,timeout=(10,40),headers={'User-Agent':'Mozilla/5.0 public verification'});r.raise_for_status();return r
def sha(text):return hashlib.sha256(text.encode()).hexdigest()
def old_body(post):
    s=BeautifulSoup(post['content']['rendered'],'html.parser')
    for p in s.find_all('p'):
        if p.get_text(' ',strip=True).startswith('Source:'):p.decompose()
    return str(s)
r=OpenAIRewriter(os.environ['OPENAI_API_KEY'],model='gpt-6-luna')
r.client=OpenAI(api_key=os.environ['OPENAI_API_KEY'],timeout=90,max_retries=0)
usage=[];create=r.client.chat.completions.create
def tracked(**params):
    params['store']=False
    response=create(**params)
    usage.append(response.usage.model_dump())
    return response
r.client.chat.completions.create=tracked
results=[]
for pid,feedurl in zip(IDS,FEEDS):
    post=get(f'https://sportsmississippi.com/wp-json/wp/v2/posts/{pid}').json()
    assert post['id']==pid and post['status']=='publish'
    s=BeautifulSoup(post['content']['rendered'],'html.parser')
    source=next(a['href'] for a in s.select('a[href]') if authorized_athletics_url(a['href']))
    feed=parse_feed(feedurl);assert feed is not None
    entry=next(e for e in feed.entries if e.get('link','').rstrip('/')==source.rstrip('/'))
    content=get_entry_content(entry);assert content
    title=entry['title'];start=len(usage);candidate=r.rewrite(content,title)
    media=get(f"https://sportsmississippi.com/wp-json/wp/v2/media/{post['featured_media']}").json()
    image=get(media['source_url']).content;ROOT.joinpath(f'{pid}-existing-image').write_bytes(image)
    row={'id':pid,'url':post['link'],'source_url':source,'source_title':title,
         'source_text':content,'source_sha256':sha(content),'source_words':len(words(content)),
         'before_body_words':len(words(old_body(post))),
         'expected_public':{k:post[k] for k in ['id','slug','link','status','date','date_gmt','modified','modified_gmt','author','featured_media','categories','tags','title','content','excerpt','meta']},
         'before_rendered_content_sha256':sha(post['content']['rendered']),
         'candidate':candidate,'candidate_body_words':len(words(candidate['body'])) if candidate else 0,
         'candidate_paragraphs':len(BeautifulSoup(candidate['body'],'html.parser').find_all('p')) if candidate else 0,
         'usage':usage[start:],'media_id':media['id'],'media_url':media['source_url'],
         'media_sha256':hashlib.sha256(image).hexdigest(),'writes':0}
    if candidate:
        row['proposed_existing_post_patch']={'content':candidate['body']+f'<p><em>Source: <a href="{source}" target="_blank" rel="noopener">Original Article</a></em></p>'}
    results.append(row);ROOT.joinpath('results.json').write_text(json.dumps(results,indent=2))
    print(json.dumps({k:row[k] for k in ['id','source_words','before_body_words','candidate_body_words','candidate_paragraphs','writes']}))
ROOT.joinpath('summary.json').write_text(json.dumps({'run_id':os.environ['GITHUB_RUN_ID'],'commit':os.environ['GITHUB_SHA'],
    'model':'gpt-6-luna','reasoning_effort':'none','posts':list(IDS),'candidates':sum(bool(x['candidate']) for x in results),
    'writes':0,'input_tokens':sum(x['prompt_tokens'] for x in usage),'output_tokens':sum(x['completion_tokens'] for x in usage)},indent=2))
assert all(x['candidate'] for x in results),'One or more samples held; review artifacts before deployment'
