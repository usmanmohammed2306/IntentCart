"""Explicit synthetic hardware worlds and a small independently stated oracle.

The oracle reads the declared world/request directly. It does not call the
planner, reuse its checks or grade against another invocation of the same code.
It is finite fixture truth, not a manufacturer or physical-hardware claim.
"""
from copy import deepcopy
from datetime import date
from itertools import product
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart import agent, evidence_catalog, missions, workbench

AXES = {
    'display_capacity': [2, 3], 'height_capacity': [1080, 2160],
    'refresh_capacity': [60, 120], 'power_capacity': [65, 100],
    'hdcp_capability': [False, True], 'gaming_capability': [False, True],
    'protocol': ['usb-c', 'displaylink'],
    'displays': [2, 3], 'height': [1080, 2160], 'hz': [60, 120],
    'charging_watts': [0, 90], 'hdcp': [False, True], 'gaming': [False, True],
    'allow_driver': [False, True], 'available': [False, True],
    'costs_known': [False, True], 'budget_gap_cents': [-1, 0, 1],
}
WORLD_KEYS = list(AXES)[:7]
REQUEST_KEYS = list(AXES)[7:14]
DOCK = 'synthetic-combination-dock'
SOURCE = DOCK + '-displays'
TOTAL_CASES = 3 * 2**16


def axis_rows(keys):
    for values in product(*(AXES[key] for key in keys)):
        yield dict(zip(keys, values))


def case_from_id(index):
    if not 0 <= index < TOTAL_CASES:
        raise ValueError('Case index outside the finite declared matrix.')
    # Mixed radix, exactly matching itertools.product with the final axis fastest.
    result = {}
    for key in reversed(AXES):
        index, remainder = divmod(index, len(AXES[key]))
        result[key] = AXES[key][remainder]
    return {key: result[key] for key in AXES}


def subtotal(displays, owned=1):
    # One dock, required purchased monitors, one cable kit, one power adapter.
    return 10000 + 5000 * max(0, displays-owned) + 1500 + 2500


def expected_support(case):
    return (
        case['display_capacity'] >= case['displays']
        and case['height_capacity'] >= case['height']
        and case['refresh_capacity'] >= case['hz']
        and case['power_capacity'] >= case['charging_watts']
        and (not case['hdcp'] or case['hdcp_capability'])
        and (not case['gaming'] or case['gaming_capability'])
        and (case['protocol'] != 'displaylink' or case['allow_driver'])
        and case['available'] and case['costs_known'] and case['budget_gap_cents'] >= 0
    )


def synthetic_catalog(world, as_of):
    if type(as_of) is not date:
        raise ValueError('Synthetic review needs an explicit snapshot date.')
    values = {
        'dock': {'protocol': world['protocol'], 'displays': world['display_capacity'],
                 'max_height': world['height_capacity'], 'max_hz': world['refresh_capacity'],
                 'pd_watts': world['power_capacity'], 'hdcp': world['hdcp_capability'],
                 'gaming': world['gaming_capability'], 'minimum_os': '12.0',
                 'output_connector': 'hdmi'},
        'monitor': {'height': world['height_capacity'], 'hz': world['refresh_capacity'], 'connector': 'hdmi'},
        'cable': {'height': world['height_capacity'], 'hz': world['refresh_capacity'],
                  'count': 4, 'connector': 'hdmi', 'direction': 'dock-to-display'},
        'power': {'watts': world['power_capacity'], 'adapter_for': DOCK},
    }
    catalog = {
        'schema': evidence_catalog.SCHEMA,
        'notice': 'Explicitly synthetic combinatorial fixture. No real product or physical truth claim.',
        'warnings': [], 'laptops': [{
            'id': 'synthetic-combination-laptop', 'name': 'Synthetic finite-matrix laptop',
            'variant': 'fictional-v1', 'protocols': ['usb-c', 'displaylink'],
            'native_displays': 4, 'charge_watts': 30,
            'source_url': 'https://support.apple.com/', 'observed_on': as_of.isoformat(),
            'source_summary': 'Synthetic declaration only; this URL does not substantiate fixture capabilities.'}],
        'products': [], 'sources': {},
    }
    prices = {'dock': 10000, 'monitor': 5000, 'cable': 1500, 'power': 2500}
    for kind, fields in values.items():
        pid = 'synthetic-combination-' + kind
        item = {'id': pid, 'name': 'Synthetic '+kind, 'kind': kind,
                'variant': 'fictional-v1', 'price_cents': prices[kind], 'observations': []}
        for field, value in fields.items():
            sid = pid+'-'+field
            item['observations'].append({'field': field, 'value': value, 'source_id': sid, 'visible': False})
            catalog['sources'][sid] = {
                'product_id': pid, 'variant': 'fictional-v1', 'field': field, 'value': value,
                'unit': missions.FACT_UNITS[field], 'kind': 'scenario_declaration', 'url': '',
                'observed_on': as_of.isoformat(), 'summary': 'Authored finite-matrix fixture, not human/merchant evidence.'}
        catalog['products'].append(item)
    return evidence_catalog.validate_catalog(catalog)


def imported_record(world, as_of):
    base = agent.create('Synthetic combinatorial verification', {}, 'curated', 32, True)
    catalog = synthetic_catalog(world, as_of)
    record = workbench.mutate(base, 'import_catalog', {
        'catalog': catalog, 'reviewed': True,
        'base_sha256': workbench.digest(workbench.catalog(base)),
        'goal': {'laptop_id': 'synthetic-combination-laptop', 'displays': 2,
                 'height': 1080, 'hz': 60, 'budget_cents': 100000, 'allow_driver': True,
                 'reuse_monitor': True},
    })
    record['inspected'] = list(catalog['sources'])
    record['discovered'] = [p['id'] for p in catalog['products']]
    record['workbench']['requirements'] = {
        'owned_monitors': [{'name': 'Synthetic owned high-capability screen',
                            'height': 2160, 'hz': 120, 'connector': 'hdmi'}],
    }
    return record


def case_record(base, case, as_of):
    """Construct an explicit immutable test state; not simulated UI interaction.

    Import validation happens in imported_record. Pydantic validates each goal
    and Requirements validates each request. Raw state construction here makes
    exhaustive validator testing practical; it cannot establish endpoint safety.
    """
    record = dict(base)
    record['goal'] = agent.goal_for({**base['goal'], **{key: case[key] for key in ('displays', 'height', 'hz', 'allow_driver')},
                                   'budget_cents': subtotal(case['displays']) + case['budget_gap_cents']},
                                  'curated', workbench.catalog(base)).model_dump()
    req = workbench.Requirements.model_validate({**base['workbench']['requirements'],
        **{key: case[key] for key in ('charging_watts', 'hdcp', 'gaming')},
        'tax_cents': 0 if case['costs_known'] else None, 'shipping_cents': 0}).model_dump()
    record['workbench'] = {**base['workbench'], 'requirements': req, 'offers': {DOCK: {
        'product_id': DOCK, 'variant': 'fictional-v1', 'merchant': 'Synthetic merchant',
        'offer_id': 'FICTIONAL-MATRIX-OFFER', 'price_cents': 10000,
        'observed_on': as_of.isoformat(), 'available': case['available']}}}
    return record


def positive_case(**overrides):
    result = {key: values[-1] for key, values in AXES.items()}
    result.update(protocol='displaylink', allow_driver=True, budget_gap_cents=0,
                  displays=2, height=1080, hz=60, charging_watts=90,
                  hdcp=True, gaming=True)
    result.update(overrides)
    return result
