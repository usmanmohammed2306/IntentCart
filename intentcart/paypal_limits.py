"""Durable, one-order sandbox test allocation; independent of sponsor AI usage."""
import hashlib
import json
import os
import re
import sqlite3
import time
from decimal import Decimal
from . import config

class LimitError(ValueError):
    pass

def declaration():
    try:
        item={'id':os.environ['PAYPAL_TEST_ALLOCATION_ID'],'limit':int(os.environ['PAYPAL_TEST_CALL_LIMIT']),
              'amount':int(os.environ['PAYPAL_TEST_AMOUNT_CENTS']),'expires':int(os.environ['PAYPAL_TEST_EXPIRES'])}
        if not re.fullmatch(r'[a-z0-9-]{8,80}',item['id']) or not 1<=item['limit']<=12 or item['amount']!=22900:
            raise ValueError()
        return item
    except (KeyError,ValueError):
        raise LimitError('PayPal Sandbox needs an explicit one-time $229 test allocation (at most 12 server calls).') from None

def transaction(action):
    item=declaration();fingerprint=hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest()
    with sqlite3.connect(config.DATABASE_PATH,timeout=10) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS paypal_test_allocations(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,calls INTEGER NOT NULL,state TEXT NOT NULL)')
        row=db.execute('SELECT fingerprint,calls,state FROM paypal_test_allocations WHERE id=?',(item['id'],)).fetchone()
        if row and row[0]!=fingerprint:raise LimitError('The fixed PayPal test allocation changed. It cannot be renewed automatically.')
        count=row[1] if row else 0;state=json.loads(row[2]) if row else {}
        result,count,state=action(item,count,state)
        db.execute('INSERT INTO paypal_test_allocations VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET calls=excluded.calls,state=excluded.state',
                   (item['id'],fingerprint,count,json.dumps(state,sort_keys=True)))
        return result

def status():
    try:
        item=declaration()
        with sqlite3.connect(config.DATABASE_PATH,timeout=10) as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paypal_test_allocations'").fetchone()
            row=db.execute('SELECT fingerprint,calls,state FROM paypal_test_allocations WHERE id=?',(item['id'],)).fetchone() if exists else None
        fingerprint=hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest()
        if row and row[0]!=fingerprint:raise LimitError('The fixed PayPal test allocation changed; checkout is paused.')
        used=row[1] if row else 0;state=json.loads(row[2]) if row else {}
        closed=bool(state.get('closed')) or time.time()>=item['expires'] or used>=item['limit']
        return {'available':not closed,'remaining_calls':max(0,item['limit']-used),'closed':closed,
                'notice':'The approved PayPal Sandbox test is closed. Saved receipts remain available; no new payment request will be sent.' if closed else 'One approved $229 sandbox test. No real money; fixed server-call cap.'}
    except (LimitError,sqlite3.Error,ValueError,TypeError) as exc:
        return {'available':False,'remaining_calls':0,'closed':True,'notice':str(exc) if isinstance(exc,LimitError) else 'PayPal test accounting is unavailable; checkout is paused.'}

def reserve(method,path,body=None,request_id=None):
    def apply(item,count,state):
        if state.get('closed') or time.time()>=item['expires'] or count>=item['limit']:
            raise LimitError('The PayPal Sandbox test allowance is closed or exhausted. No request was sent.')
        if (method,path)==('POST','/v1/oauth2/token'):pass
        elif (method,path)==('POST','/v2/checkout/orders'):
            try:
                units=body['purchase_units'];unit=units[0];amount=unit['amount'];quote=unit['reference_id']
                if len(units)!=1 or amount['currency_code']!='USD' or Decimal(amount['value'])*100!=item['amount'] or not request_id or not quote:raise ValueError()
                if state.get('create_key') not in (None,request_id) or state.get('quote') not in (None,quote):raise ValueError()
            except (KeyError,TypeError,ValueError,ArithmeticError):raise LimitError('Only the exact approved $229 sandbox cart and its original idempotency key are allowed.') from None
            state.update(create_key=request_id,quote=quote)
        elif method=='GET' and state.get('order') and path=='/v2/checkout/orders/'+state['order']:pass
        elif method=='POST' and state.get('order') and path=='/v2/checkout/orders/'+state['order']+'/capture' and not state.get('refunded'):pass
        elif method=='POST' and state.get('capture') and path=='/v2/payments/captures/'+state['capture']+'/refund' and not state.get('refunded'):pass
        else:raise LimitError('That PayPal operation is outside the approved sandbox test. No request was sent.')
        return None,count+1,state
    transaction(apply)

def observe(method,path,payload):
    if not isinstance(payload,dict):return
    def apply(item,count,state):
        if (method,path)==('POST','/v2/checkout/orders') and payload.get('id'):
            if state.get('order') not in (None,payload['id']):raise LimitError('PayPal returned a different order for the fixed test.')
            state['order']=payload['id']
        if state.get('order') and path in ('/v2/checkout/orders/'+state['order'],'/v2/checkout/orders/'+state['order']+'/capture'):
            units=payload.get('purchase_units',[])
            if len(units)==1 and units[0].get('reference_id')==state.get('quote'):
                captures=units[0].get('payments',{}).get('captures',[])
                if len(captures)==1:
                    capture=captures[0];amount=capture.get('amount',{})
                    if amount.get('currency_code')=='USD' and Decimal(amount.get('value','0'))*100==item['amount']:
                        if state.get('capture') not in (None,capture.get('id')):raise LimitError('The sandbox capture identity changed.')
                        state['capture']=capture.get('id')
                        if method=='GET' and capture.get('status')=='REFUNDED' and state.get('refunded'):state['closed']=True
        if method=='POST' and state.get('capture') and path=='/v2/payments/captures/'+state['capture']+'/refund':
            amount=payload.get('amount',{})
            if payload.get('id') and payload.get('status')=='COMPLETED' and amount.get('currency_code')=='USD' and Decimal(amount.get('value','0'))*100==item['amount']:
                state.update(refund=payload['id'],refunded=True)
        return None,count,state
    transaction(apply)
