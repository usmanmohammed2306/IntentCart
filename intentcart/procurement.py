"""Single-instance IT procurement: evidence, stock reservations and dual control.

No network, model, payment, supplier ordering or invented price data. An approved
handoff is a record for the purchasing team, not proof of purchase or delivery.
"""
from datetime import date
import hashlib
import json
import secrets
import time
import uuid
from pathlib import Path
from typing import Literal
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from . import accounts

CATALOG_PATH = Path(__file__).parent/'data/it-catalog.json'
CATALOG = json.loads(CATALOG_PATH.read_text())
PRODUCTS = {p['id']:p for p in CATALOG['products']}
CATALOG_HASH = hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest()
LAPTOP='dell-latitude-5440'
DOCK='dell-wd22tb4-180w'
MONITOR='dell-p2422h-dp'
DAY=86400

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,str_strip_whitespace=True)
    @field_validator('*',mode='after')
    @classmethod
    def text(cls,value):
        if isinstance(value,str) and any(ord(c)<32 for c in value):
            raise ValueError('Control characters are not allowed.')
        return value

class Team(Strict):
    name:str=Field(min_length=1,max_length=80)
    limit_cents:int=Field(ge=0,le=100000000)
class Member(Strict):
    username:str=Field(min_length=3,max_length=32)
    role:Literal['requester','approver','stock']
class Asset(Strict):
    tag:str=Field(min_length=1,max_length=64)
    sku:str=Field(min_length=1,max_length=100)
    location:str=Field(min_length=1,max_length=100)
    usable:bool=False
class AssetState(Strict):
    revision:int=Field(ge=1)
    state:Literal['available','service','retired']
    usable:bool
class Quote(Strict):
    revision:int=Field(default=0,ge=0)
    sku:str=Field(min_length=1,max_length=100)
    vendor:str=Field(min_length=1,max_length=100)
    reference:str=Field(min_length=1,max_length=120)
    unit_cents:int=Field(ge=1,le=100000000)
    valid_until:int=Field(ge=1)
    available_units:int=Field(ge=0,le=1000)
class Need(Strict):
    title:str=Field(min_length=1,max_length=100)
    employee:str=Field(min_length=1,max_length=100)
    location:str=Field(min_length=1,max_length=100)
    laptop_asset:str=Field(min_length=1,max_length=64)
    screens:int=Field(ge=0,le=4)
    budget_cents:int=Field(ge=0,le=100000000)
    shipping_cents:int|None=Field(default=None,ge=0,le=100000000)
    tax_cents:int|None=Field(default=None,ge=0,le=100000000)
    configuration_checked:bool=False
    it_readiness_checked:bool=False
    notes:str=Field(default='',max_length=1000)
class Revise(Need):
    revision:int=Field(ge=1)
class Version(Strict):
    revision:int=Field(ge=1)
class Quantity(Version):
    screens:int=Field(ge=0,le=4)
    replace_approved:bool=False
class ReturnAsset(Version):
    location:str=Field(min_length=1,max_length=100)
    reason:str=Field(min_length=3,max_length=500)
class Submit(Version):
    fingerprint:str=Field(min_length=64,max_length=64)
class Decide(Submit):
    decision:Literal['approve','reject']
    reason:str=Field(min_length=3,max_length=500)
class Ordered(Submit):
    reference:str=Field(min_length=1,max_length=120)
class Receive(Version):
    tags:list[str]=Field(max_length=3)

