import copy,hashlib,html,importlib.util,json
from pathlib import Path
from unittest.mock import Mock
import pytest

PATH=Path(__file__).resolve().parents[1]/'scripts/enrich_reviewed_athletics_20261027.py'
spec=importlib.util.spec_from_file_location('fixed_enrichment',PATH)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_manifest_is_exact_reviewed_scope_and_carey_has_no_derived_interval():
    data=m.load_manifest()
    assert tuple(p['id'] for p in data['posts'])==m.IDS and 25216 not in m.IDS
    assert all(p['expected_public']['status']=='publish' for p in data['posts'])
    carey=data['posts'][0]
    assert 'final 13 minutes' not in m.plain(carey['content'])
    assert 'final 13 minutes' not in m.plain(carey['expected_public']['excerpt']['rendered'])
    assert all('Update: This article has been expanded' in p['content'] for p in data['posts'])

def test_changed_manifest_fails_closed(monkeypatch,tmp_path):
    data=m.load_manifest();data['posts'][0]['content']+='unreviewed'
    (tmp_path/'reviewed-enrichment').mkdir();(tmp_path/'reviewed-enrichment/2026-10-27.json').write_text(json.dumps(data))
    monkeypatch.setattr(m,'ROOT',tmp_path)
    with pytest.raises(m.Stop,match='manifest changed'):m.load_manifest()

@pytest.mark.parametrize('endpoint,payload',[('posts',{'content':'x'}),('media/25129',{'content':'x'}),('posts/25216',{'content':'x'}),('posts/25130',{'content':'x'}),('posts/25130',{'status':'draft'}),('posts/25130',{'title':'x','content':'x'}),('posts/25130',{'slug':'new'})])
def test_mutation_scope_is_fixed(tmp_path,endpoint,payload):
    auth=Mock();w=m.Worker(auth,Mock(),tmp_path)
    with pytest.raises(m.Stop):w.request('POST',endpoint,json=payload)
    auth.request.assert_not_called()

def test_raw_snapshot_is_mandatory():
    with pytest.raises(m.Stop,match='raw'):m.snapshot(m.load_manifest()['posts'][0]['expected_public'],True)

class Response:
    def __init__(self,data=None,text='',content=b'fixture',headers=None):
        self.data=data;self.text=text;self.content=content;self.status_code=200;self.headers=headers or {}
    def json(self):return copy.deepcopy(self.data)

class API:
    def __init__(self,data):
        self.posts={p['id']:copy.deepcopy(p['expected_public']) for p in data['posts']};self.writes=[]
        for p in self.posts.values():
            for key in ('title','content','excerpt'):p[key]['raw']=p[key]['rendered']
    def request(self,method,url,**kwargs):
        endpoint=url.split('/wp-json/wp/v2/')[1]
        if endpoint=='users/me':return Response({'id':next(iter(self.posts.values()))['author'],'capabilities':{'edit_posts':True,'edit_published_posts':True,'edit_others_posts':True}})
        if method=='OPTIONS':return Response({'endpoints':[{'methods':['GET'],'args':{'status':{'items':{'enum':['publish','future','draft','pending','private','trash']}}}}]})
        if endpoint=='posts':
            status=dict(kwargs['params'])['status'];rows=[p for p in self.posts.values() if p['status']==status]
            return Response(rows,headers={'X-WP-Total':str(len(rows)),'X-WP-TotalPages':'1' if rows else '0'})
        pid=int(endpoint.split('/')[1]);p=self.posts[pid]
        if method=='POST':
            self.writes.append((endpoint,copy.deepcopy(kwargs['json'])))
            p['content']={'raw':kwargs['json']['content'],'rendered':kwargs['json']['content']}
        return Response(p)
    def get(self,url,**kwargs):
        if '/wp-json/wp/v2/posts/' in url:return Response(self.posts[int(url.rsplit('/',1)[1])])
        if '/wp-json/wp/v2/media/' in url:return Response({'id':int(url.rsplit('/',1)[1]),'source_url':m.SITE+'/wp-content/fixture.jpg'})
        if '/wp-content/' in url:return Response(content=b'fixture')
        p=next(p for p in self.posts.values() if p['link']==url)
        desc=html.escape(m.plain(p['excerpt']['rendered']),quote=True)
        page=f'<html><head><link rel="canonical" href="{url}">'
        for name in ('description','dc.description','og:description','twitter:description'):page+=f'<meta name="{name}" content="{desc}">'
        page+=f'</head><body><h1>{p["title"]["rendered"]}</h1><div class="entry-content">{p["content"]["rendered"]}</div></body></html>'
        return Response(text=page)

