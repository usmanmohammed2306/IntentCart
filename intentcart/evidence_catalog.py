"""Curated, bounded manufacturer evidence. Never a retailer checkout catalog.

Summaries were manually checked on October 14, 2026. Prices are declared
planning allowances; user equipment is an explicit scenario assumption.
No network, provider, storage or credential access occurs in this module.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from pydantic import Field
from .missions import Goal, FACT_UNITS

SCHEMA = 'intentcart-evidence-catalog/1'
ROOT = Path(__file__).parent
APPROVED_HOSTS = {'plugable.com', 'support.apple.com', 'www.dell.com', 'www.delltechnologies.com'}

class EvidenceGoal(Goal):
    displays: int = Field(default=2, ge=1, le=4, strict=True)
    laptop_id: str = Field(default='macbook-air-m1-2020', min_length=1, max_length=80)

def identity(catalog):
    return hashlib.sha256(json.dumps(catalog, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def validate_catalog(catalog):
    if not isinstance(catalog, dict) or catalog.get('schema') != SCHEMA:
        raise ValueError('Unsupported evidence catalog.')
    if not 1 <= len(catalog.get('products', [])) <= 24 or not 1 <= len(catalog.get('laptops', [])) <= 8:
        raise ValueError('Catalog exceeds bounded planning limits.')
    sources = catalog.get('sources', {})
    if not isinstance(sources, dict) or len(sources) > 256:
        raise ValueError('Invalid source collection.')
    ids = set()
    for item in catalog['products']:
        if item['id'] in ids or item['kind'] not in ('dock', 'monitor', 'cable', 'power'):
            raise ValueError('Duplicate product or unknown component kind.')
        ids.add(item['id'])
        if type(item['price_cents']) is not int or not 0 <= item['price_cents'] <= 300000:
            raise ValueError('Invalid planning allowance.')
        for observation in item['observations']:
            field, value = observation['field'], observation['value']
            if field not in FACT_UNITS or type(observation.get('visible')) is not bool:
                raise ValueError('Invalid observation field or visibility.')
            validate_value(field, value)
            source = sources.get(observation['source_id'])
            if not source or source['product_id'] != item['id'] or source['variant'] != item['variant']:
                raise ValueError('Source belongs to another product variant.')
            if source['field'] != observation['field'] or source['value'] != observation['value']:
                raise ValueError('Source value does not support the observation.')
            if source['unit'] != FACT_UNITS.get(source['field']):
                raise ValueError('Source units do not match the planning field.')
            validate_source(source)
            if source['kind'] == 'manufacturer':
                url = urlsplit(source['url'])
                if url.scheme != 'https' or url.hostname not in APPROVED_HOSTS or url.username or url.password:
                    raise ValueError('Unreviewed manufacturer origin.')
            elif source['kind'] != 'scenario_declaration' or source.get('url'):
                raise ValueError('Unknown source authority.')
    used_sources={o['source_id'] for p in catalog['products'] for o in p['observations']}
    if set(sources)!=used_sources or any(type(sid) is not str or not 1<=len(sid)<=100 for sid in sources):
        raise ValueError('Every bounded source must bind to a represented product observation.')
    laptop_ids = [p['id'] for p in catalog['laptops']]
    if len(set(laptop_ids)) != len(laptop_ids) or set(laptop_ids) & ids:
        raise ValueError('Duplicate laptop identity.')
    for laptop in catalog['laptops']:
        if type(laptop.get('source_url')) is not str or len(laptop['source_url'])>2048:
            raise ValueError('Laptop source URL must be bounded text.')
        url = urlsplit(laptop['source_url'])
        date.fromisoformat(laptop['observed_on'])
        if not isinstance(laptop.get('variant'),str) or not laptop['variant']:
            raise ValueError('Laptop needs an exact variant identity.')
        if url.scheme != 'https' or url.hostname not in APPROVED_HOSTS or url.username or url.password:
            raise ValueError('Unreviewed laptop source.')
        if type(laptop['native_displays']) is not int or not 1 <= laptop['native_displays'] <= 8:
            raise ValueError('Invalid native display limit.')
        if type(laptop['charge_watts']) is not int or not 1 <= laptop['charge_watts'] <= 240:
            raise ValueError('Invalid declared charging target.')
        if not isinstance(laptop['protocols'], list) or not laptop['protocols'] or any(p not in ('displaylink', 'usb-c', 'tb3', 'tb4') for p in laptop['protocols']):
            raise ValueError('Invalid laptop transport declarations.')
    return deepcopy(catalog)

def load_catalog():
    return validate_catalog(json.loads((ROOT / 'data/evidence-catalog.json').read_text()))

def validate_goal(goal, catalog):
    goal = EvidenceGoal.model_validate(goal)
    if goal.laptop_id not in {p['id'] for p in catalog['laptops']}:
        raise ValueError('Choose an exact laptop in the reviewed catalog.')
    return goal

def public_catalog(catalog):
    return {k: deepcopy(catalog[k]) for k in ('schema', 'notice', 'laptops', 'warnings')} | {
        'source_sha256': identity(catalog), 'checkout_supported': False,
        'products': [{k: v for k, v in item.items() if k != 'observations'} for item in catalog['products']],
        'goal_schema': EvidenceGoal.model_json_schema()}


def validate_value(field, value):
    enums = {'protocol': {'displaylink','usb-c','tb3','tb4'}, 'connector': {'hdmi','displayport','usb-c'},
             'output_connector': {'hdmi','displayport','usb-c'}, 'direction': {'dock-to-display','display-to-dock','bidirectional'}}
    if field in enums:
        if type(value) is not str or value not in enums[field]: raise ValueError('Unknown transport or connector value.')
    elif field in ('hdcp','gaming'):
        if type(value) is not bool: raise ValueError('Capability evidence must be an explicit boolean.')
    elif field == 'minimum_os':
        from .workbench import version
        if type(value) is not str: raise ValueError('OS evidence must be a version string.')
        version(value)
    elif field == 'adapter_for':
        if type(value) is not str or not value or len(value)>100: raise ValueError('Adapter evidence needs an exact dock identity.')
    elif field not in FACT_UNITS or type(value) is not int or not 1 <= value <= 10000:
        raise ValueError('Numeric evidence must be a bounded integer with declared units.')


def validate_source(source):
    if type(source) is not dict: raise ValueError('Source must be a record.')
    required={'product_id','variant','field','value','unit','kind','url','observed_on'}
    if not required <= set(source): raise ValueError('Source identity fields are incomplete.')
    if not (source['kind']=='scenario_declaration' and source['url'] is None):
        if type(source['url']) is not str or len(source['url'])>2048:
            raise ValueError('Source URL must be bounded text or absent for a scenario declaration.')
    for key in ('summary','excerpt'):
        if key in source and (type(source[key]) is not str or len(source[key])>2000):
            raise ValueError('Source descriptions must be bounded text.')
    validate_value(source['field'],source['value'])
    if source['unit'] != FACT_UNITS.get(source['field']): raise ValueError('Source unit does not match field.')
    date.fromisoformat(source['observed_on'])
    for key in ('product_id','variant'):
        if type(source[key]) is not str or not 0 < len(source[key]) <= 200: raise ValueError('Invalid source identity.')
    if source['kind']=='manufacturer':
        url=urlsplit(source['url'])
        if url.scheme!='https' or url.hostname not in APPROVED_HOSTS or url.username or url.password: raise ValueError('Unreviewed manufacturer origin.')
    elif source['kind']!='scenario_declaration' or source['url']:
        raise ValueError('Unknown source authority.')
    return deepcopy(source)
