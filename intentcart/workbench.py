"""Owned planning workbench. Human edits never create payments or model authority."""
from copy import deepcopy
import csv
from datetime import date, datetime
from zoneinfo import ZoneInfo
import hashlib
import io
import json
import re
from pydantic import BaseModel, ConfigDict, Field
from . import missions, evidence_catalog, workspace_preferences as preferences

class Requirements(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    hdcp: bool = False
    gaming: bool = False
    os_version: str = Field(default='', max_length=40)
    charging_watts: int = Field(default=0, ge=0, le=240)
    connector: str = Field(default='hdmi', pattern=r'^(hdmi|displayport|usb-c)$')
    tax_cents: int | None = Field(default=0, ge=0, le=100000)
    shipping_cents: int | None = Field(default=0, ge=0, le=100000)
    evidence_max_age_days: int = Field(default=90, ge=1, le=3650)
    price_max_age_days: int = Field(default=7, ge=1, le=365)
    owned_monitors: list[dict] = Field(default_factory=list, max_length=4)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _integer(value, lo, hi, label):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f'{label} must be an integer between {lo} and {hi}.')
    return value


def _text(value, label, limit=400):
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise ValueError(f'Invalid {label}.')
    return value.strip()


def settings(record):
    return Requirements.model_validate(record.get('workbench', {}).get('requirements', {}))


def catalog(record):
    from . import agent
    return deepcopy(record.get('workbench', {}).get('catalog') or agent.catalog_for(record['catalog_kind']))


def current_day():
    return datetime.now(ZoneInfo('America/Phoenix')).date()

def freshness(source, max_age=90, today=None):
    today = today or current_day()
    observed = source.get('observed_on')
    if not observed:
        return {'status': 'fictional' if source.get('kind') != 'manufacturer' else 'undated', 'age_days': None}
    try:
        age = (today - date.fromisoformat(observed)).days
    except (ValueError, TypeError):
        return {'status': 'invalid_date', 'age_days': None}
    return {'status': 'future' if age < 0 else 'expired' if age > max_age else 'current', 'age_days': age}


def observed(record, current_catalog=None):
    cat = current_catalog or catalog(record)
    req = settings(record)
    # Fictional fixtures have no real-world freshness claim. Curated evidence
    # must remain inside the explicit review interval, including on page reload.
    return [sid for sid in record['inspected'] if sid in cat['sources'] and
            (record['catalog_kind'] == 'fixture' or freshness(cat['sources'][sid], req.evidence_max_age_days)['status'] == 'current')]


def version(value):
    if not re.fullmatch(r'\d{1,3}(?:\.\d{1,3}){0,2}', value):
        raise ValueError('OS version must use numeric major.minor.patch notation.')
    return tuple((list(map(int, value.split('.'))) + [0, 0])[:3])


