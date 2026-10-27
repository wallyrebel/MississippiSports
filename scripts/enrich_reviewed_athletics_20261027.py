"""One-shot, digest-bound body enrichment of five fixed existing posts.

No creation, media/taxonomy writes, publication replay, credentials provisioning
or mutation retries. Dry-run precedes a separately pinned apply control.
"""
import hashlib,json,os,re
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup
from rss_to_wp.feeds.parser import scrape_article_content

SITE='https://sportsmississippi.com'
BRANCH='refs/heads/enrich-reviewed-athletics-20261027'
IDS=(25130,25134,25148,25204,25220)
MANIFEST_SHA='6d3368870cc9186cbffa087b3e06b8f1ace9a0dc606f90ed5bd8dfd84cfffe1c'
PATCHES={25130:'426c0c296df11969d7cc66e14290d9f112a6bf0c8e82a7973bb95b1d94f24e79',25134:'1883dc777768809d7a6398abb2de0d1aac11f99b183f9c040935cb085d9c7e12',25148:'008a9ddc271140af17dd7c07b32beacabb1cbf31ad2161baf2fdf73257bc655c',25204:'a450b1fcc8dc75cc267657070af7074a51334b4192b9e0f0b58470a9144a91c2',25220:'2d21ebca136f06f2c6e6d9b604cbf745724ee18755f476be4a7ec668bed6ae1c'}
CORE=('id','slug','link','status','date','date_gmt','modified','modified_gmt','author','featured_media','categories','tags')
PRESERVED=tuple(k for k in CORE if k not in ('modified','modified_gmt'))
ROOT=Path(__file__).resolve().parents[1]

class Stop(Exception):pass
def require(ok,message):
    if not ok:raise Stop(message)
def sha(text):return hashlib.sha256(text.encode()).hexdigest()
def digest(value):return sha(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False))
def plain(text):
    text=BeautifulSoup(text,'html.parser').get_text(' ',strip=True)
    return re.sub(r'\s+',' ',text).translate(str.maketrans({'’':"'",'‘':"'",'“':'"','”':'"'})).strip()
def snapshot(post,edit=False):
    require(all(k in post for k in CORE),'Incomplete post identity')
    out={k:post[k] for k in CORE}
    for field in ('title','content','excerpt'):
        require(isinstance(post.get(field,{}).get('rendered'),str),'Rendered field missing')
        out[field]=post[field]['rendered']
        if edit:
            require(isinstance(post[field].get('raw'),str),'Authenticated raw field missing')
            out[field+'_raw']=post[field]['raw']
    if edit:out['meta_sha256']=digest(post.get('meta',{}))
    return out
def load_manifest():
    data=json.loads((ROOT/'reviewed-enrichment/2026-10-27.json').read_text())
    require(digest(data)==MANIFEST_SHA,'Reviewed manifest changed')
    require(data['site']==SITE and tuple(p['id'] for p in data['posts'])==IDS,'Wrong site or IDs')
    for p in data['posts']:
        require(sha(p['content'])==p['patch_sha256']==PATCHES[p['id']],'Unreviewed body patch')
    return data

