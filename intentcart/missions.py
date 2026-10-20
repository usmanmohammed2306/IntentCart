"""Bounded outcome compiler: typed goals, partial facts and exact finite planning.

Pure CPU code. All built-in products are fictional. No model output or retrieved
page is an authority for facts, prices, inventory or payment consent.
"""
from copy import deepcopy
from itertools import product
from pathlib import Path
import hashlib
import json
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

CATALOG = json.loads((Path(__file__).parent/'data/missions-catalog.json').read_text())
PRODUCTS = {p['id']: p for p in CATALOG['products']}
LAPTOPS = {p['id']: p for p in CATALOG['laptops']}
FACT_UNITS = {'protocol':'transport enum','displays':'independent displays',
              'max_height':'vertical pixels','height':'vertical pixels',
              'max_hz':'Hz','hz':'Hz','pd_watts':'W','watts':'W',
              'connector':'connector enum','count':'cables',
              'hdcp':'boolean','gaming':'boolean','minimum_os':'version',
              'output_connector':'connector enum','direction':'direction enum','adapter_for':'product ID'}
LABELS = {
    'budget': 'Complete basket must fit the all-in budget',
    'transport': 'Laptop must support the dock transport',
    'driver': 'DisplayLink requires your explicit driver permission',
    'displays': 'Dock and laptop must drive every independent display',
    'resolution': 'Every display must support the requested resolution',
    'refresh': 'Every component must support the requested refresh rate',
    'charging': 'Dock and supply must deliver the laptop charging requirement',
    'cables': 'Enough compatible cables with adequate resolution are required',
}

class Goal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    laptop_id: Literal['studio-pro','studio-air','studio-work'] = 'studio-pro'
    budget_cents: int = Field(default=35000, ge=1000, le=300000, strict=True)
    displays: int = Field(default=2, ge=1, le=2, strict=True)
    height: Literal[1080,2160] = 1080
    hz: Literal[60,120] = 60
    reuse_monitor: bool = Field(default=True, strict=True)
    allow_driver: bool = Field(default=False, strict=True)

def compile_text(text):
    """Conservative deterministic fallback; suggestions require explicit review.

    This is intentionally not claimed as an LLM. Structured model suggestions
    use the same Goal schema and still require shopper confirmation.
    """
    lower = re.sub(r'[-\u2010-\u2015]', ' ', text.lower().replace('\u2019', "'"))
    suggestions = {}
    review_fields = set()

    def negated(match):
        # Deliberately bounded phrase recognition, not general language parsing.
        return bool(re.search(
            r"\b(?:no|not|without|never|don't|do not)"
            r"(?:\s+(?:want|need|require|use|any|a|an|for|to|buy|purchase|new|single|one|two|dual|1|2))*\s*$",
            lower[:match.start()]))

    def suggest(field, values):
        if len(values) == 1:
            suggestions[field] = values.pop()
        elif values:
            review_fields.add(field)

    money = re.findall(r'\$\s*(\d+(?:\.\d{1,2})?)', lower)
    if len(money) == 1:
        from decimal import Decimal
        cents = int(Decimal(money[0])*100)
        if 1000 <= cents <= 300000:
            suggestions['budget_cents'] = cents
    display = r'(?:monitors?|displays?|screens?)\b'
    resolution = r'(?:full\s+hd|1080p?|4k|2160p?)'
    descriptor = rf'(?:{resolution}\s+)?'
    counts = set()
    for match in re.finditer(rf'\b(single|one|1|dual|two|2)\s+{descriptor}{display}', lower):
        if negated(match):
            review_fields.add('displays')
        else:
            counts.add(1 if match[1] in ('single', 'one', '1') else 2)
    suggest('displays', counts)

    heights, excluded_heights = set(), set()
    for match in re.finditer(rf'\b{resolution}\b', lower):
        value = 2160 if match[0] in ('4k', '2160', '2160p') else 1080
        if negated(match):
            excluded_heights.add(value)
            review_fields.add('resolution')
        else:
            heights.add(value)
    # A rejected resolution does not imply a particular replacement.
    if not heights & excluded_heights:
        suggest('height', heights)
    else:
        review_fields.add('resolution')

    reuse = set()
    for match in re.finditer(rf'\b(?:reuse|keep)\s+(?:(?:my|our|the|a|an)\s+)?'
                             rf'(?:(?:current|existing|old|owned)\s+)?{descriptor}{display}', lower):
        reuse.add(not negated(match))
    for match in re.finditer(rf'\bnew\s+{descriptor}{display}', lower):
        if not negated(match):
            reuse.add(False)
        else:
            review_fields.add('reuse')
    suggest('reuse_monitor', reuse)

    rates = set()
    for match in re.finditer(r'\b(60|120)\s*hz\b', lower):
        if not negated(match):
            rates.add(int(match[1]))
        else:
            review_fields.add('refresh rate')
    suggest('hz', rates)
    # Permissions are never inferred from free text (including negations).
    notice = ('Only the reviewed form becomes requirements. Local rules recognize limited '
              'budget, display-count, resolution, refresh and reuse/new-display phrases. '
              'Check every field, including laptop and driver permission; other requests are not enforced.')
    if review_fields:
        notice += ' Ambiguous or negated details need manual review; no alternative was assumed.'
    return {'suggestions': suggestions, 'mode':'local rule compiler',
            'review_required': True,
            'notice':notice}