def evaluate(record, row, cat):
    row = deepcopy(row)
    req = settings(record)
    products = {p['id']: p for p in cat['products']}
    selected = {products[i['product_id']]['kind']: products[i['product_id']] for i in row['items']}
    checks = row['checks']
    dock, cable, power = (selected[k] for k in ('dock', 'cable', 'power'))
    seen = observed(record, cat)
    def fact(item, field):
        result = missions.fact(item, field, seen, catalog=cat)
        row['facts'][item['id'] + ':' + field] = result
        return result['value']
    # Only requested extra capabilities become hard requirements. Missing data
    # never turns into permission or evidence of support.
    if req.hdcp:
        checks['hdcp'] = fact(dock, 'hdcp') is True
    if req.gaming:
        checks['gaming'] = fact(dock, 'gaming') is True
    if req.os_version:
        minimum = fact(dock, 'minimum_os')
        checks['os_version'] = minimum is not None and version(req.os_version) >= version(minimum)
    if req.charging_watts:
        pd, watts = fact(dock, 'pd_watts'), fact(power, 'watts')
        checks['charging_target'] = pd is not None and watts is not None and min(pd, watts) >= req.charging_watts
    connector = fact(cable, 'connector')
    if req.connector != 'hdmi':
        monitor = selected.get('monitor')
        mc = fact(monitor, 'connector') if monitor else (req.owned_monitors[0].get('connector') if req.owned_monitors else None)
        checks['cables'] = connector == mc == req.connector and all(
            row['facts'][cable['id'] + ':' + field]['value'] is not None and
            row['facts'][cable['id'] + ':' + field]['value'] >= target
            for field, target in [('count', record['goal']['displays']), ('height', record['goal']['height']), ('hz', record['goal']['hz'])])
        checks['dock_output'] = fact(dock, 'output_connector') == req.connector
    direction = fact(cable, 'direction') if any(o['field'] == 'direction' for o in cable['observations']) else None
    if any(o['field']=='direction' for o in cable['observations']):
        checks['connector_direction'] = direction in ('dock-to-display','bidirectional')
    matches = fact(power, 'adapter_for') if any(o['field'] == 'adapter_for' for o in power['observations']) else None
    if any(o['field']=='adapter_for' for o in power['observations']):
        checks['adapter_match'] = matches == dock['id']
    elif record['catalog_kind'] == 'curated':
        # The one included adapter declaration is tied to its exact kit.
        checks['adapter_match'] = power.get('compatible_dock_id') == dock['id']
    if req.owned_monitors and record['goal']['reuse_monitor']:
        monitors = req.owned_monitors
        checks['owned_monitors'] = len(monitors) <= record['goal']['displays'] and all(
            m['height'] >= record['goal']['height'] and m['hz'] >= record['goal']['hz'] and m['connector'] == req.connector for m in monitors)
        if checks['owned_monitors']:
            # Replace the baseline's single assumed 1080p60 monitor constraint
            # with the explicit human-declared owned specification.
            checks['resolution'] = all(f['value'] is not None and f['value'] >= record['goal']['height'] for key, f in row['facts'].items() if key.endswith((':max_height', ':height')))
            checks['refresh'] = all(f['value'] is not None and f['value'] >= record['goal']['hz'] for key, f in row['facts'].items() if key.endswith((':max_hz', ':hz')))
    extra = None if req.tax_cents is None or req.shipping_cents is None else req.tax_cents + req.shipping_cents
    row['subtotal_cents'] = row['total_cents']
    row['total_cents'] = None if extra is None else row['total_cents'] + extra
    checks['all_in_price'] = row['total_cents'] is not None and row['total_cents'] <= record['goal']['budget_cents']
    for item in row['items']:
        offer = record.get('workbench', {}).get('offers', {}).get(item['product_id'])
        if offer:
            checks['offer_' + item['product_id']] = freshness(offer, req.price_max_age_days)['status'] == 'current' and offer['available']
    row['failed'] = [k for k, v in checks.items() if v is False]
    row['unknown'] = [k for k, f in row['facts'].items() if f['status'] not in ('verified_fixture', 'supported_curated_record')]
    row['valid'] = all(v is True for v in checks.values())
    return row


def rows(record):
    from . import agent
    cat = catalog(record)
    goal = agent.goal_for(record['goal'], record['catalog_kind'], cat)
    owned = settings(record).owned_monitors
    seen_baskets = set()
    for items in missions.candidates(goal, record['excluded'], catalog=cat):
        if goal.reuse_monitor and len(owned) > 1:
            items = [dict(i, quantity=max(0, goal.displays-len(owned))) if next(p for p in cat['products'] if p['id']==i['product_id'])['kind']=='monitor' else i for i in items]
            items = [i for i in items if i['quantity']]
        key=missions.basket_key(items)
        if key in seen_baskets: continue
        seen_baskets.add(key)
        yield evaluate(record, missions.evaluate(goal, items, observed(record, cat), catalog=cat), cat)


