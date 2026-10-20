"""Offline fictional-persona rehearsal; never a human participant study."""
import argparse
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart import agent, workbench


def finish(record, driver=True):
    """Drive the real local policy with explicitly scripted permission answers."""
    for _ in range(64):
        if record['pending_question']:
            record = agent.answer(record, driver, origin='scripted_user')
        if record['status'] != 'ACTIVE':
            return record
        record = agent.step(record, agent.local_action(record))
    raise RuntimeError('Rehearsal exceeded its local action bound.')


def snapshot(record):
    ranked = workbench.rank(record)
    return {
        'status': record['status'], 'revision': record['revision'],
        'supported_baskets': len(ranked), 'inspection_count': len(record['inspected']),
        'recommended': record['recommended_id'] is not None,
        'best_total_cents': ranked[0]['total_cents'] if ranked else None,
        'allow_driver': record['goal']['allow_driver'],
        'checkout_authority': False,
    }


def evaluate(as_of):
    if type(as_of) is not date:
        raise ValueError('Supply an explicit snapshot date.')
    records = []
    with patch.object(workbench, 'current_day', return_value=as_of):
        def fresh(driver=True, goal=None):
            return finish(agent.create('Fictional workstation rehearsal', goal or {},
                                       'curated', 32, True), driver)

        def record(pid, name, brief, stages, checks):
            records.append({'id': pid, 'fictional_name': name,
                            'persona_is_fictional': True, 'scenario': brief,
                            'answer_provenance': 'authored deterministic script',
                            'stages': stages, 'checks': checks,
                            'all_checks_pass': all(checks.values())})

        base = fresh()
        record('S01', 'Mira — budget keeper', 'Two Full HD displays, one retained, USD 350 cap; scripted driver permission.',
               {'final': snapshot(base)}, {'supported': bool(workbench.rank(base)),
                'recommended': base['status'] == 'RECOMMENDED',
                'within_budget': bool(workbench.rank(base)) and workbench.rank(base)[0]['total_cents'] <= 35000})

        denied = fresh(False)
        record('S02', 'Noah — driver cautious', 'Decline the driver request.',
               {'final': snapshot(denied)}, {'permission_not_granted': not denied['goal']['allow_driver'],
                'no_supported_basket': not workbench.rank(denied), 'no_recommendation': denied['recommended_id'] is None})

        unknown = workbench.mutate(base, 'requirements', {'tax_cents': None, 'shipping_cents': None})
        record('S03', 'Leena — price skeptic', 'Replace declared zero tax/shipping allowances with unknown values.',
               {'before': snapshot(base), 'after': snapshot(unknown)},
               {'unknown_cost_blocks_support': not workbench.rank(unknown),
                'acceptance_cleared': unknown['recommended_id'] is None})

        gaming = workbench.mutate(base, 'requirements', {'gaming': True})
        record('S04', 'Jules — gamer', 'Require gaming capability without supporting reviewed evidence.',
               {'after': snapshot(gaming)}, {'unsupported_capability_blocks_support': not workbench.rank(gaming),
                'acceptance_cleared': gaming['recommended_id'] is None})

        removed = agent.revise(base, exclude='plugable-ud6950pdh')
        repaired = workbench.mutate(removed, 'restore_product', {'product_id': 'plugable-ud6950pdh'})
        record('S05', 'Sam — repair planner', 'Remove the only supporting dock; restore its availability in the scenario.',
               {'removed': snapshot(removed), 'restored': snapshot(repaired)},
               {'removal_blocks_support': not workbench.rank(removed),
                'restoration_recovers_support': bool(workbench.rank(repaired)),
                'restoration_does_not_auto_accept': repaired['recommended_id'] is None})

        sid = 'plugable-ud6950pdh-displays'
        replacement = deepcopy(workbench.catalog(base)['sources'][sid])
        replacement['value'] = 1
        proposed = workbench.mutate(base, 'propose_source', {
            'source_id': sid, 'replacement': replacement, 'reason': 'Explicit hypothetical one-display correction'})
        accepted = workbench.mutate(proposed, 'accept_source', {
            'proposal_id': proposed['workbench']['pending_source']['id'], 'reviewed': True})
        record('S06', 'Ari — source reviewer', 'Propose then script acceptance of a hypothetical two-to-one-display source correction.',
               {'proposed': snapshot(proposed), 'accepted': snapshot(accepted)},
               {'proposal_does_not_replace_source': workbench.catalog(proposed)['sources'][sid]['value'] == 2,
                'exact_acceptance_changes_source': workbench.catalog(accepted)['sources'][sid]['value'] == 1,
                'changed_source_needs_reinspection': sid not in accepted['inspected'],
                'stale_recommendation_cleared': accepted['recommended_id'] is None,
                'no_supported_basket': not workbench.rank(accepted)})

        withdrawn = workbench.mutate(base, 'withdraw_driver', {})
        record('S07', 'Tess — permission revoker', 'Withdraw previously scripted driver permission.',
               {'after': snapshot(withdrawn)}, {'permission_revoked': not withdrawn['goal']['allow_driver'],
                'no_supported_basket': not workbench.rank(withdrawn),
                'stale_recommendation_cleared': withdrawn['recommended_id'] is None})

        tight = fresh(goal={'budget_cents': 10000})
        record('S08', 'Dev — strict budget', 'Request the same setup under a USD 100 cap.',
               {'final': snapshot(tight)}, {'no_supported_basket': not workbench.rank(tight),
                'no_recommendation': tight['recommended_id'] is None})

    sources = ['scripts/rehearse_workstation.py', 'intentcart/agent.py',
               'intentcart/workbench.py', 'intentcart/missions.py',
               'intentcart/evidence_catalog.py', 'intentcart/workspace_preferences.py',
               'intentcart/data/evidence-catalog.json', 'intentcart/data/missions-catalog.json']
    return {
        'schema': 'intentcart-synthetic-workstation-rehearsal/1',
        'evidence_class': 'synthetic_scripted_scenarios',
        'notice': 'FICTIONAL PERSONAS. No people, consent, human observations, usability ratings or live model trials.',
        'snapshot_date': as_of.isoformat(), 'clock': 'explicit frozen scenario date; not current source freshness',
        'human_participants': 0, 'consent_records': 0, 'provider_requests': 0,
        'payment_operations': 0, 'cash_spend_usd': 0,
        'fictional_personas': len(records), 'scenario_checks': sum(len(r['checks']) for r in records),
        'passed_checks': sum(sum(r['checks'].values()) for r in records),
        'all_checks_pass': all(r['all_checks_pass'] for r in records),
        'sources': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sorted(set(sources))},
        'records': records,
        'limitations': [
            'Authored correlated cases share one curated catalog and the same final validator.',
            'Scripted permissions and source acceptance are simulated inputs, never actual user consent.',
            'Passing checks establish these specified software behaviors only; usability and human benefit remain unmeasured.',
            'No fabricated quotes, completion times, satisfaction scores or recruitment records.',
            'Roadmap 88 remains pending: a consented participant study was not conducted.',
        ],
    }