def fact(item, field, inspected=(), *, catalog=None):
    catalog = CATALOG if catalog is None else catalog
    records = [o for o in item['observations'] if o['field'] == field
               and (o['visible'] or o['source_id'] in inspected)]
    values = {json.dumps(o['value'], sort_keys=True) for o in records}
    sources = [catalog['sources'][o['source_id']] for o in records]
    provenance_ok = all(s.get('product_id') == item['id'] and
                        s.get('variant') == item.get('variant', item['id']) and
                        s.get('field') == field and s.get('value') == o['value'] and
                        s.get('unit') == FACT_UNITS.get(field)
                        for o, s in zip(records, sources))
    units = {json.dumps(s.get('unit'), sort_keys=True) for s in sources}
    verified = len(values) == 1 and provenance_ok and len(units) == 1
    return {'status': 'unknown' if not values else 'verified_fixture' if verified else 'conflict',
            'value': records[0]['value'] if verified else None,
            'unit': catalog['sources'][records[0]['source_id']]['unit'] if records else None,
            'sources': [o['source_id'] for o in records]}

def basket_key(items):
    return hashlib.sha256(json.dumps(items,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]

def candidates(goal, excluded=(), *, catalog=None):
    products = PRODUCTS if catalog is None else {p['id']: p for p in catalog['products']}
    groups = [[p for p in products.values() if p['kind']==kind and p['id'] not in excluded]
              for kind in ('dock','monitor','cable','power')]
    count = goal.displays - int(goal.reuse_monitor)
    if count == 0: groups[1] = [None]
    for dock, monitor, cable, power in product(*groups):
        items = [{'product_id':p['id'],'quantity':count if p['kind']=='monitor' else 1}
                 for p in (dock,monitor,cable,power) if p]
        yield items

def evaluate(goal, items, inspected=(), *, catalog=None):
    products = PRODUCTS if catalog is None else {p['id']: p for p in catalog['products']}
    laptops = LAPTOPS if catalog is None else {p['id']: p for p in catalog['laptops']}
    selected = {products[i['product_id']]['kind']: products[i['product_id']] for i in items}
    dock, cable, power = (selected[k] for k in ('dock','cable','power'))
    monitor = selected.get('monitor')
    laptop = laptops[goal.laptop_id]
    facts = {}
    def get(p, field):
        key = p['id']+':'+field
        facts[key] = fact(p,field,inspected,catalog=catalog)
        return facts[key]['value']
    protocol = get(dock,'protocol')
    n, dh, dr, pd = [get(dock,k) for k in ('displays','max_height','max_hz','pd_watts')]
    ch, cr, cn, connector = [get(cable,k) for k in ('height','hz','count','connector')]
    watts = get(power,'watts')
    mh, mr, mc = [get(monitor,k) for k in ('height','hz','connector')] if monitor else (2160,120,'hdmi')
    # Three-valued conjunction: a known contradiction wins over missing facts.
    def all3(*values):
        return False if False in values else None if None in values else True
    def cmp(value, predicate): return None if value is None else bool(predicate(value))
    total = sum(products[i['product_id']]['price_cents']*i['quantity'] for i in items)
    checks = {
        'budget': total <= goal.budget_cents,
        'transport': cmp(protocol,lambda v:v in laptop['protocols']),
        'driver': cmp(protocol,lambda v:v!='displaylink' or goal.allow_driver),
        'displays': all3(cmp(n,lambda v:v>=goal.displays),
                         cmp(protocol,lambda v:v=='displaylink' or laptop['native_displays']>=goal.displays)),
        'resolution': all3(cmp(dh,lambda v:v>=goal.height),cmp(mh,lambda v:v>=goal.height),
                           not goal.reuse_monitor or goal.height<=1080),
        'refresh': all3(cmp(dr,lambda v:v>=goal.hz),cmp(mr,lambda v:v>=goal.hz),
                        cmp(cr,lambda v:v>=goal.hz),not goal.reuse_monitor or goal.hz<=60),
        'charging': all3(cmp(pd,lambda v:v>=laptop['charge_watts']),cmp(watts,lambda v:v>=laptop['charge_watts'])),
        'cables': all3(cmp(cn,lambda v:v>=goal.displays),cmp(ch,lambda v:v>=goal.height),
                       cmp(connector,lambda v:v=='hdmi'),cmp(mc,lambda v:v=='hdmi')),
    }
    return {'id':basket_key(items),'items':items,'total_cents':total,'checks':checks,
            'failed':[k for k,v in checks.items() if v is False],
            'unknown':[k for k,v in facts.items() if v['status']!='verified_fixture'],
            'facts':facts,'valid':all(v is True for v in checks.values())}

def irreducible_core(rows):
    """Deletion-based subset-minimal conflict; not minimum cardinality.

    Unknowns fail closed. Availability/complete structure define the candidate
    universe; returned conflicts concern only the eight displayed constraints.
    """
    if not rows: return ['availability']
    core = list(LABELS)
    for key in list(core):
        reduced = [k for k in core if k!=key]
        if not any(all(r['checks'][k] is True for k in reduced) for r in rows): core = reduced
    return core

def solve(goal, inspected=(), excluded=(), previous=None, *, catalog=None, preference_history=()):
    catalog = CATALOG if catalog is None else catalog
    products = {p['id']: p for p in catalog['products']}
    rows = [evaluate(goal,i,inspected,catalog=catalog) for i in candidates(goal,excluded,catalog=catalog)]
    prior = {products[i['product_id']]['kind']:(i['product_id'],i['quantity']) for i in (previous or [])}
    def changes(row):
        current = {products[i['product_id']]['kind']:(i['product_id'],i['quantity']) for i in row['items']}
        return sum(prior.get(k)!=current.get(k) for k in prior.keys()|current.keys()) if previous else 0
    valid = sorted((r for r in rows if r['valid']),key=lambda r:(changes(r),r['total_cents'],r['id']))
    from . import workspace_preferences
    personalized = workspace_preferences.active(preference_history)
    if personalized:
        from . import workspace_preferences
        valid = workspace_preferences.rank(valid, catalog, preference_history)
        if previous:
            valid.sort(key=changes)
    leader = valid[0] if valid else None
    if leader: leader={**leader,'changed_slots':changes(leader)}
    blocked = [r for r in rows if not r['failed'] and r['unknown']]
    investigations = {}
    for row in blocked:
        for key in row['unknown']:
            pid, field = key.split(':')
            ids = [o['source_id'] for o in products[pid]['observations'] if o['field']==field and not o['visible'] and o['source_id'] not in inspected]
            if not ids: continue
            entry = investigations.setdefault(key,{'product_id':pid,'field':field,'source_ids':ids,
                'unlocks_candidates':0,'optimistic_total_cents':row['total_cents']})
            entry['unlocks_candidates'] += 1
            entry['optimistic_total_cents'] = min(entry['optimistic_total_cents'],row['total_cents'])
    research = sorted(investigations.values(),key=lambda r:(r['optimistic_total_cents'],-r['unlocks_candidates'],r['product_id']))
    for r in research:
        r['could_improve_cost'] = leader is None or r['optimistic_total_cents'] < leader['total_cents']
        r['reason'] = 'Unknown fact blocks otherwise admissible baskets. Count is hypothetical feasibility, not probability or expected information gain.'
    conflicts = [] if leader or research else irreducible_core(rows)
    alternatives = []
    if not leader:
        for field,value in [('allow_driver',True),('reuse_monitor',False),('height',1080),('hz',60),('displays',1),('budget_cents',300000)]:
            if getattr(goal,field)==value: continue
            revised=goal.model_copy(update={field:value})
            possible=[evaluate(revised,i,inspected,catalog=catalog) for i in candidates(revised,excluded,catalog=catalog)]
            feasible=[r for r in possible if r['valid']]
            if feasible:
                cheapest=min(feasible,key=lambda r:r['total_cents'])
                alternatives.append({'field':field,'value':cheapest['total_cents'] if field=='budget_cents' else value,
                                     'minimum_total_cents':cheapest['total_cents']})
    graph = []
    if leader:
        ids={products[i['product_id']]['kind']:i['product_id'] for i in leader['items']}
        graph=[{'from':goal.laptop_id,'to':ids['dock'],'label':'data transport'},
               {'from':ids['power'],'to':ids['dock'],'label':'power supply'},
               {'from':ids['dock'],'to':ids['cable'],'label':'display signal'},
               {'from':ids['cable'],'to':ids.get('monitor','owned-monitor'),'label':'HDMI connection'},
               {'from':ids['dock'],'to':goal.laptop_id,'label':'one-cable charging'}]
        if goal.reuse_monitor and 'monitor' in ids: graph.append({'from':ids['cable'],'to':'owned-monitor','label':'reused Full HD display'})
    return {'status':'READY' if leader else 'NEEDS_EVIDENCE' if research else 'INFEASIBLE',
            'plan':leader,'feasible_count':len(valid),'candidate_count':len(rows),
            'investigations':research,'conflict_core':conflicts,
            'conflict_note':'Subset-minimal over current finite candidates and displayed constraints; not a global or minimum-cardinality proof.',
            'relaxations':alternatives,'graph':graph,
            'rejected':sorted((r for r in rows if not r['valid']),key=lambda r:(r['total_cents'],r['id']))[:8],
            'preference_choices': [{'id': r['id'], 'items': r['items'], 'total_cents': r['total_cents']} for r in valid[:12]],
            'objective':('Hard constraints and minimal-change repair first, then estimated human preference utility.' if personalized
                         else 'Fewest changed component slots, then lowest total cents, then stable basket ID.' if previous else 'Lowest total cents, then stable basket ID.'),
            'evidence_limit':catalog['notice']}

def public_catalog():
    return {'notice':CATALOG['notice'],'laptops':CATALOG['laptops'],
            'products':[{k:v for k,v in p.items() if k!='observations'} for p in PRODUCTS.values()],
            'constraints':LABELS,'goal_schema':Goal.model_json_schema()}

def public_record(record):
    """Return an owned record for display/export without its server row cache."""
    from . import validity
    if record is None:
        return None
    result=deepcopy(record)
    if 'validity' in result:
        result['validity']=validity.public_certificate(result['validity'])
    if 'validity' in result.get('result', {}):
        result['result']['validity']=validity.public_certificate(result['result']['validity'])
    return result

def create(text, goal, revision=1):
    from . import validity
    result=solve(goal)
    source=source_identity()
    certificate=validity.analyze(goal,items=result['plan']['items'] if result['plan'] else [],
                                 revision=revision,source_sha256=source)
    result['validity']=validity.public_certificate(certificate)
    return {'schema':'intentcart-mission/1','revision':revision,'text':text,'goal':goal.model_dump(),
            'inspected':[],'excluded':[],'preference_history':[],'events':[{'kind':'compile','revision':revision}],
            'result':result,'validity':certificate,'previous_plan':None,'objective_mode':'cost','source_sha256':source,'compiler':'local reviewed fields'}

def revise(record, goal=None, exclude=None, inspect=None):
    from . import validity
    new=deepcopy(record)
    previous=record['result']['plan']
    if previous: new['previous_plan']=previous['items']
    if goal is not None: new['goal']=goal.model_dump()
    if exclude and exclude not in new['excluded']: new['excluded'].append(exclude)
    if inspect and inspect not in new['inspected']: new['inspected'].append(inspect)
    new['revision']+=1
    new['objective_mode']='cost' if inspect else 'repair'
    new['result']=solve(Goal(**new['goal']),new['inspected'],new['excluded'],new['previous_plan'] if new['objective_mode']=='repair' else None,
                        preference_history=new.get('preference_history', ()))
    new['validity']=validity.analyze(new['goal'],inspected=new['inspected'],excluded=new['excluded'],
        items=new['result']['plan']['items'] if new['result']['plan'] else [],
        previous_items=new['previous_plan'] if new['objective_mode']=='repair' else None,
        revision=new['revision'],source_sha256=new['source_sha256'],previous=record.get('validity'))
    if new.get('preference_history'):
        annotate_preferences(new['validity'], new['preference_history'])
    new['result']['validity']=validity.public_certificate(new['validity'])
    new['events']=(new['events']+[{'kind':'inspect' if inspect else 'exclude' if exclude else 'requirements',
        'revision':new['revision'],'detail':inspect or exclude or new['goal']}])[-30:]
    return new

def source_identity():
    root=Path(__file__).parent
    return hashlib.sha256((root/'missions.py').read_bytes()+(root/'validity.py').read_bytes()+
                          (root/'data/missions-catalog.json').read_bytes()+
                          (root/'workspace_preferences.py').read_bytes()).hexdigest()

def annotate_preferences(certificate, history):
    from . import validity
    from . import workspace_preferences
    if not workspace_preferences.active(history):
        return
    certificate['claims']['optimality'] = {'status': 'unresolved', 'objective': 'estimated human preference utility',
        'note': 'Preference-ranked configuration. The cost certificate does not establish your true utility or preference-policy superiority.'}
    certificate['identities']['preference_history_sha256'] = validity.digest(history)
    public = validity.public_certificate(certificate)
    public.pop('certificate_sha256', None)
    certificate['certificate_sha256'] = validity.digest(public)

def prefer(record, a, b, choice):
    from . import validity
    if a == b or choice not in ('a', 'b', 'tie', 'skip'):
        raise ValueError('Choose two different supported configurations and a preference response.')
    choices = {r['id'] for r in record['result'].get('preference_choices', [])}
    if a not in choices or b not in choices:
        raise ValueError('Compare only currently supported configurations.')
    new = deepcopy(record)
    new['preference_history'] = (new.get('preference_history', []) + [{'a': a, 'b': b, 'choice': choice}])[-30:]
    new['revision'] += 1
    new['previous_plan'] = None
    new['objective_mode'] = 'cost'
    goal = Goal(**new['goal'])
    new['result'] = solve(goal, new['inspected'], new['excluded'], preference_history=new['preference_history'])
    plan = new['result']['plan']
    new['validity'] = validity.analyze(goal, items=plan['items'] if plan else [], inspected=new['inspected'], excluded=new['excluded'],
                                     revision=new['revision'], source_sha256=new['source_sha256'], previous=record.get('validity'))
    annotate_preferences(new['validity'], new['preference_history'])
    new['result']['validity'] = validity.public_certificate(new['validity'])
    new['events'] = (new['events'] + [{'kind': 'preference', 'revision': new['revision'], 'detail': {'choice': choice}}])[-30:]
    return new

def quote_gate(quote, state, proposal, now):
    record=state.get('outcome')
    plan=record['result']['plan'] if record else None
    canonical=False
    cost=None
    if record and plan:
        goal=Goal(**record['goal'])
        canonical=any(items==quote.get('basket') for items in candidates(goal,record['excluded']))
        if canonical:
            result=evaluate(goal,quote['basket'],record['inspected'])
            canonical=result['valid'] and result['id']==plan['id']==quote['product']['id'].removeprefix('mission-')
            cost=result['total_cents']
    conditions={
        'consent':proposal.get('approved') is True,
        'version':bool(record and quote['version']==state['version']==proposal.get('version') and quote['mission_revision']==record['revision']),
        'expiry':now<quote['expires_at'],
        'product':proposal.get('product_id')==quote['product']['id'],
        'amount':type(proposal.get('total_cents')) is int and proposal['total_cents']==quote['total_cents'],
        'currency':proposal.get('currency')==quote['currency']=='USD',
        'budget':bool(record and quote['total_cents']<=record['goal']['budget_cents']),
        'feasible':canonical,
        'pricing':cost is not None and cost==quote['total_cents']==quote['item_cents'] and quote['shipping_cents']==quote['tax_cents']==0,
        'source':quote.get('mission_source_sha256')==source_identity(),
    }
    return {'eligible':all(conditions.values()),'checks':[{'id':k,'label':k.replace('_',' '),'passed':bool(v)} for k,v in conditions.items()],
            'failed':[k for k,v in conditions.items() if not v],
            'note':'Fixture compatibility and sandbox eligibility; not real specification certification or recorded consent.'}