def changed_slots(record, row):
    cat = catalog(record); products = {p['id']: p for p in cat['products']}
    def slots(items):
        return {products[i['product_id']]['kind']: (i['product_id'], i['quantity']) for i in items}
    old, new = slots(record.get('previous_items') or []), slots(row['items'])
    return sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k)) if old else []


def rank(record, candidates=None):
    valid = [r for r in (list(rows(record)) if candidates is None else candidates) if r['valid']]
    if record['personalized']:
        valid = preferences.rank(valid, catalog(record), record['history'])
        valid.sort(key=lambda r: len(changed_slots(record, r)))
    else:
        valid.sort(key=lambda r: (len(changed_slots(record, r)), r['total_cents'], r['id']))
    return valid


def mutate(record, operation, payload):
    from . import agent
    agent.ensure_current(record)
    if type(payload) is not dict or len(json.dumps(payload)) > 24000:
        raise ValueError('Supply a bounded workbench object.')
    # Withdrawing a proposal changes no accepted facts or preference evidence.
    # Handle it before structural mutation bookkeeping can change prior plans.
    if operation == 'cancel_source':
        proposal = record.get('workbench', {}).get('pending_source')
        if (set(payload) != {'proposal_id'} or not proposal
                or payload['proposal_id'] != proposal['id']):
            raise ValueError('Cancel only the exact pending source proposal; refresh and review again.')
        new = deepcopy(record)
        del new['workbench']['pending_source']
        new['revision'] += 1
        new['events'] = (new['events'] + [{
            'index': agent.event_index(new), 'origin': 'human',
            'action': {'action': operation, 'proposal_id': proposal['id']},
            'response': {'source_id': proposal['source_id'], 'proposal_cancelled': True,
                         'accepted_evidence_changed': False},
            'revision': new['revision']}])[-48:]
        return new
    new = deepcopy(record)
    wb = new.setdefault('workbench', {})
    wb.setdefault('requirements', {})
    cat = catalog(new)
    before = {'goal': deepcopy(new['goal']), 'requirements': deepcopy(wb['requirements']), 'excluded': list(new['excluded'])}
    previous = rank(record)
    if previous: new['previous_items'] = previous[0]['items']
    history_only = operation in ('undo_preference', 'delete_preference', 'edit_preference')
    if operation == 'import_catalog':
        if not {'catalog','reviewed','base_sha256'} <= set(payload) or set(payload)-{'catalog','reviewed','base_sha256','goal'} or payload['reviewed'] is not True or payload['base_sha256'] != digest(cat):
            raise ValueError('Review the bounded catalog against the exact current catalog identity.')
        imported = evidence_catalog.validate_catalog(payload['catalog'])
        new['goal'] = agent.goal_for(payload.get('goal',new['goal']), 'curated', imported).model_dump()
        new['catalog_kind'] = 'curated'
        new['source_sha256'] = agent.source_identity('curated')
        wb['catalog'] = imported
        new['inspected'] = []; new['discovered'] = []; new['excluded'] = []; new['previous_items'] = None
    elif operation == 'requirements':
        req = Requirements.model_validate({**wb['requirements'], **payload})
        if req.os_version: version(req.os_version)
        for monitor in req.owned_monitors:
            if set(monitor) != {'name','height','hz','connector'}:
                raise ValueError('Owned monitors need name, height, hz and connector only.')
            _text(monitor['name'], 'monitor name', 80)
            _integer(monitor['height'], 1, 4320, 'Owned monitor resolution')
            _integer(monitor['hz'], 1, 480, 'Owned monitor refresh')
            if monitor['connector'] not in ('hdmi','displayport','usb-c'): raise ValueError('Unknown owned monitor connector.')
        if len(req.owned_monitors) > new['goal']['displays']: raise ValueError('Owned monitor count exceeds requested displays.')
        wb['requirements'] = req.model_dump()
    elif operation == 'restore_product':
        pid = _text(payload.get('product_id'), 'product ID', 100)
        if pid not in new['excluded']: raise ValueError('Only excluded products can be restored.')
        new['excluded'].remove(pid)
    elif operation == 'withdraw_driver':
        new['goal']['allow_driver'] = False; new['driver_answered'] = False
    elif operation == 'select_variant':
        pid = _text(payload.get('product_id'), 'product ID', 100)
        selected = next((p for p in cat['products'] if p['id'] == pid), None)
        if selected is None or payload.get('variant') != selected.get('variant', selected['id']): raise ValueError('Exact product and variant must match.')
        new['excluded'] = sorted(set(new['excluded']) | {p['id'] for p in cat['products'] if p['kind'] == selected['kind'] and p['id'] != pid})
        new['excluded'] = [p for p in new['excluded'] if p != pid]
    elif operation == 'offer':
        pid = payload.get('product_id')
        product = next((p for p in cat['products'] if p['id'] == pid), None)
        if product is None or payload.get('variant') != product.get('variant',product['id']): raise ValueError('Offer must match exact product variant.')
        if set(payload) != {'product_id','variant','merchant','offer_id','price_cents','observed_on','available'}: raise ValueError('Supply the complete offer identity, price and review date.')
        _text(payload['merchant'],'merchant',100); _text(payload['offer_id'],'offer ID',100)
        _integer(payload['price_cents'],0,300000,'Price')
        if type(payload['available']) is not bool or freshness(payload,3650)['status'] != 'current': raise ValueError('Review date or availability invalid.')
        if any(other!=pid and offer['merchant'].casefold()==payload['merchant'].casefold() and offer['offer_id']==payload['offer_id'] for other,offer in wb.get('offers',{}).items()):
            raise ValueError('Merchant offer identity is already bound to another product.')
        wb.setdefault('offers',{})[pid] = deepcopy(payload)
        product['price_cents'] = payload['price_cents']; product['price_basis'] = 'human-reviewed offer declaration; not independently fetched'
        wb['catalog'] = cat
    elif operation == 'propose_source':
        sid = payload.get('source_id'); original = cat['sources'].get(sid)
        if original is None or set(payload) != {'source_id','replacement','reason'}: raise ValueError('Choose an existing source and provide replacement and reason.')
        replacement = payload['replacement']
        if type(replacement) is not dict: raise ValueError('Replacement must be a source record.')
        _text(payload['reason'],'review reason')
        if replacement.get('product_id') != original['product_id'] or replacement.get('variant') != original['variant'] or replacement.get('field') != original['field']:
            raise ValueError('Replacement must preserve product, field and exact variant.')
        proposed = deepcopy(cat); proposed['sources'][sid] = deepcopy(replacement)
        for product in proposed['products']:
            for obs in product['observations']:
                if obs['source_id'] == sid: obs['value'] = replacement['value']
        evidence_catalog.validate_catalog(proposed) if new['catalog_kind']=='curated' else evidence_catalog.validate_source(replacement)
        if freshness(replacement, settings(new).evidence_max_age_days)['status'] != 'current': raise ValueError('Replacement needs a current review date.')
        proposal = {'source_id':sid,'replacement':deepcopy(replacement),'reason':payload['reason'],'before_sha256':digest(original)}
        proposal['id'] = digest(proposal)
        wb['pending_source'] = proposal
    elif operation == 'accept_source':
        proposal = wb.get('pending_source')
        if not proposal or payload.get('proposal_id') != proposal['id'] or payload.get('reviewed') is not True: raise ValueError('Review and accept the exact pending source proposal.')
        sid = proposal['source_id']
        if digest(cat['sources'][sid]) != proposal['before_sha256']: raise ValueError('Source changed after proposal; review again.')
        cat['sources'][sid] = deepcopy(proposal['replacement'])
        for product in cat['products']:
            for obs in product['observations']:
                if obs['source_id']==sid: obs['value']=proposal['replacement']['value']
        new['inspected'] = [s for s in new['inspected'] if s != sid]
        wb.setdefault('source_reviews',[]).append({**proposal,'accepted_on':current_day().isoformat(),'basis':'explicit human review, not independent source verification'})
        wb['source_reviews'] = wb['source_reviews'][-24:]
        wb['catalog'] = cat; wb.pop('pending_source')
    elif operation == 'undo_preference':
        if not new['history']: raise ValueError('No preference comparison to undo.')
        new['history'].pop()
    elif operation in ('delete_preference','edit_preference'):
        index = _integer(payload.get('index'),0,len(new['history'])-1,'History index')
        if operation == 'delete_preference': new['history'].pop(index)
        else:
            if payload.get('choice') not in ('a','b','tie','skip'): raise ValueError('Unknown comparison choice.')
            new['history'][index]['choice'] = payload['choice']
    elif operation == 'revise_goal':
        new['goal'] = agent.goal_for({**new['goal'],**payload},new['catalog_kind'],cat).model_dump()
        new['driver_answered'] = None
    else:
        raise ValueError('Unknown human workbench action.')
    # Structural changes clear old preference evidence rather than transferring
    # learned utility to changed source values, prices or requirements.
    if not history_only and operation != 'propose_source': new['history'] = []
    new.update(personalized=preferences.active(new['history']), recommended_id=None,status='ACTIVE',pending_question=None,revision=new['revision']+1)
    after={'goal':new['goal'],'requirements':wb['requirements'],'excluded':new['excluded']}
    diff={key:{'before':before[key],'after':deepcopy(after[key])} for key in before if before[key] != after[key]}
    new['events']=(new['events']+[{'index':agent.event_index(new),'origin':'human','action':{'action':operation},'response':{'diff':diff,'recommendation_cleared':True},'revision':new['revision']}])[-48:]
    return new


