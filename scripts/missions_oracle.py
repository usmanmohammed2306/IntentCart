"""Independent exhaustive fixture grader; does not import the mission solver.

Same declared rules/catalog, separately implemented validation and enumeration.
This is an oracle for a small synthetic system, not real hardware certification.
"""
from itertools import product
import hashlib
import json
from pathlib import Path

DATA=json.loads((Path(__file__).resolve().parents[1]/'intentcart/data/missions-catalog.json').read_text())
ITEMS={p['id']:p for p in DATA['products']}

def grade(goal, basket, inspected=(), excluded=(), active=None):
    if not isinstance(basket,list) or not basket: return False
    kinds={}
    for line in basket:
        if set(line)!= {'product_id','quantity'} or line['product_id'] not in ITEMS or type(line['quantity']) is not int or line['quantity']<=0:return False
        p=ITEMS[line['product_id']]
        if p['id'] in excluded or p['kind'] in kinds:return False
        kinds[p['kind']]=(p,line['quantity'])
    need=goal['displays']-int(goal['reuse_monitor'])
    if set(kinds)!=({'dock','cable','power','monitor'} if need else {'dock','cable','power'}):return False
    if any(q!=(need if k=='monitor' else 1) for k,(_,q) in kinds.items()):return False
    spec={}
    for kind,(p,_) in kinds.items():
        fields={o['field'] for o in p['observations']}
        spec[kind]={}
        for f in fields:
            vals=[o['value'] for o in p['observations'] if o['field']==f and (o['visible'] or o['source_id'] in inspected)]
            if vals and all(v==vals[0] for v in vals):spec[kind][f]=vals[0]
    d,c,w=spec['dock'],spec['cable'],spec['power']
    m=spec.get('monitor',{'height':2160,'hz':120,'connector':'hdmi'})
    laptop=next(l for l in DATA['laptops'] if l['id']==goal['laptop_id'])
    rules={
        'budget':lambda:sum(ITEMS[b['product_id']]['price_cents']*b['quantity'] for b in basket)<=goal['budget_cents'],
        'transport':lambda:d['protocol'] in laptop['protocols'],
        'driver':lambda:d['protocol']!='displaylink' or goal['allow_driver'],
        'displays':lambda:d['displays']>=goal['displays'] and (d['protocol']=='displaylink' or laptop['native_displays']>=goal['displays']),
        'resolution':lambda:min(d['max_height'],m['height'],1080 if goal['reuse_monitor'] else 100000)>=goal['height'],
        'refresh':lambda:min(d['max_hz'],m['hz'],c['hz'],60 if goal['reuse_monitor'] else 100000)>=goal['hz'],
        'charging':lambda:min(d['pd_watts'],w['watts'])>=laptop['charge_watts'],
        'cables':lambda:c['count']>=goal['displays'] and c['height']>=goal['height'] and c['connector']==m['connector']=='hdmi',
    }
    for key,rule in rules.items():
        if active is not None and key not in active:continue
        try:
            if not rule():return False
        except KeyError:return False
    return True

def enumerate_baskets(goal,excluded=()):
    need=goal['displays']-int(goal['reuse_monitor'])
    groups=[]
    for kind in ('dock','monitor','cable','power'):
        groups.append([p for p in ITEMS.values() if p['kind']==kind and p['id'] not in excluded] if kind!='monitor' or need else [None])
    for combo in product(*groups):
        yield [{'product_id':p['id'],'quantity':need if p['kind']=='monitor' else 1} for p in combo if p]

def best(goal,inspected=(),excluded=(),previous=None,active=None):
    prior={ITEMS[b['product_id']]['kind']:(b['product_id'],b['quantity']) for b in previous or []}
    choices=[]
    for b in enumerate_baskets(goal,excluded):
        if not grade(goal,b,inspected,excluded,active):continue
        now={ITEMS[i['product_id']]['kind']:(i['product_id'],i['quantity']) for i in b}
        changed=sum(now.get(k)!=prior.get(k) for k in now.keys()|prior.keys()) if previous else 0
        cost=sum(ITEMS[i['product_id']]['price_cents']*i['quantity'] for i in b)
        key=hashlib.sha256(json.dumps(b,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]
        choices.append(((changed,cost,key),b))
    return min(choices,key=lambda v:v[0]) if choices else None