def markdown(report):
    lines = ['# Synthetic workstation rehearsal', '', '**Fictional personas — zero human participants.**', '',
             f"Snapshot: {report['snapshot_date']}; local deterministic policy, no model or payment calls.", '',
             '| Fictional persona | Scripted scenario | Software checks |', '|---|---|---|']
    for r in report['records']:
        lines.append(f"| {r['fictional_name']} | {r['scenario']} | {sum(r['checks'].values())}/{len(r['checks'])} |")
    lines += ['', f"Observed software checks: **{report['passed_checks']}/{report['scenario_checks']}** across {report['fictional_personas']} authored scenarios. This is not a participant success rate.", '',
              'Reproduce:', '', '```sh',
              f".venv/bin/python scripts/rehearse_workstation.py --as-of {report['snapshot_date']} --output output/synthetic-workstation-rehearsal.json --markdown output/synthetic-workstation-rehearsal.md",
              '```', '', 'The companion JSON retains each stage, expected check and source hash. A blocked basket is an intended result where support is missing. No usability observation or user feedback is inferred.', '']
    lines += ['- ' + item for item in report['limitations']]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', type=date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--markdown', type=Path)
    args = parser.parse_args()
    destinations = [args.output] + ([args.markdown] if args.markdown else [])
    if len({p.resolve() for p in destinations}) != len(destinations) or any(p.exists() for p in destinations):
        parser.error('Use distinct new output paths; existing evidence is never overwritten.')
    report = evaluate(args.as_of)
    for path, content in [(args.output, json.dumps(report, indent=2) + '\n')] + ([(args.markdown, markdown(report))] if args.markdown else []):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x') as handle:
            handle.write(content)
    print(json.dumps({k: report[k] for k in ('evidence_class', 'human_participants', 'fictional_personas', 'passed_checks', 'scenario_checks', 'all_checks_pass')}))
    return 0 if report['all_checks_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
