"""Single-instance account and tenant-owned CRM service. No paid identity/email API.

Passwords use stdlib scrypt (N=2**17,r=8,p=1), opaque revocable sessions,
exact-Origin + per-session CSRF, bounded durable throttles and explicit invites.
Recovery uses a one-time 256-bit saved key; no email ownership is claimed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import uuid
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from typing import Literal

COOKIE='intentcart_account'
PREAUTH='intentcart_signin'
TTL=7*86400
IDLE=86400
HASH_SLOTS=threading.BoundedSemaphore(2)
USERNAME=re.compile(r'[a-z0-9][a-z0-9_.-]{2,31}\Z')
PUBLIC_APIS={'/api/account','/api/account/security','/api/account/register','/api/account/login','/api/account/recover'}
AI_PATHS={'/api/agent/model-step','/api/missions/model-interpret','/api/agent/research/intake','/api/agent/research/model-brief','/api/discover'}

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
class Credentials(Strict):
    username: str=Field(max_length=32)
    password: SecretStr
class Signup(Credentials):
    name: str=Field(min_length=1,max_length=80)
    invite: str=Field(default='',max_length=100)
class Recovery(Strict):
    username: str=Field(max_length=32)
    recovery_key: SecretStr
    password: SecretStr
class Profile(Strict):
    name: str=Field(min_length=1,max_length=80)
    revision: int=Field(ge=1)
class Password(Strict):
    current_password: SecretStr
    password: SecretStr
class ClaimInvite(Strict):
    password:str=Field(min_length=1,max_length=128)
    invite:str=Field(min_length=20,max_length=300)
class Confirm(Strict):
    password: SecretStr
class Contact(Strict):
    name: str=Field(min_length=1,max_length=80)
    company: str=Field(default='',max_length=80)
    email: str=Field(default='',max_length=254)
    phone: str=Field(default='',max_length=48)
    stage: Literal['new','planning','ready','archived']='new'
    notes: str=Field(default='',max_length=2000)
class EditContact(Contact):
    revision: int=Field(ge=1)
class AdminEdit(Strict):
    revision: int=Field(ge=1)
    active: bool
    ai_access: bool
    password: SecretStr

def enabled():return os.getenv('INTENTCART_AUTH')=='accounts'
def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def clean(value):
    if any(ord(c)<32 and c not in '\n\t' for c in value):raise HTTPException(422,'Please remove control characters.')
    return value.strip()
def display_name(value):
    value=clean(value)
    if not value:raise HTTPException(422,'Please enter your name.')
    return value

def username(value):
    value=value.strip().lower()
    if not USERNAME.fullmatch(value):raise HTTPException(422,'Use 3–32 letters, numbers, dots, dashes or underscores for your username.')
    return value
def password_value(value):
    value=value.get_secret_value() if isinstance(value,SecretStr) else value
    if not 15<=len(value)<=128 or len(value.encode())>512:raise HTTPException(422,'Use a password with 15–128 characters.')
    if value.lower() in {'passwordpassword','passwordpassword123','123456789012345','qwertyqwertyqwerty'}:raise HTTPException(422,'Please choose a less common password.')
    return value

def derive(password,salt):
    if not HASH_SLOTS.acquire(blocking=False):raise HTTPException(429,'Sign-in is busy. Please try again shortly.')
    try:return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=131072,r=8,p=1,maxmem=192*1024*1024,dklen=32).hex()
    finally:HASH_SLOTS.release()
def hash_password(value):
    salt=secrets.token_hex(16)
    return 'scrypt$131072$8$1$'+salt+'$'+derive(password_value(value),salt)
def verify(value,stored):
    raw=value.get_secret_value() if isinstance(value,SecretStr) else value
    raw=raw if isinstance(raw,str) and len(raw)<=128 and len(raw.encode())<=512 else ''
    if stored:
        parts=stored.split('$');salt=parts[4];expected=parts[5]
    else:salt='0'*32;expected='0'*64
    return secrets.compare_digest(derive(raw,salt),expected) and stored is not None

def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS accounts (
      id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
      password TEXT NOT NULL, recovery TEXT NOT NULL, workspace TEXT UNIQUE NOT NULL REFERENCES sessions(id),
      role TEXT NOT NULL CHECK(role IN ('member','admin')), active INTEGER NOT NULL DEFAULT 1,
      ai_access INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS account_sessions (
      token TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), csrf TEXT NOT NULL,
      created REAL NOT NULL, seen REAL NOT NULL, expires REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS account_sessions_owner ON account_sessions(account_id);
    CREATE TABLE IF NOT EXISTS signin_tokens (token TEXT PRIMARY KEY,csrf TEXT NOT NULL,expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS account_rates (key TEXT PRIMARY KEY, bucket INTEGER NOT NULL,count INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS account_invites (token TEXT PRIMARY KEY,role TEXT NOT NULL,ai_access INTEGER NOT NULL,expires REAL NOT NULL,used INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS customers (
      id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES accounts(id), data TEXT NOT NULL,
      revision INTEGER NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS customers_owner ON customers(owner,updated);
    CREATE TABLE IF NOT EXISTS account_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,owner TEXT NOT NULL,event TEXT NOT NULL,created REAL NOT NULL);
    ''')
    # Optional operator-approved bootstrap is a fixed, hashed, one-use invitation.
    # A restart cannot extend its deadline or revive a consumed invitation.
    token_hash=os.getenv('INTENTCART_OPERATOR_INVITE_SHA256','')
    if token_hash:
        if not re.fullmatch(r'[a-f0-9]{64}',token_hash):raise ValueError('Invalid operator invitation fingerprint')
        try:expires=int(os.environ['INTENTCART_OPERATOR_INVITE_EXPIRES'])
        except (KeyError,ValueError):raise ValueError('A fixed operator invitation expiry is required') from None
        if time.time()<expires:
            db.execute('INSERT OR IGNORE INTO account_invites VALUES (?,?,?,?,0)',(token_hash,'admin',int(os.getenv('INTENTCART_OPERATOR_AI_ACCESS')=='true'),expires))

def throttle(db,key,limit,window):
    bucket=int(time.time())//window;key=digest(key)
    row=db.execute('SELECT bucket,count FROM account_rates WHERE key=?',(key,)).fetchone()
    count=(row['count'] if row and row['bucket']==bucket else 0)+1
    db.execute('INSERT INTO account_rates VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET bucket=excluded.bucket,count=excluded.count',(key,bucket,count))
    return count<=limit

def event(db,uid,kind):
    db.execute('INSERT INTO account_events(owner,event,created) VALUES (?,?,?)',(uid,kind,time.time()))
    db.execute('DELETE FROM account_events WHERE owner=? AND id NOT IN (SELECT id FROM account_events WHERE owner=? ORDER BY id DESC LIMIT 30)',(uid,uid))

def public(row):
    return {k:row[k] for k in ('id','username','name','role','active','ai_access','revision','created')}

def current(request,db,mutation=False):
    token=request.cookies.get(COOKIE,'')
    if len(token)>100:raise HTTPException(401,'Please sign in to IntentCart.')
    now=time.time()
    row=db.execute('SELECT a.*,s.csrf,s.token AS session_token FROM accounts a JOIN account_sessions s ON s.account_id=a.id WHERE s.token=? AND s.expires>? AND s.seen>? AND a.active=1',(digest(token),now,now-IDLE)).fetchone()
    if row is None:raise HTTPException(401,'Please sign in to IntentCart.')
    if mutation and not secrets.compare_digest(row['csrf'],request.headers.get('x-csrf-token','')):raise HTTPException(403,'Refresh the page before trying again.')
    if mutation and request.headers.get('origin')!=__import__('intentcart.config',fromlist=['PUBLIC_URL']).PUBLIC_URL:raise HTTPException(403,'Request origin is not allowed.')
    db.execute('UPDATE account_sessions SET seen=? WHERE token=?',(now,row['session_token']))
    db.execute('UPDATE sessions SET expires=? WHERE id=?',(now+TTL,row['workspace']))
    return row

def preauth(request,db):
    token=request.cookies.get(PREAUTH,'')
    row=db.execute('SELECT csrf FROM signin_tokens WHERE token=? AND expires>?',(digest(token),time.time())).fetchone() if len(token)<=100 else None
    if not row or not secrets.compare_digest(row['csrf'],request.headers.get('x-csrf-token','')):raise HTTPException(403,'Refresh the sign-in page before trying again.')

def issue(db,uid,secure,recovery=None):
    now=time.time();token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
    db.execute('DELETE FROM account_sessions WHERE expires<? OR seen<?',(now,now-IDLE))
    db.execute('DELETE FROM account_sessions WHERE account_id=? AND token NOT IN (SELECT token FROM account_sessions WHERE account_id=? ORDER BY created DESC LIMIT 9)',(uid,uid))
    db.execute('INSERT INTO account_sessions VALUES (?,?,?,?,?,?)',(digest(token),uid,csrf,now,now,now+TTL))
    row=db.execute('SELECT * FROM accounts WHERE id=?',(uid,)).fetchone()
    response=JSONResponse({'user':public(row),'csrf_token':csrf,**({'recovery_key':recovery} if recovery else {})})
    response.set_cookie(COOKIE,token,httponly=True,secure=secure,samesite='lax',max_age=TTL,path='/')
    response.delete_cookie('intentcart_session',path='/');return response

def bind(request,module):
    if not enabled():return None
    if not request.url.path.startswith('/api/') or request.url.path in PUBLIC_APIS:return None
    try:
        with module.database() as db:
            row=current(request,db,request.method not in ('GET','HEAD','OPTIONS'))
            request.scope['intentcart_account']=public(row)
            request.scope['intentcart_account_workspace']=row['workspace']
            request.scope['intentcart_account_csrf']=row['csrf']
            request.scope['intentcart_auth_subject']='account:'+row['id']
            # New accounts cannot spend the owner's five remaining shared actions.
            path=request.url.path
            if request.method=='POST' and not row['ai_access'] and (path in AI_PATHS or path=='/api/agent/research/advance' and json.loads(db.execute('SELECT state FROM sessions WHERE id=?',(row['workspace'],)).fetchone()['state']).get('research_run',{}).get('options',{}).get('engine') not in ('local','trained') or path.endswith('/ask') and path.startswith('/api/documents/')):
                return JSONResponse({'detail':'AI access is available by invitation. You can still use the planner and customer workspace.'},status_code=403)
    except HTTPException as exc:return JSONResponse({'detail':exc.detail},status_code=exc.status_code)
    return None

def register(module):
    app=module.app
    def available():
        if not enabled():raise HTTPException(404,'Accounts are not enabled on this installation.')
    def auth_limit(request,action,name=''):
        ip=request.client.host if request.client else 'unknown'
        with module.database() as db:
            ok=throttle(db,'auth:'+ip,15,60)&throttle(db,'auth-global',120,60)
            if name:ok=throttle(db,'user:'+digest(name),8,900)&ok
            if action=='register':ok=throttle(db,'signup:'+ip,10,3600)&ok
            if db.execute('SELECT count(*) FROM account_rates').fetchone()[0]>6000:
                db.execute('DELETE FROM account_rates WHERE rowid IN (SELECT rowid FROM account_rates LIMIT 1000)')
        if not ok:raise HTTPException(429,'Too many sign-in attempts. Please wait before trying again.')
    def account(request,db,mutation=False,admin=False):
        available();row=current(request,db,mutation)
        if admin and row['role']!='admin':raise HTTPException(403,'Only the workspace operator can manage accounts.')
        return row

    @app.get('/login')
    @app.get('/account')
    @app.get('/customers')
    def page():return FileResponse(module.ROOT/'web/accounts.html')
    @app.get('/privacy')
    def privacy():return FileResponse(module.ROOT/'web/privacy.html')

    @app.get('/api/account')
    def status(request:Request):
        if not enabled():return {'enabled':False,'user':None}
        with module.database() as db:
            try:row=current(request,db)
            except HTTPException:return {'enabled':True,'user':None}
            return {'enabled':True,'user':public(row),'csrf_token':row['csrf'],'sessions':db.execute('SELECT count(*) FROM account_sessions WHERE account_id=? AND expires>? AND seen>?',(row['id'],time.time(),time.time()-IDLE)).fetchone()[0]}

    @app.get('/api/account/security')
    def security(request:Request):
        available();auth_limit(request,'bootstrap')
        with module.database() as db:
            db.execute('DELETE FROM signin_tokens WHERE expires<?',(time.time(),))
            if db.execute('SELECT count(*) FROM signin_tokens').fetchone()[0]>=2000:raise HTTPException(429,'Please try again later.')
            token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
            db.execute('INSERT INTO signin_tokens VALUES (?,?,?)',(digest(token),csrf,time.time()+1800))
        response=JSONResponse({'csrf_token':csrf});response.set_cookie(PREAUTH,token,httponly=True,secure=module.config.COOKIE_SECURE,samesite='lax',max_age=1800,path='/');return response

    @app.post('/api/account/register')
    def signup(body:Signup,request:Request):
        available();name=username(body.username);auth_limit(request,'register',name)
        with module.database() as db:preauth(request,db)
        hashed=hash_password(body.password);key='IC-'+secrets.token_urlsafe(32)
        with module.database() as db:
            preauth(request,db)
            if db.execute('SELECT count(*) FROM accounts').fetchone()[0]>=1000:raise HTTPException(409,'Registration is currently full.')
            invite=None
            if body.invite:
                invite=db.execute('SELECT * FROM account_invites WHERE token=? AND used=0 AND expires>?',(digest(body.invite),time.time())).fetchone()
                if not invite:raise HTTPException(409,'That invitation is unavailable or expired.')
            uid=uuid.uuid4().hex;sid=secrets.token_hex(32);state=module.fresh_state();state['_auth_subject']='account:'+uid
            try:
                db.execute('INSERT INTO sessions VALUES (?,?,?,?)',(sid,secrets.token_urlsafe(32),json.dumps(state),time.time()+TTL))
                db.execute('INSERT INTO accounts(id,username,name,password,recovery,workspace,role,ai_access,created) VALUES (?,?,?,?,?,?,?,?,?)',(uid,name,display_name(body.name),hashed,digest(key),sid,invite['role'] if invite else 'member',invite['ai_access'] if invite else 0,time.time()))
            except sqlite3.IntegrityError:raise HTTPException(409,'That username is unavailable. Please choose another.') from None
            if invite:db.execute('UPDATE account_invites SET used=1 WHERE token=?',(invite['token'],))
            db.execute('DELETE FROM signin_tokens WHERE token=?',(digest(request.cookies.get(PREAUTH,'')),))
            event(db,uid,'Account created');return issue(db,uid,module.config.COOKIE_SECURE,key)

    @app.post('/api/account/login')
    def login(body:Credentials,request:Request):
        available();name=username(body.username);auth_limit(request,'login',name)
        with module.database() as db:
            preauth(request,db);row=db.execute('SELECT * FROM accounts WHERE username=?',(name,)).fetchone();stored=row['password'] if row else None
        valid=verify(body.password,stored)
        with module.database() as db:
            row=db.execute('SELECT * FROM accounts WHERE username=?',(name,)).fetchone()
            if not valid or not row or row['password']!=stored or not row['active']:raise HTTPException(401,'Username or password was not accepted.')
            db.execute('DELETE FROM signin_tokens WHERE token=?',(digest(request.cookies.get(PREAUTH,'')),));event(db,row['id'],'Signed in');return issue(db,row['id'],module.config.COOKIE_SECURE)

    @app.post('/api/account/recover')
    def recover(body:Recovery,request:Request):
        available();name=username(body.username);auth_limit(request,'recover',name)
        with module.database() as db:
            preauth(request,db);row=db.execute('SELECT * FROM accounts WHERE username=?',(name,)).fetchone()
            valid=bool(row and row['active'] and secrets.compare_digest(row['recovery'],digest(body.recovery_key.get_secret_value())))
        hashed=hash_password(body.password)
        if not valid:raise HTTPException(401,'Username or recovery key was not accepted.')
        key='IC-'+secrets.token_urlsafe(32)
        with module.database() as db:
            preauth(request,db)
            result=db.execute('UPDATE accounts SET password=?,recovery=?,revision=revision+1 WHERE id=? AND recovery=? AND active=1',(hashed,digest(key),row['id'],row['recovery']))
            if result.rowcount!=1:raise HTTPException(409,'That recovery key was already used.')
            db.execute('DELETE FROM account_sessions WHERE account_id=?',(row['id'],));db.execute('DELETE FROM signin_tokens WHERE token=?',(digest(request.cookies.get(PREAUTH,'')),));event(db,row['id'],'Recovered account; all sessions revoked');return issue(db,row['id'],module.config.COOKIE_SECURE,key)

    @app.post('/api/account/invitation')
    def claim_invitation(body:ClaimInvite,request:Request):
        auth_limit(request,'invitation')
        with module.database() as db:row=account(request,db,True);old=row['password']
        if not verify(body.password,old):raise HTTPException(403,'Current password was not accepted.')
        with module.database() as db:
            row=account(request,db,True)
            if row['password']!=old:raise HTTPException(409,'Account changed. Sign in again.')
            invite=db.execute('SELECT * FROM account_invites WHERE token=? AND used=0 AND expires>?',(digest(body.invite),time.time())).fetchone()
            if not invite:raise HTTPException(403,'Invitation is invalid, expired or already used.')
            if db.execute('UPDATE account_invites SET used=1 WHERE token=? AND used=0',(invite['token'],)).rowcount!=1:raise HTTPException(409,'Invitation was already used.')
            db.execute('UPDATE accounts SET role=?,ai_access=?,revision=revision+1 WHERE id=?',(invite['role'],invite['ai_access'],row['id']))
            db.execute('DELETE FROM account_sessions WHERE account_id=?',(row['id'],));event(db,row['id'],'Applied operator invitation; previous sessions revoked')
            return issue(db,row['id'],module.config.COOKIE_SECURE)

    @app.post('/api/account/logout')
    def logout(request:Request):
        with module.database() as db:
            row=account(request,db,True);db.execute('DELETE FROM account_sessions WHERE token=?',(row['session_token'],))
        response=JSONResponse({'signed_out':True});response.delete_cookie(COOKIE,path='/');response.delete_cookie('intentcart_session',path='/');return response
    @app.post('/api/account/logout-all')
    def logout_all(request:Request):
        with module.database() as db:
            row=account(request,db,True);db.execute('DELETE FROM account_sessions WHERE account_id=?',(row['id'],));event(db,row['id'],'Signed out all devices')
        response=JSONResponse({'signed_out':True});response.delete_cookie(COOKIE,path='/');return response
    @app.post('/api/account/profile')
    def profile(body:Profile,request:Request):
        with module.database() as db:
            row=account(request,db,True)
            if db.execute('UPDATE accounts SET name=?,revision=revision+1 WHERE id=? AND revision=?',(display_name(body.name),row['id'],body.revision)).rowcount!=1:raise HTTPException(409,'Profile changed. Refresh before saving.')
        return {'saved':True}
    @app.post('/api/account/password')
    def password(body:Password,request:Request):
        auth_limit(request,'password')
        with module.database() as db:row=account(request,db,True);old=row['password']
        if not verify(body.current_password,old):raise HTTPException(401,'Current password was not accepted.')
        hashed=hash_password(body.password);key='IC-'+secrets.token_urlsafe(32)
        with module.database() as db:
            row=account(request,db,True)
            if db.execute('UPDATE accounts SET password=?,recovery=?,revision=revision+1 WHERE id=? AND password=?',(hashed,digest(key),row['id'],old)).rowcount!=1:raise HTTPException(409,'Account changed. Please sign in again.')
            db.execute('DELETE FROM account_sessions WHERE account_id=?',(row['id'],));event(db,row['id'],'Changed password; all previous sessions revoked');return issue(db,row['id'],module.config.COOKIE_SECURE,key)
    @app.post('/api/account/deactivate')
    def deactivate(body:Confirm,request:Request):
        auth_limit(request,'deactivate')
        with module.database() as db:row=account(request,db,True);old=row['password']
        if not verify(body.password,old):raise HTTPException(401,'Current password was not accepted.')
        with module.database() as db:
            row=account(request,db,True)
            if row['role']=='admin':raise HTTPException(409,'Operators must arrange an account handover before deactivation.')
            db.execute('UPDATE accounts SET active=0,revision=revision+1 WHERE id=? AND password=?',(row['id'],old));db.execute('DELETE FROM account_sessions WHERE account_id=?',(row['id'],));event(db,row['id'],'Deactivated account')
        response=JSONResponse({'deactivated':True});response.delete_cookie(COOKIE,path='/');return response

    @app.get('/api/customers')
    def customers(request:Request,q:str='',stage:str=''):
        with module.database() as db:
            row=account(request,db);items=[{**json.loads(r['data']),'id':r['id'],'revision':r['revision'],'created':r['created'],'updated':r['updated']} for r in db.execute('SELECT * FROM customers WHERE owner=? ORDER BY updated DESC LIMIT 100',(row['id'],))]
        term=q[:100].strip().casefold();filtered=[c for c in items if (not stage or c['stage']==stage) and (not term or term in ' '.join(c[k] for k in ('name','company','email','notes')).casefold())]
        return {'customers':filtered,'counts':{s:sum(c['stage']==s for c in items) for s in ('new','planning','ready','archived')},'total':len(items)}
    def contact_data(body):
        data={k:clean(v) for k,v in body.model_dump().items() if k!='revision'}
        if not data['name']:raise HTTPException(422,'Customer name is required.')
        if data['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',data['email']):raise HTTPException(422,'Please enter a valid contact email or leave it empty.')
        return json.dumps(data)
    @app.post('/api/customers')
    def create_customer(body:Contact,request:Request):
        data=contact_data(body)
        with module.database() as db:
            row=account(request,db,True)
            if db.execute('SELECT count(*) FROM customers WHERE owner=?',(row['id'],)).fetchone()[0]>=100:raise HTTPException(409,'This workspace is limited to 100 customer records.')
            cid=uuid.uuid4().hex;now=time.time();db.execute('INSERT INTO customers VALUES (?,?,?,?,?,?)',(cid,row['id'],data,1,now,now));event(db,row['id'],'Created customer record')
        return {'id':cid,'revision':1}
    @app.post('/api/customers/{customer_id}')
    def edit_customer(customer_id:str,body:EditContact,request:Request):
        data=contact_data(body)
        with module.database() as db:
            row=account(request,db,True)
            result=db.execute('UPDATE customers SET data=?,revision=revision+1,updated=? WHERE id=? AND owner=? AND revision=?',(data,time.time(),customer_id,row['id'],body.revision))
            if result.rowcount!=1:
                if not db.execute('SELECT 1 FROM customers WHERE id=? AND owner=?',(customer_id,row['id'])).fetchone():raise HTTPException(404,'Customer not found in this workspace.')
                raise HTTPException(409,'Customer changed. Refresh before saving.')
            event(db,row['id'],'Updated customer record')
        return {'saved':True}
    @app.get('/api/account/export')
    def export(request:Request):
        with module.database() as db:
            row=account(request,db);items=[{**json.loads(r['data']),'id':r['id'],'revision':r['revision']} for r in db.execute('SELECT * FROM customers WHERE owner=?',(row['id'],))];events=[dict(r) for r in db.execute('SELECT event,created FROM account_events WHERE owner=? ORDER BY id DESC LIMIT 30',(row['id'],))]
        return JSONResponse({'schema':'intentcart-workspace/1','profile':public(row),'customers':items,'activity':events,'notice':'Private customer records. No passwords, recovery keys, session tokens or other accounts. Contact details are user-entered and unverified.'},headers={'Content-Disposition':'attachment; filename="intentcart-workspace.json"'})
    @app.get('/api/account/activity')
    def activity(request:Request):
        with module.database() as db:
            row=account(request,db);return {'events':[dict(r) for r in db.execute('SELECT event,created FROM account_events WHERE owner=? ORDER BY id DESC LIMIT 30',(row['id'],))]}
    @app.get('/api/admin/accounts')
    def admin_accounts(request:Request):
        with module.database() as db:account(request,db,admin=True);return {'accounts':[public(r) for r in db.execute('SELECT * FROM accounts ORDER BY created DESC LIMIT 1000')]}
    @app.post('/api/admin/accounts/{account_id}')
    def admin_edit(account_id:str,body:AdminEdit,request:Request):
        auth_limit(request,'admin')
        with module.database() as db:row=account(request,db,True,True);old=row['password']
        if not verify(body.password,old):raise HTTPException(401,'Current password was not accepted.')
        with module.database() as db:
            operator=account(request,db,True,True)
            target=db.execute('SELECT * FROM accounts WHERE id=?',(account_id,)).fetchone()
            if not target:raise HTTPException(404,'Account not found.')
            if target['role']=='admin' and not body.active:raise HTTPException(409,'Operator accounts cannot be disabled here.')
            if db.execute('UPDATE accounts SET active=?,ai_access=?,revision=revision+1 WHERE id=? AND revision=?',(int(body.active),int(body.ai_access),account_id,body.revision)).rowcount!=1:raise HTTPException(409,'Account changed. Refresh before saving.')
            if not body.active:db.execute('DELETE FROM account_sessions WHERE account_id=?',(account_id,))
            event(db,operator['id'],'Updated account access');event(db,account_id,'Operator updated access')
        return {'saved':True,'notice':'AI access shares the existing fixed allowance; it does not add credits or requests.'}


def main():
    parser=argparse.ArgumentParser(description='Create an explicit one-use operator invitation on the existing local volume. Never publish invitations.')
    parser.add_argument('command',choices=['invite-admin']);parser.add_argument('--ai',action='store_true',help='Explicitly grant use of the existing shared AI allocation, without changing it.')
    args=parser.parse_args();from . import app
    app.initialize();token=secrets.token_urlsafe(32)
    with app.database() as db:
        db.execute('DELETE FROM account_invites WHERE expires<?',(time.time(),))
        db.execute('INSERT INTO account_invites VALUES (?,?,?,?,0)',(digest(token),'admin',int(args.ai),time.time()+86400))
    print(token)
if __name__=='__main__':main()