def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS it_teams(id TEXT PRIMARY KEY,name TEXT NOT NULL,limit_cents INTEGER NOT NULL,created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS it_members(team TEXT REFERENCES it_teams(id),account TEXT REFERENCES accounts(id),role TEXT NOT NULL,PRIMARY KEY(team,account));
    CREATE TABLE IF NOT EXISTS it_assets(id TEXT PRIMARY KEY,team TEXT NOT NULL REFERENCES it_teams(id),tag TEXT NOT NULL,sku TEXT NOT NULL,location TEXT NOT NULL,usable INTEGER NOT NULL,state TEXT NOT NULL,request_id TEXT,revision INTEGER NOT NULL,UNIQUE(team,tag));
    CREATE TABLE IF NOT EXISTS it_quotes(team TEXT REFERENCES it_teams(id),sku TEXT NOT NULL,data TEXT NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(team,sku));
    CREATE TABLE IF NOT EXISTS it_requests(id TEXT PRIMARY KEY,team TEXT REFERENCES it_teams(id),author TEXT REFERENCES accounts(id),state TEXT NOT NULL,revision INTEGER NOT NULL,data TEXT NOT NULL,snapshot TEXT,approver TEXT,expires REAL,created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS it_events(id INTEGER PRIMARY KEY AUTOINCREMENT,team TEXT NOT NULL,request_id TEXT,actor TEXT NOT NULL,event TEXT NOT NULL,created REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS it_requests_team ON it_requests(team,created);
    CREATE INDEX IF NOT EXISTS it_assets_team ON it_assets(team,state);
    ''')

def unpack(row):return dict(row) if row else None
def fail(status,message):raise HTTPException(status,message)
def event(db,team,actor,kind,rid=None):
    db.execute('INSERT INTO it_events(team,request_id,actor,event,created) VALUES (?,?,?,?,?)',(team,rid,actor,kind,time.time()))
def release(db,rid):
    db.execute("UPDATE it_assets SET state='available',request_id=NULL,revision=revision+1 WHERE request_id=? AND state='reserved'",(rid,))
def expire(db,team):
    rows=db.execute("SELECT id FROM it_requests WHERE team=? AND state IN ('submitted','approved') AND expires<=?",(team,time.time())).fetchall()
    for row in rows:
        release(db,row['id']);db.execute("UPDATE it_requests SET state='cancelled',revision=revision+1 WHERE id=?",(row['id'],))
        event(db,team,'system','Reservation expired; create or revise a request.',row['id'])

def member(db,team,user,roles=None):
    row=db.execute('SELECT role FROM it_members WHERE team=? AND account=?',(team,user)).fetchone()
    if not row:fail(404,'Team not found.')
    if roles and row['role'] not in roles:fail(403,'Your team role cannot perform this action.')
    expire(db,team)
    return row['role']
def request_row(db,team,rid):
    row=db.execute('SELECT * FROM it_requests WHERE team=? AND id=?',(team,rid)).fetchone()
    if not row:fail(404,'Request not found.')
    return row
def version(row,v):
    if row['revision']!=v:fail(409,'This record changed. Refresh before continuing.')
def editable(row,user):
    if row['author']!=user:fail(403,'Only the requester can edit this request.')
    if row['state'] not in ('draft','rejected','cancelled'):fail(409,'Cancel the active request before editing.')

def plan(db,row,now=None):
    now=time.time() if now is None else now
    need=json.loads(row['data']);checks=[];lines=[];reuse=[];missing=[]
    def check(key,ok,label,source_ids=None):checks.append({'key':key,'ok':bool(ok),'label':label,'source_ids':source_ids or []})
    team=db.execute('SELECT * FROM it_teams WHERE id=?',(row['team'],)).fetchone()
    requester_active=db.execute('SELECT 1 FROM it_members m JOIN accounts a ON a.id=m.account WHERE m.team=? AND m.account=? AND a.active=1',(row['team'],row['author'])).fetchone()
    check('requester',requester_active,'Requester still has an active team account')
    if row['state'] in ('submitted','approved'):
        check('reservation',row['expires'] is not None and row['expires']>now,'Fixed stock reservation has not expired')
    assets=db.execute("SELECT * FROM it_assets WHERE team=? AND usable=1 AND location=? AND (state='available' OR (state='reserved' AND request_id=?)) ORDER BY tag,id",(row['team'],need['location'],row['id'])).fetchall()
    host=next((a for a in assets if a['id']==need['laptop_asset']),None)
    check('host',host is not None and host['sku']==LAPTOP,'Exact Latitude 5440 asset available at this location',['host-ports'])
    check('configuration',need['configuration_checked'],'IT confirms Windows 11, Intel integrated graphics and ≤100 W host configuration',['host-ports','host-power'])
    check('readiness',need['it_readiness_checked'],'IT confirms approved BIOS/graphics/dock firmware, power leads and direct DP cables; no new display driver promised',['dock-display','dock-power','display'])
    check('evidence',date.fromtimestamp(now)<=date.fromisoformat(CATALOG['review_by']),'Manufacturer evidence is within its review window')
    check('screens',need['screens']<=2,'Reviewed limit: zero, one or two 1080p/60 displays',['dock-display','display'])
    if host:reuse.append(dict(host))
    wanted={DOCK:1 if need['screens'] else 0,MONITOR:need['screens']}
    for sku,quantity in wanted.items():
        available=[a for a in assets if a['sku']==sku][:quantity]
        reuse.extend(dict(a) for a in available)
        count=quantity-len(available)
        if not count:continue
        q=db.execute('SELECT data,revision FROM it_quotes WHERE team=? AND sku=?',(row['team'],sku)).fetchone()
        quote=json.loads(q['data']) if q else None
        committed=0
        if q:
            for other in db.execute("SELECT snapshot FROM it_requests WHERE team=? AND id<>? AND state IN ('submitted','approved','ordered','fulfilled')",(row['team'],row['id'])):
                for line in json.loads(other['snapshot'])['purchase']:
                    if line['sku']==sku and line['quote_revision']==q['revision']:committed+=line['quantity']
        good=quote is not None and quote['valid_until']>now and quote['available_units']-committed>=count
        check('quote:'+sku,good,'Current supplier quote and declared stock: '+PRODUCTS[sku]['name'])
        if not good:missing.append(sku)
        lines.append({'sku':sku,'name':PRODUCTS[sku]['name'],'quantity':count,'quote':quote,'quote_revision':q['revision'] if q else None,'subtotal_cents':count*quote['unit_cents'] if quote else None})
    extras=need['shipping_cents'] is not None and need['tax_cents'] is not None
    check('landed',extras or not lines,'Shipping and tax are explicitly entered, including zero')
    total=(sum(l['subtotal_cents'] or 0 for l in lines)+(need['shipping_cents'] or 0)+(need['tax_cents'] or 0) if lines else 0) if not missing and (extras or not lines) else None
    limit=min(need['budget_cents'],team['limit_cents'])
    check('budget',total is not None and total<=limit,'All-in purchase is within employee and team limits')
    deadline=min([now+DAY]+[l['quote']['valid_until'] for l in lines if l['quote']])
    # Preserve a submitted plan's fixed deadline; a read can never extend it.
    if row['expires']:deadline=min(deadline,row['expires'])
    payload={'need':need,'catalog_sha256':CATALOG_HASH,'team_limit_cents':team['limit_cents'],'reuse':[{'id':a['id'],'sku':a['sku'],'tag':a['tag']} for a in reuse],'purchase':lines,'total_cents':total}
    fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'checks':checks,'ready':all(c['ok'] for c in checks),'reuse':reuse,'purchase':lines,'total_cents':total,'fingerprint':fingerprint,'expires':deadline,'catalog_sha256':CATALOG_HASH,'scope':CATALOG['scope']}

def view(db,row):
    result=dict(row);result['data']=json.loads(row['data']);result['snapshot']=json.loads(row['snapshot']) if row['snapshot'] else None
    result['plan']=plan(db,row)
    result['approval_current']=row['state'] in ('approved','ordered','fulfilled') and bool(result['snapshot']) and (row['state'] in ('ordered','fulfilled') or row['expires']>time.time() and result['snapshot']['fingerprint']==result['plan']['fingerprint'] and result['plan']['ready'])
    if row['state']=='approved':
        active=db.execute("SELECT 1 FROM it_members m JOIN accounts a ON a.id=m.account WHERE m.team=? AND m.account=? AND m.role IN ('owner','approver') AND a.active=1",(row['team'],row['approver'])).fetchone()
        result['approval_current']=result['approval_current'] and bool(active)
    return result

def register(module):
    app=module.app
    def auth(request,db,write=False):
        if not accounts.enabled():fail(403,'Sign-in accounts are required for procurement.')
        return accounts.current(request,db,write)['id']
    @app.get('/procurement')
    def page():return RedirectResponse('/agent#team',status_code=307)
    @app.get('/api/it/catalog')
    def catalog(request:Request):
        with module.database() as db:auth(request,db)
        return {**CATALOG,'sha256':CATALOG_HASH}
    @app.get('/api/it/teams')
    def teams(request:Request):
        with module.database() as db:
            uid=auth(request,db)
            return {'teams':[dict(r) for r in db.execute('SELECT t.*,m.role FROM it_teams t JOIN it_members m ON m.team=t.id WHERE m.account=? ORDER BY t.created',(uid,))]}
    @app.post('/api/it/teams')
    def create_team(body:Team,request:Request):
        with module.database() as db:
            uid=auth(request,db,True)
            if db.execute("SELECT count(*) FROM it_members WHERE account=? AND role='owner'",(uid,)).fetchone()[0]>=5:fail(409,'Five owned teams is the local limit.')
            tid=str(uuid.uuid4());db.execute('INSERT INTO it_teams VALUES (?,?,?,?)',(tid,body.name,body.limit_cents,time.time()))
            db.execute('INSERT INTO it_members VALUES (?,?,?)',(tid,uid,'owner'));event(db,tid,uid,'Team created')
            return {'id':tid}
    @app.get('/api/it/{tid}')
    def dashboard(tid:str,request:Request):
        with module.database() as db:
            uid=auth(request,db);role=member(db,tid,uid)
            return {'team':dict(db.execute('SELECT * FROM it_teams WHERE id=?',(tid,)).fetchone()),'role':role,'user_id':uid,
                'members':[dict(r) for r in db.execute('SELECT a.id,a.username,a.name,m.role FROM it_members m JOIN accounts a ON a.id=m.account WHERE m.team=?',(tid,))],
                'assets':[dict(r) for r in db.execute('SELECT * FROM it_assets WHERE team=? ORDER BY tag',(tid,))],
                'quotes':[{'revision':r['revision'],**json.loads(r['data'])} for r in db.execute('SELECT data,revision FROM it_quotes WHERE team=?',(tid,))],
                'requests':[view(db,r) for r in db.execute('SELECT * FROM it_requests WHERE team=? ORDER BY created DESC LIMIT 100',(tid,))],
                'events':[dict(r) for r in db.execute('SELECT * FROM it_events WHERE team=? ORDER BY id DESC LIMIT 100',(tid,))]}
    @app.post('/api/it/{tid}/members')
    def add_member(tid:str,body:Member,request:Request):
        with module.database() as db:
            uid=auth(request,db,True);member(db,tid,uid,('owner',))
            target=db.execute('SELECT id FROM accounts WHERE username=? AND active=1',(body.username,)).fetchone()
            if not target:fail(404,'An active account with that exact username is required.')
            if target['id']==uid:fail(409,'You cannot change the owner role.')
            if db.execute('SELECT 1 FROM it_members WHERE team=? AND account=?',(tid,target['id'])).fetchone():fail(409,'This person already belongs to the team.')
            db.execute('INSERT INTO it_members VALUES (?,?,?)',(tid,target['id'],body.role));event(db,tid,uid,'Member added: '+body.username+' / '+body.role)
            return {'ok':True}
    @app.delete('/api/it/{tid}/members/{account_id}')
    def remove_member(tid:str,account_id:str,request:Request):
        with module.database() as db:
            uid=auth(request,db,True);member(db,tid,uid,('owner',))
            if account_id==uid:fail(409,'The team owner cannot be removed.')
            db.execute('DELETE FROM it_members WHERE team=? AND account=?',(tid,account_id));event(db,tid,uid,'Member removed: '+account_id)
            return {'ok':True}
    @app.post('/api/it/{tid}/assets')
    def add_asset(tid:str,body:Asset,request:Request):
        with module.database() as db:
            uid=auth(request,db,True);member(db,tid,uid,('owner','stock'))
            if db.execute('SELECT 1 FROM it_assets WHERE team=? AND tag=?',(tid,body.tag)).fetchone():fail(409,'Asset tag already exists in this team.')
            if db.execute('SELECT count(*) FROM it_assets WHERE team=?',(tid,)).fetchone()[0]>=1000:fail(409,'Local inventory limit reached.')
            aid=str(uuid.uuid4());db.execute('INSERT INTO it_assets VALUES (?,?,?,?,?,?,?,NULL,1)',(aid,tid,body.tag,body.sku,body.location,int(body.usable),'available' if body.usable else 'service'));event(db,tid,uid,'Asset added: '+body.tag)
            return {'id':aid}
    @app.post('/api/it/{tid}/assets/{aid}')
    def update_asset(tid:str,aid:str,body:AssetState,request:Request):
        with module.database() as db:
            uid=auth(request,db,True);member(db,tid,uid,('owner','stock'))
            a=db.execute('SELECT * FROM it_assets WHERE team=? AND id=?',(tid,aid)).fetchone()
            if not a:fail(404,'Asset not found.')
            version(a,body.revision)
            if a['state'] in ('reserved','assigned'):fail(409,'Reserved or assigned equipment cannot be edited as available stock.')
            if body.state=='available' and not body.usable:fail(422,'Available equipment must be checked usable.')
            db.execute('UPDATE it_assets SET state=?,usable=?,revision=revision+1 WHERE id=?',(body.state,int(body.usable),aid));event(db,tid,uid,'Asset state: '+a['tag']+' / '+body.state)
            return {'ok':True}
    @app.post('/api/it/{tid}/quotes')
    def quote(tid:str,body:Quote,request:Request):
        with module.database() as db:
            uid=auth(request,db,True);member(db,tid,uid,('owner','stock'))
            if body.sku not in (DOCK,MONITOR):fail(422,'Supplier quotes are supported for the reviewed dock and display bundles only.')
            if not time.time()<body.valid_until<=time.time()+30*DAY:fail(422,'Use a fixed quote expiry within the next 30 days.')
            old=db.execute('SELECT revision FROM it_quotes WHERE team=? AND sku=?',(tid,body.sku)).fetchone()
            if body.revision!=(old['revision'] if old else 0):fail(409,'The supplier quote changed. Refresh before saving.')
            db.execute('INSERT INTO it_quotes VALUES (?,?,?,1) ON CONFLICT(team,sku) DO UPDATE SET data=excluded.data,revision=it_quotes.revision+1',(tid,body.sku,json.dumps(body.model_dump(exclude={'revision'}))));event(db,tid,uid,'Supplier quote updated: '+body.sku)
            return {'ok':True}
    @app.post('/api/it/{tid}/assets/{aid}/return')
    def return_asset(tid:str,aid:str,body:ReturnAsset,request:Request):
        with module.database() as db:
            uid=auth(request,db,True);member(db,tid,uid,('owner','stock'))
            a=db.execute('SELECT * FROM it_assets WHERE team=? AND id=?',(tid,aid)).fetchone()
            if not a:fail(404,'Asset not found.')
            version(a,body.revision)
            if a['state']!='assigned':fail(409,'Only assigned equipment can be returned. Active reservations must be cancelled by the requester.')
            # A return is not proof of working condition. Quarantine it until a
            # separate stock check explicitly makes the asset usable again.
            db.execute("UPDATE it_assets SET state='service',usable=0,request_id=NULL,location=?,revision=revision+1 WHERE id=?",(body.location,aid))
            event(db,tid,uid,'Returned '+a['tag']+' for condition check: '+body.reason,a['request_id'])
            return {'ok':True}
    @app.post('/api/it/{tid}/requests')
    def create_request(tid:str,body:Need,request:Request):
        with module.database() as db:
            uid=auth(request,db,True);member(db,tid,uid,('owner','requester'))
            if db.execute('SELECT count(*) FROM it_requests WHERE team=?',(tid,)).fetchone()[0]>=1000:fail(409,'Local request limit reached.')
            rid=str(uuid.uuid4());db.execute("INSERT INTO it_requests VALUES (?,?,?,'draft',1,?,NULL,NULL,NULL,?)",(rid,tid,uid,body.model_dump_json(),time.time()));event(db,tid,uid,'Draft created',rid)
            return view(db,request_row(db,tid,rid))
    @app.post('/api/it/{tid}/requests/{rid}/revise')
    def revise(tid:str,rid:str,body:Revise,request:Request):
        with module.database() as db:
            uid=auth(request,db,True);member(db,tid,uid);row=request_row(db,tid,rid);version(row,body.revision);editable(row,uid)
            db.execute("UPDATE it_requests SET data=?,state='draft',snapshot=NULL,approver=NULL,expires=NULL,revision=revision+1 WHERE id=?",(json.dumps(body.model_dump(exclude={'revision'})),rid));event(db,tid,uid,'Draft revised; previous approval not retained',rid)
            return view(db,request_row(db,tid,rid))
    @app.post('/api/it/{tid}/requests/{rid}/quantity')
    def quantity(tid:str,rid:str,body:Quantity,request:Request):
        with module.database() as db:
            uid=auth(request,db,True);member(db,tid,uid,('owner','requester'));row=request_row(db,tid,rid);version(row,body.revision)
            if row['author']!=uid:fail(403,'Only this setup’s requester can change its quantities.')
            if row['state'] in ('ordered','fulfilled'):fail(409,'Ordered equipment needs purchasing review.')
            need=json.loads(row['data']);need['screens']=body.screens
            if row['state'] in ('submitted','approved'):
                if not body.replace_approved:fail(409,'Confirm replacement of this reviewed request first.')
                if db.execute('SELECT count(*) FROM it_requests WHERE team=?',(tid,)).fetchone()[0]>=1000:fail(409,'Local request limit reached.')
                replacement=str(uuid.uuid4());release(db,rid)
                db.execute("UPDATE it_requests SET state='cancelled',revision=revision+1 WHERE id=?",(rid,))
                need['configuration_checked']=False;need['it_readiness_checked']=False
                db.execute("INSERT INTO it_requests VALUES (?,?,?,'draft',1,?,NULL,NULL,NULL,?)",(replacement,tid,uid,json.dumps(need),time.time()))
                event(db,tid,uid,'Replaced by draft '+replacement+'; prior approval retained as history',rid);event(db,tid,uid,'Quantity revision of '+rid,replacement)
                return view(db,request_row(db,tid,replacement))
            db.execute("UPDATE it_requests SET data=?,state='draft',snapshot=NULL,approver=NULL,expires=NULL,revision=revision+1 WHERE id=?",(json.dumps(need),rid));event(db,tid,uid,'Display quantity changed; review required',rid)
            return view(db,request_row(db,tid,rid))
    @app.post('/api/it/{tid}/requests/{rid}/submit')
    def submit(tid:str,rid:str,body:Submit,request:Request):
        with module.database() as db:
            uid=auth(request,db,True);member(db,tid,uid,('owner','requester'));row=request_row(db,tid,rid);version(row,body.revision);editable(row,uid)
            p=plan(db,row)
            if not p['ready']:fail(409,'Resolve the compatibility, stock, quote and budget checks first.')
            if not secrets.compare_digest(p['fingerprint'],body.fingerprint):fail(409,'The displayed plan changed. Review it again.')
            for a in p['reuse']:
                changed=db.execute("UPDATE it_assets SET state='reserved',request_id=?,revision=revision+1 WHERE id=? AND state='available' AND usable=1",(rid,a['id'])).rowcount
                if changed!=1:fail(409,'Stock was reserved by another request. Refresh the plan.')
            db.execute("UPDATE it_requests SET state='submitted',revision=revision+1,snapshot=?,expires=? WHERE id=?",(json.dumps(p),p['expires'],rid));event(db,tid,uid,'Submitted; exact stock reserved for at most 24 hours',rid)
            return view(db,request_row(db,tid,rid))
    @app.post('/api/it/{tid}/requests/{rid}/decide')
    def decide(tid:str,rid:str,body:Decide,request:Request):
        with module.database() as db:
            uid=auth(request,db,True);member(db,tid,uid,('owner','approver'));row=request_row(db,tid,rid);version(row,body.revision)
            if row['author']==uid:fail(403,'A different person must review the request.')
            if row['state']!='submitted':fail(409,'Only a submitted request can be reviewed.')
            p=plan(db,row);old=json.loads(row['snapshot'])
            if body.decision=='approve' and (not p['ready'] or body.fingerprint!=p['fingerprint'] or old['fingerprint']!=p['fingerprint']):fail(409,'Evidence, price or stock changed. Requester must cancel and submit a reviewed plan.')
            state='approved' if body.decision=='approve' else 'rejected'
            if state=='rejected':release(db,rid)
            db.execute('UPDATE it_requests SET state=?,approver=?,revision=revision+1 WHERE id=?',(state,uid,rid));event(db,tid,uid,state.title()+': '+body.reason,rid)
            return view(db,request_row(db,tid,rid))
    @app.post('/api/it/{tid}/requests/{rid}/cancel')
    def cancel(tid:str,rid:str,body:Version,request:Request):
        with module.database() as db:
            uid=auth(request,db,True);role=member(db,tid,uid);row=request_row(db,tid,rid);version(row,body.revision)
            if row['author']!=uid and role!='owner':fail(403,'Only the requester or team owner can cancel.')
            if row['state'] not in ('draft','submitted','approved'):fail(409,'This request cannot be cancelled; ordered equipment needs purchasing review.')
            release(db,rid);db.execute("UPDATE it_requests SET state='cancelled',revision=revision+1 WHERE id=?",(rid,));event(db,tid,uid,'Cancelled; reserved stock released',rid)
            return view(db,request_row(db,tid,rid))
    @app.get('/api/it/{tid}/requests/{rid}/handoff')
    def handoff(tid:str,rid:str,request:Request):
        with module.database() as db:
            uid=auth(request,db);member(db,tid,uid);row=request_row(db,tid,rid);v=view(db,row)
            if row['state']!='approved' or not v['approval_current']:fail(409,'A current, independently approved request is required.')
            v['notice']='Purchasing handoff only. No supplier order, PayPal payment, physical test or delivery has been performed.'
            return JSONResponse(v,headers={'Content-Disposition':'attachment; filename="intentcart-approved-purchase.json"'})
    @app.post('/api/it/{tid}/requests/{rid}/ordered')
    def ordered(tid:str,rid:str,body:Ordered,request:Request):
        with module.database() as db:
            uid=auth(request,db,True);member(db,tid,uid,('owner','approver'));row=request_row(db,tid,rid);version(row,body.revision);v=view(db,row)
            if row['state']!='approved' or not v['approval_current'] or body.fingerprint!=v['plan']['fingerprint']:fail(409,'A current approval is required before recording an external order.')
            s=json.loads(row['snapshot']);s['external_order_reference']=body.reference
            db.execute("UPDATE it_requests SET state='ordered',snapshot=?,revision=revision+1 WHERE id=?",(json.dumps(s),rid));event(db,tid,uid,'External order recorded by operator: '+body.reference,rid)
            return view(db,request_row(db,tid,rid))
    @app.post('/api/it/{tid}/requests/{rid}/receive')
    def receive(tid:str,rid:str,body:Receive,request:Request):
        with module.database() as db:
            uid=auth(request,db,True);member(db,tid,uid,('owner','stock'));row=request_row(db,tid,rid);version(row,body.revision)
            if row['state']!='ordered':fail(409,'Record the external order first.')
            s=json.loads(row['snapshot']);skus=[l['sku'] for l in s['purchase'] for _ in range(l['quantity'])]
            tags=[t.strip() for t in body.tags]
            if len(tags)!=len(skus) or len(set(tags))!=len(tags) or any(not t or len(t)>64 or any(ord(c)<32 for c in t) for t in tags):fail(422,'Enter one unique new asset tag per purchased unit.')
            if any(db.execute('SELECT 1 FROM it_assets WHERE team=? AND tag=?',(tid,t)).fetchone() for t in tags):fail(409,'An incoming asset tag already exists.')
            for sku,tag in zip(skus,tags):db.execute("INSERT INTO it_assets VALUES (?,?,?,?,?,1,'assigned',?,1)",(str(uuid.uuid4()),tid,tag,sku,json.loads(row['data'])['location'],rid))
            db.execute("UPDATE it_assets SET state='assigned',revision=revision+1 WHERE request_id=? AND state='reserved'",(rid,))
            db.execute("UPDATE it_requests SET state='fulfilled',revision=revision+1 WHERE id=?",(rid,));event(db,tid,uid,'Receipt and condition recorded by operator; equipment assigned',rid)
            return view(db,request_row(db,tid,rid))