def summary(record):
    cat = catalog(record); all_rows=list(rows(record)); valid=rank(record,all_rows)
    req=settings(record)
    probability=preferences.distribution(record['history'],[r for r in all_rows if r['valid']],cat)
    import numpy as np
    intervals={}
    for i,name in enumerate(preferences.FEATURES):
        order=np.argsort(preferences.PARTICLES[:,i]); cumulative=np.cumsum(probability[order])
        intervals[name]={'mean':float(probability @ preferences.PARTICLES[:,i]),'q05':float(preferences.PARTICLES[order[np.searchsorted(cumulative,.05)],i]),'q95':float(preferences.PARTICLES[order[np.searchsorted(cumulative,.95)],i])}
    compared=[]
    for row in valid[:12]:
        features=preferences.features(row,cat); mean=probability @ preferences.PARTICLES
        compared.append({'id':row['id'],'items':row['items'],'total_cents':row['total_cents'],'changed_slots':changed_slots(record,row),'checks':row['checks'],
                         'contributions':dict(zip(preferences.FEATURES,map(float,features*mean)))})
    field_checks={'protocol':['transport','driver','displays'],'displays':['displays'],'max_height':['resolution'],'height':['resolution','cables'],'max_hz':['refresh'],'hz':['refresh'],'pd_watts':['charging','charging_target'],'watts':['charging','charging_target'],'connector':['cables'],'count':['cables'],'hdcp':['hdcp'],'gaming':['gaming'],'minimum_os':['os_version'],'output_connector':['dock_output'],'direction':['connector_direction'],'adapter_for':['adapter_match']}
    selected_ids={i['product_id'] for i in valid[0]['items']} if valid else set()
    selected_checks=set(valid[0]['checks']) if valid else set()
    kinds={p['id']:p['kind'] for p in cat['products']}
    def used_checks(source):
        if source['product_id'] not in selected_ids:return []
        checks=field_checks.get(source['field'],[])
        if source['field']=='height':
            checks=['cables'] if kinds[source['product_id']]=='cable' else ['resolution']
        return [check for check in checks if check in selected_checks]
    dependencies=[{'source_id':sid,'product_id':cat['sources'][sid]['product_id'],'field':cat['sources'][sid]['field'],
                   'checks':used_checks(cat['sources'][sid]),
                   'freshness':freshness(cat['sources'][sid],req.evidence_max_age_days)} for sid in record['inspected'] if sid in cat['sources']]
    duplicate_groups={}
    for product in cat['products']:
        key=(product['kind'],re.sub(r'[^a-z0-9]','',product['name'].casefold()),product.get('variant',product['id']).casefold())
        duplicate_groups.setdefault(key,[]).append(product['id'])
    return {'duplicate_products':[ids for ids in duplicate_groups.values() if len(ids)>1],'schema':'intentcart-workbench/1','revision':record['revision'],'checkout_supported':False,
            'catalog_sha256':digest(cat),'requirements':req.model_dump(),
            'products':[{k:v for k,v in p.items() if k!='observations'} for p in cat['products']],
            'laptop_sources':[{**p,'source_sha256':digest(p)} for p in cat['laptops']],'sources':dependencies,'configurations':compared,
            'uncertainty':intervals,'uncertainty_notice':'Posterior particle quantiles under a declared finite model; not calibrated confidence in user satisfaction.',
            'history':record['history'],'question_burden':{'permission_questions':sum(e['action']['action']=='clarify' for e in record['events']),
            'retained_pairwise_answers':len(record['history']),'skips':sum(h['choice']=='skip' for h in record['history']), 'timeline_window':len(record['events'])},
            'pending_source':record.get('workbench',{}).get('pending_source'), 'offers':record.get('workbench',{}).get('offers',{}),
            'excluded':record['excluded'],'supported_count':len(valid),'candidate_count':len(all_rows),
            'conflicts':sorted({k for row in all_rows for k in row['failed']}),
            'notice':'Human-reviewed planning declarations; no hardware certification, live merchant verification or checkout authority.'}


