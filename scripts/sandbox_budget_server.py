"""Temporary local sandbox server with a durable API-call and exact-amount guard.

Default is a no-network dry run. Existing private app credentials are read by
the ordinary config loader. Model/discovery access is disabled in this process.
The ceiling counts server-side PayPal API requests, including OAuth/failures;
it cannot count PayPal's internal browser authentication/SDK traffic.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


class Ledger:
    def __init__(self,path,ceiling):
        if type(ceiling) is not int or not 1<=ceiling<=12:raise ValueError('Explicit sandbox ceiling must be 1..12.')
        self.path=Path(path);self.ceiling=ceiling
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, method TEXT, path TEXT, reserved_utc TEXT, status INTEGER)')
        self.path.chmod(0o600)

    def reserve(self,method,path):
        with sqlite3.connect(self.path,timeout=10) as db:
            db.execute('BEGIN IMMEDIATE')
            count=db.execute('SELECT COUNT(*) FROM requests').fetchone()[0]
            if count>=self.ceiling:raise RuntimeError('Approved PayPal API ceiling reached; reconcile existing outcomes, no retry sent.')
            row=db.execute('INSERT INTO requests (method,path,reserved_utc) VALUES (?,?,?)',
                           (method,path,datetime.now(timezone.utc).isoformat()))
            return row.lastrowid

    def record_status(self,index,status):
        with sqlite3.connect(self.path) as db:db.execute('UPDATE requests SET status=? WHERE id=?',(status,index))


def guard_request(request,total_cents):
    if request.url.scheme!='https' or request.url.host!='api-m.sandbox.paypal.com':
        raise RuntimeError('Only the PayPal sandbox API is allowed in this temporary server.')
    allowed=(request.method=='POST' and request.url.path=='/v1/oauth2/token') or request.url.path.startswith(('/v2/checkout/orders','/v2/payments/captures','/v2/payments/refunds'))
    if not allowed:raise RuntimeError('Endpoint is outside the approved sandbox validation flow.')
    if request.method=='POST' and request.url.path=='/v2/checkout/orders':
        payload=json.loads(request.content)
        units=payload.get('purchase_units',[])
        expected=f'{total_cents/100:.2f}'
        if len(units)!=1 or units[0].get('amount')!={'currency_code':'USD','value':expected}:
            raise RuntimeError('Order amount differs from the explicitly approved complete basket.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--port',type=int,default=4005)
    parser.add_argument('--max-api-calls',type=int,default=12)
    parser.add_argument('--approved-total-cents',type=int,default=27900)
    parser.add_argument('--database',type=Path,default=ROOT/'output/approved-sandbox-app.sqlite3')
    parser.add_argument('--ledger',type=Path,default=ROOT/'output/approved-sandbox-api-ledger.sqlite3')
    args=parser.parse_args()
    if not args.execute:
        print(json.dumps({'mode':'dry_run','provider_requests':0,'maximum_server_api_requests':args.max_api_calls,
                          'approved_total_cents':args.approved_total_cents,'permanent_env_changed':False}))
        return 0
    if not 1024<=args.port<=65535 or args.approved_total_cents!=27900:parser.error('Use a local port and the explicitly approved USD 279.00 basket.')
    if not args.database.resolve().is_relative_to((ROOT/'output').resolve()) or not args.ledger.resolve().is_relative_to((ROOT/'output').resolve()):
        parser.error('Temporary state belongs in ignored output/.')
    import httpx
    from intentcart import config
    if not (config.CLIENT_ID and config.CLIENT_SECRET):parser.error('Existing sandbox app credentials are absent.')
    config.CALL_LIMIT=0;config.ASTRO_KEY='';config.ASTRO_BUDGET=0;config.CHANNEL3_KEY=''
    config.PUBLIC_URL=f'http://127.0.0.1:{args.port}';config.DATABASE_PATH=str(args.database);config.COOKIE_SECURE=False
    ledger=Ledger(args.ledger,args.max_api_calls)
    original=httpx.HTTPTransport.handle_request
    def bounded(transport,request):
        guard_request(request,args.approved_total_cents)
        index=ledger.reserve(request.method,request.url.path)
        result=original(transport,request)
        ledger.record_status(index,result.status_code)
        return result
    httpx.HTTPTransport.handle_request=bounded
    import uvicorn
    print('Local sandbox-only server; exact USD 279.00 order guard; durable server API ceiling 12; inference/discovery disabled.',flush=True)
    uvicorn.run('intentcart.app:app',host='127.0.0.1',port=args.port)
    return 0


if __name__=='__main__':raise SystemExit(main())