@pytest.fixture
def setup(monkeypatch,tmp_path):
    data=copy.deepcopy(m.load_manifest())
    for p in data['posts']:p['source_sha256']=m.sha('source fact');p['media_sha256']=hashlib.sha256(b'fixture').hexdigest()
    monkeypatch.setattr(m,'scrape_article_content',lambda _: 'source fact');monkeypatch.setattr(m,'ROOT',tmp_path)
    monkeypatch.setenv('GITHUB_ACTIONS','true');monkeypatch.setenv('GITHUB_REF',m.BRANCH);monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1')
    api=API(data);w=m.Worker(api,api,tmp_path/'output');return data,api,w

def control(plan):return {'apply':True,'approved_plan_sha256':m.digest(plan),'preflight_run_id':'123','preflight_commit':'a'*40}

def test_dry_run_reconciles_all_statuses_and_never_writes(setup):
    data,api,w=setup;plan=w.preflight(data)
    assert len(plan['posts'])==5 and not api.writes and not w.actions
    assert len(json.loads((w.output/'all-status-preflight.json').read_text()))==6
    assert all(x['before_sha256']==m.digest(x['before']) for x in plan['posts'])

def test_serial_apply_is_body_only_and_preserves_all_other_fields(setup):
    data,api,w=setup;plan=w.preflight(data);receipt=w.apply(plan,control(plan))
    assert [p[0] for p in api.writes]==[f'posts/{p}' for p in m.IDS]
    assert all(set(payload)=={'content'} for _,payload in api.writes)
    assert receipt['writes']==5 and all(a['state']=='confirmed' for a in w.actions)

@pytest.mark.parametrize('case',['plan_drift','post_drift','second_attempt','wrong_branch','completed'])
def test_apply_guards_stop_before_first_write(setup,monkeypatch,case):
    data,api,w=setup;plan=w.preflight(data);c=control(plan)
    if case=='plan_drift':c['approved_plan_sha256']='0'*64
    elif case=='post_drift':api.posts[25220]['title']['raw']+=' changed'
    elif case=='second_attempt':monkeypatch.setenv('GITHUB_RUN_ATTEMPT','2')
    elif case=='wrong_branch':monkeypatch.setenv('GITHUB_REF','refs/heads/main')
    elif case=='completed':
        (m.ROOT/'reviewed-enrichment').mkdir();(m.ROOT/'reviewed-enrichment/completion-receipt.json').write_text('{}')
    with pytest.raises(m.Stop):w.apply(plan,c)
    assert not api.writes

def test_uncertain_write_is_recorded_without_retry(setup):
    data,api,w=setup;plan=w.preflight(data);original=api.request;attempts=[]
    def fail(method,url,**kwargs):
        if method=='POST':attempts.append(url);raise m.requests.Timeout('no response')
        return original(method,url,**kwargs)
    api.request=fail
    with pytest.raises(m.Stop,match='outcome unavailable'):w.apply(plan,control(plan))
    assert len(attempts)==1 and w.actions[0]['state']=='uncertain_or_failed'
    assert (w.output/f'uncertain-{m.IDS[0]}.json').exists()

@pytest.mark.parametrize('drift',['missing','status','source','image'])
def test_preflight_drift_prevents_writes(setup,monkeypatch,drift):
    data,api,w=setup
    if drift=='missing':api.posts.pop(25130)
    elif drift=='status':api.posts[25130]['status']='draft'
    elif drift=='source':monkeypatch.setattr(m,'scrape_article_content',lambda _: 'changed source')
    elif drift=='image':data['posts'][0]['media_sha256']='0'*64
    with pytest.raises(m.Stop):w.preflight(data)
    assert not api.writes