def bill_of_materials(record):
    candidates=rank(record)
    if not candidates: raise ValueError('No supported configuration to export.')
    products={p['id']:p for p in catalog(record)['products']}
    stream=io.StringIO(newline='');writer=csv.writer(stream)
    writer.writerow(['product_id','name','variant','quantity','unit_cents','line_cents','price_basis'])
    def safe(value):
        text=str(value)
        return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r')) else text
    for item in candidates[0]['items']:
        p=products[item['product_id']]
        writer.writerow([safe(p['id']),safe(p['name']),safe(p.get('variant',p['id'])),item['quantity'],p['price_cents'],p['price_cents']*item['quantity'],safe(p.get('price_basis','fictional fixture'))])
    return stream.getvalue()


def decision_report(record):
    result=summary(record)
    lines=['IntentCart decision report',f"Revision: {record['revision']}",f"Catalog identity: {result['catalog_sha256']}",
           f"Supported configurations: {result['supported_count']} of {result['candidate_count']}",'Checkout authority: none',result['notice']]
    for c in result['configurations'][:4]:
        lines += [f"\nBasket {c['id']}: USD {c['total_cents']/100:.2f}",f"Changed slots: {', '.join(c['changed_slots']) or 'none / initial plan'}"]
        lines += [f"  {i['quantity']} x {i['product_id']}" for i in c['items']]
    lines += ['\nEvidence freshness:']+[f"  {s['source_id']}: {s['freshness']['status']}" for s in result['sources']]
    if not result['supported_count']: lines += ['Conflicts: '+', '.join(result['conflicts'])]
    return '\n'.join(lines)+'\n'


def counterfactual(record, changes):
    from . import agent
    if not isinstance(changes,list) or not 1 <= len(changes) <= 8: raise ValueError('Supply one to eight reviewed counterfactual goals.')
    reports=[]
    for change in changes:
        revised=mutate(record,'revise_goal',change)
        result=summary(revised)
        reports.append({'changes':change,'supported':result['supported_count'],'configurations':result['configurations'][:2], 'conflicts':result['conflicts']})
    return {'schema':'intentcart-counterfactual/1','base_revision':record['revision'],'hypothetical':True,'mutates_task':False,'checkout_supported':False,'scenarios':reports}