class Worker:
    def __init__(self,auth,public,output):
        self.auth,self.public,self.output=auth,public,Path(output)
        self.output.mkdir(parents=True,exist_ok=True)
        self.actions=[];self.save('actions.json',self.actions)
    def save(self,name,data):
        (self.output/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
    def request(self,method,endpoint,**kwargs):
        require(method in ('GET','OPTIONS','POST'),'Unsupported method')
        require(endpoint in {'posts','users/me'}|{f'posts/{p}' for p in IDS},'Unexpected endpoint')
        if method=='POST':
            require(endpoint in {f'posts/{p}' for p in IDS},'Mutation outside fixed IDs')
            require(set(kwargs)=={'json'} and set(kwargs['json'])=={'content'},'Only body may change')
            pid=int(endpoint.split('/')[1]);require(sha(kwargs['json']['content'])==PATCHES[pid],'Unreviewed content')
        try:r=self.auth.request(method,SITE+'/wp-json/wp/v2/'+endpoint,timeout=(10,45),allow_redirects=False,**kwargs)
        except requests.RequestException:raise Stop(f'{method} {endpoint} outcome unavailable') from None
        require(200<=r.status_code<300,f'{method} {endpoint} failed HTTP{r.status_code}')
        return r
    def read(self,endpoint,**kwargs):return self.request('GET',endpoint,**kwargs).json()
    def public_get(self,url):
        from urllib.parse import urlsplit
        host=urlsplit(url).hostname
        require(url.startswith('https://') and host in {'sportsmississippi.com','careyathletics.com','bmcusports.com','gostatesmen.com','blazers.belhaven.edu','sports.hindscc.edu'},'Unexpected public host')
        try:r=self.public.get(url,timeout=(10,45),allow_redirects=False)
        except requests.RequestException:raise Stop('Public verification unavailable') from None
        require(r.status_code==200,f'Public verification failed HTTP{r.status_code}')
        return r
    def surface(self,post):
        # Static page caches can omit charset in Content-Type. Let the HTML
        # declaration decode bytes instead of requests' ISO-8859-1 fallback.
        page=self.public_get(post['link']);s=BeautifulSoup(page.content,'html.parser')
        canonical=s.find('link',rel='canonical')
        require(canonical and canonical.get('href','').rstrip('/')==post['link'].rstrip('/'),'Canonical changed')
        h1s=[plain(str(h)) for h in s.find_all('h1')]
        if plain(post['title']) not in h1s:
            self.save(f'public-h1-mismatch-{post["id"]}.json',{'url':post['link'],
                      'expected':plain(post['title']),'observed':h1s,
                      'content_type':page.headers.get('Content-Type','')})
            raise Stop(f'Post{post["id"]} H1 differs from retained title')
        descriptions={}
        for name in ('description','dc.description','og:description','twitter:description'):
            tag=s.find('meta',attrs={'name':name}) or s.find('meta',attrs={'property':name})
            require(tag is not None,f'Missing {name}');descriptions[name]=tag.get('content','')
        robots=[m.get('content','') for m in s.find_all('meta',attrs={'name':re.compile('^robots$',re.I)})]
        header=page.headers.get('X-Robots-Tag','')
        require('noindex' not in (' '.join(robots)+' '+header).lower(),'Article is not indexable')
        return {'canonical':canonical['href'],'description':descriptions,'robots':robots,'x_robots_tag':header,
                'page_body':plain(str(s.select_one('.entry-content') or s))}
    def statuses(self):
        schema=self.request('OPTIONS','posts').json();statuses=[]
        for route in schema.get('endpoints',[]):
            if 'GET' in route.get('methods',[]) and 'status' in route.get('args',{}):
                statuses=[s for s in route['args']['status'].get('items',{}).get('enum',[]) if s!='any'];break
        require({'publish','future','draft','pending','private','trash'}<=set(statuses),'All-status schema unavailable')
        return statuses
    def preflight(self,data):
        me=self.read('users/me',params={'context':'edit','_fields':'id,capabilities'})
        caps=me.get('capabilities',{});require(caps.get('edit_posts') is True and caps.get('edit_published_posts') is True,'Existing account lacks edit capability')
        found={};audit=[]
        for status in self.statuses():
            page=1;batch=[];totals=None
            while True:
                params=[('include[]',p) for p in IDS]+[('context','edit'),('status',status),('per_page',100),('page',page),('orderby','id'),('order','asc')]
                r=self.request('GET','posts',params=params);now=(int(r.headers['X-WP-Total']),int(r.headers['X-WP-TotalPages']))
                require(totals in (None,now),'All-status pagination changed');totals=now
                values=r.json();require(isinstance(values,list) and 0<=now[1]<=100,'Invalid pagination');batch+=values
                if page>=now[1]:break
                page+=1
            require(len(batch)==totals[0],'Incomplete status reconciliation')
            for p in batch:
                require(p['id'] in IDS and p['status']==status and p['id'] not in found,'Duplicate or unexpected status record')
                found[p['id']]=p
            audit.append({'status':status,'ids':[p['id'] for p in batch],'total':totals[0]})
        require(set(found)==set(IDS),'A reviewed post is missing')
        plan={'site':SITE,'manifest_sha256':MANIFEST_SHA,'posts':[]}
        for item in data['posts']:
            p=found[item['id']];require(p['status']=='publish','Only existing published posts')
            require(p['author']==me['id'] or caps.get('edit_others_posts') is True,'Cannot edit this author')
            require(snapshot(p)==snapshot(item['expected_public']),f'Post{p["id"]} public baseline drift')
            before=snapshot(p,True)
            require(snapshot(self.read(f'posts/{p["id"]}',params={'context':'edit'}),True)==before,'Post drift during preflight')
            source=scrape_article_content(item['source_url'])
            require(source and sha(source)==item['source_sha256'],f'Source{p["id"]} drift')
            media=self.public_get(f'{SITE}/wp-json/wp/v2/media/{p["featured_media"]}').json()
            require(media['id']==p['featured_media'],'Image identity changed')
            image_sha=hashlib.sha256(self.public_get(media['source_url']).content).hexdigest()
            require(image_sha==item['media_sha256'],'Existing image bytes changed')
            surfaces=self.surface(before);surfaces.pop('page_body')
            plan['posts'].append({'id':p['id'],'before':before,'before_sha256':digest(before),
                'content':item['content'],'patch_sha256':item['patch_sha256'],'source_sha256':item['source_sha256'],
                'media_url':media['source_url'],'media_sha256':image_sha,'surface_before':surfaces})
        self.save('all-status-preflight.json',audit);self.save('plan.json',plan)
        self.save('review.json',{'plan_sha256':digest(plan),'manifest_sha256':MANIFEST_SHA,
                                'run_id':os.environ.get('GITHUB_RUN_ID'),'commit':os.environ.get('GITHUB_SHA'),'writes':0})
        return plan
    def apply(self,plan,control):
        require(control.get('apply') is True and control.get('approved_plan_sha256')==digest(plan),'Fresh plan differs from reviewed dry-run')
        require(re.fullmatch(r'\d+',str(control.get('preflight_run_id',''))) and re.fullmatch(r'[a-f0-9]{40}',control.get('preflight_commit','')),'Missing dry-run provenance')
        require(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REF')==BRANCH and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','Only first managed attempt on fixed branch')
        require(not (ROOT/'reviewed-enrichment/completion-receipt.json').exists(),'One-shot already complete')
        for item in plan['posts']:
            require(snapshot(self.read(f'posts/{item["id"]}',params={'context':'edit'}),True)==item['before'],'Post drift before first write')
        receipts=[]
        for item in plan['posts']:
            endpoint=f'posts/{item["id"]}'
            require(snapshot(self.read(endpoint,params={'context':'edit'}),True)==item['before'],'Post drift immediately before write')
            action={'id':item['id'],'state':'attempted','patch_sha256':item['patch_sha256']};self.actions.append(action);self.save('actions.json',self.actions)
            try:self.request('POST',endpoint,json={'content':item['content']})
            except Stop:
                action['state']='uncertain_or_failed';self.save('actions.json',self.actions)
                try:self.save(f'uncertain-{item["id"]}.json',snapshot(self.read(endpoint,params={'context':'edit'}),True))
                except Exception:pass
                raise
            after=snapshot(self.read(endpoint,params={'context':'edit'}),True)
            require(all(after[k]==item['before'][k] for k in (*PRESERVED,'title_raw','excerpt_raw','meta_sha256')),'Preserved field changed')
            require(after['content_raw']==item['content'],'Raw body write not confirmed')
            self.save(f'after-{item["id"]}.json',after)
            action['state']='authenticated_confirmed';self.save('actions.json',self.actions)
            public=snapshot(self.public_get(f'{SITE}/wp-json/wp/v2/{endpoint}').json())
            require(all(public[k]==item['before'][k] for k in PRESERVED),'Public identity changed')
            require(plain(public['content'])==plain(item['content']),'Public REST body not confirmed')
            surface=self.surface(public);body=surface.pop('page_body')
            require(plain(item['content']) in body,'Public canonical body not confirmed')
            require(surface==item['surface_before'],'Description/canonical/indexability changed')
            media=self.public_get(f'{SITE}/wp-json/wp/v2/media/{public["featured_media"]}').json()
            require(media['source_url']==item['media_url'] and hashlib.sha256(self.public_get(media['source_url']).content).hexdigest()==item['media_sha256'],'Image changed')
            action['state']='confirmed';self.save('actions.json',self.actions)
            receipts.append({'id':item['id'],'url':public['link'],'patch_sha256':item['patch_sha256'],
                'before_sha256':item['before_sha256'],'after_raw_content_sha256':sha(after['content_raw']),
                'identity_title_excerpt_dates_media_taxonomy_preserved':True,'public_rest_canonical_body_verified':True,
                'h1_descriptions_canonical_indexability_preserved':True,'image_file_preserved':True})
            self.save('partial-receipt.json',receipts)
        receipt={'run_id':os.environ.get('GITHUB_RUN_ID'),'commit':os.environ.get('GITHUB_SHA'),
                 'plan_sha256':digest(plan),'posts':receipts,'writes':len(self.actions)}
        self.save('completion-receipt.json',receipt);return receipt

def main():
    worker=None
    try:
        require(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REF')==BRANCH,'Managed fixed branch only')
        require(os.environ.get('WORDPRESS_BASE_URL','').rstrip('/')==SITE,'Managed site mismatch')
        auth,public=requests.Session(),requests.Session()
        for s in (auth,public):s.mount('https://',HTTPAdapter(max_retries=0))
        auth.auth=(os.environ['WORDPRESS_USERNAME'],os.environ['WORDPRESS_APP_PASSWORD'])
        public.headers.update({'User-Agent':'Mozilla/5.0 publication verification'})
        worker=Worker(auth,public,'enrichment-output');data=load_manifest()
        control=json.loads((ROOT/'reviewed-enrichment/control.json').read_text());plan=worker.preflight(data)
        if control.get('apply') is True:worker.apply(plan,control)
        worker.save('result.json',{'ok':True,'dry_run':control.get('apply') is not True,'writes':len(worker.actions),'plan_sha256':digest(plan)})
        print(json.dumps({'ok':True,'dry_run':control.get('apply') is not True,'writes':len(worker.actions)}))
    except Exception as error:
        message=str(error) if isinstance(error,Stop) else 'Invalid preflight or managed response; no mutation retry'
        if worker:worker.save('result.json',{'ok':False,'error':message,'writes_attempted':len(worker.actions)})
        print(message);raise SystemExit(1)
if __name__=='__main__':main()
