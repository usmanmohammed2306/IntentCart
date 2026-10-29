"""Bounded onboarding what-if allocation. The original database is read only.
Deterministic request order, not a proof of globally minimum procurement cost.
"""
import copy,json,sqlite3
from pydantic import Field
from .workspace import Strict
from fastapi import Request,HTTPException
from . import procurement,accounts

def batch(db,tid):
 shadow=sqlite3.connect(':memory:');shadow.row_factory=sqlite3.Row
 # Copy only this team's business rows. Backing up a connection after the
 # authentication last-seen write can deadlock on its own transaction.
 shadow.execute('CREATE TABLE accounts(id TEXT PRIMARY KEY,active INTEGER NOT NULL)')
 shadow.executemany('INSERT INTO accounts VALUES (?,?)',[tuple(r) for r in db.execute('SELECT a.id,a.active FROM accounts a JOIN it_members m ON m.account=a.id WHERE m.team=?',(tid,))])
 for name,field,limit in [('it_teams','id',1),('it_members','team',1000),('it_assets','team',5000),('it_quotes','team',500),('it_requests','team',2000)]:
  rows=db.execute('SELECT * FROM '+name+' WHERE '+field+'=? LIMIT ?',(tid,limit+1)).fetchall()
  if len(rows)>limit:shadow.close();raise ValueError('This team exceeds the bounded batch planning size. Split the work into smaller teams.')
  shadow.execute(db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()[0])
  if rows:shadow.executemany('INSERT INTO '+name+' VALUES ('+','.join('?' for _ in rows[0])+')',[tuple(r) for r in rows])
 try:
  requests=shadow.execute("SELECT * FROM it_requests WHERE team=? AND state IN ('draft','rejected','cancelled') ORDER BY created,id LIMIT 21",(tid,)).fetchall()
  if len(requests)>20:raise ValueError('Review up to twenty pending setups per batch.')
  output=[];total=0;complete=True;assigned=set()
  for original in requests:
   row=dict(original);need=json.loads(row['data']);changes=[]
   requested=shadow.execute("SELECT * FROM it_assets WHERE id=? AND team=?",(need['laptop_asset'],tid)).fetchone()
   if requested and (requested['id'] in assigned or requested['state']!='available'):
    alt=shadow.execute("SELECT * FROM it_assets WHERE team=? AND sku=? AND location=? AND usable=1 AND state='available' ORDER BY tag,id LIMIT 1",(tid,procurement.LAPTOP,need['location'])).fetchone()
    if alt:need['laptop_asset']=alt['id'];changes.append('Use available laptop '+alt['tag']+' instead; requester must review.')
   row['data']=json.dumps(need);plan=procurement.plan(shadow,row)
   for asset in plan['reuse']:
    if asset['id'] in assigned:raise ValueError('Conflicting allocation detected; no real reservation was made.')
    assigned.add(asset['id']);shadow.execute("UPDATE it_assets SET state='reserved',request_id=? WHERE id=?",(row['id'],asset['id']))
   for line in plan['purchase']:
    quote=shadow.execute('SELECT data FROM it_quotes WHERE team=? AND sku=?',(tid,line['sku'])).fetchone()
    if quote:
     value=json.loads(quote['data']);value['available_units']=max(0,value['available_units']-line['quantity']);shadow.execute('UPDATE it_quotes SET data=? WHERE team=? AND sku=?',(json.dumps(value),tid,line['sku']))
   if plan['total_cents'] is None:complete=False
   else:total+=plan['total_cents']
   output.append({'request_id':row['id'],'proposed_need':need,'changes':changes,'plan':plan,'review_required':True})
  return {'requests':output,'reuse_count':len(assigned),'known_total_cents':total,'total_cents':total if complete else None,'scope':'Read-only sequential allocation over the team’s reviewed three-SKU catalog, current private assets and declared quotes. No reservation, approval, supplier order or global optimality. Each proposed change requires normal requester review and submission.'}
 finally:shadow.close()

class Comment(Strict):
 text:str=Field(min_length=1,max_length=1000)
 revision:int=Field(ge=1)
 client_id:str=Field(pattern=r'^[a-f0-9]{32}$')

def register(module):
 @module.app.post('/api/it/{tid}/requests/{rid}/comments')
 def comment(tid:str,rid:str,body:Comment,request:Request):
  with module.database() as db:
   uid=accounts.current(request,db,True)['id'];procurement.member(db,tid,uid);row=procurement.request_row(db,tid,rid);procurement.version(row,body.revision)
   if not body.text.strip():raise HTTPException(422,'Write a short message.')
   for event in db.execute('SELECT event FROM it_events WHERE team=? AND request_id=? AND actor=? ORDER BY id DESC LIMIT 100',(tid,rid,uid)):
    try:old=json.loads(event['event'])
    except (ValueError,TypeError):continue
    if old.get('type')=='comment' and old.get('id')==body.client_id:
     if old.get('text')!=body.text.strip():raise HTTPException(409,'That message ID was already used.')
     return {'saved':True}
   procurement.event(db,tid,uid,json.dumps({'type':'comment','id':body.client_id,'text':body.text.strip(),'revision':body.revision}),rid);return {'saved':True}

 @module.app.get('/api/it/{tid}/batch-plan')
 def preview(tid:str,request:Request):
  if not accounts.enabled():raise HTTPException(403,'Sign in to your team.')
  with module.database() as db:
   uid=accounts.current(request,db)['id'];procurement.member(db,tid,uid)
   try:return batch(db,tid)
   except ValueError as exc:raise HTTPException(422,str(exc)) from exc
