"""Expanded fictional cast with composed, branching offline software scenarios."""
import argparse
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart import agent, workbench
from scripts.rehearse_complex_personas import Journey, DOCK, SOURCE

PROTOCOL = ROOT / 'docs/protocols/persona-cohort.json'


def load_protocol():
    protocol = json.loads(PROTOCOL.read_text())
    earlier = json.loads((ROOT / protocol['prior_profiles']).read_text())
    profiles = []
    for original in earlier['personas']:
        p = deepcopy(original)
        p['prior_workflow'] = True
        p['decision_owner'] = 'The fictional scenario author defines revisions; no real permission is collected.'
        p['reactions'] = protocol['prior_reactions'][p['id']]
        profiles.append(p)
    profiles += deepcopy(protocol['personas'])
    ids = [p['id'] for p in profiles]
    if len(ids) != len(set(ids)):
        raise ValueError('Fictional persona IDs must be unique.')
    for p in profiles:
        if len(p['reactions']) != 3 or any(choice not in allowed for choice, allowed in zip(
                p['reactions'], ({'stop', 'extend'}, {'stop', 'correct'}, {'stop', 'refresh'}))):
            raise ValueError('Each persona needs explicit, bounded recovery rules.')
    return protocol, profiles


def resolve(value, as_of):
    dates = {'$tomorrow': as_of+timedelta(days=1), '$stale': as_of-timedelta(days=8),
             '$two_days_ago': as_of-timedelta(days=2)}
    if isinstance(value, str) and value in dates:
        return dates[value].isoformat()
    if isinstance(value, dict):
        return {key: resolve(item, as_of) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, as_of) for item in value]
    return value


def execute(journey, instruction):
    step = resolve(instruction, journey.as_of)
    kind, intent = step['kind'], step['intent']
    if kind == 'change':
        journey.change(intent, step['operation'], step['payload'], step.get('supported'))
    elif kind == 'reject':
        journey.reject(intent, step['operation'], step['payload'])
    elif kind == 'drive':
        journey.drive(intent, step['expected'], step.get('driver'))
    elif kind in ('offer', 'reject_offer'):
        payload = journey.offer(**step['changes'])
        if kind == 'offer':
            journey.change(intent, 'offer', payload, step.get('supported'))
        else:
            journey.reject(intent, 'offer', payload)
    elif kind == 'monitor':
        monitor = {'name': 'Explicit fictional inventory declaration', 'height': 1080,
                   'hz': 60, 'connector': step.get('connector', 'hdmi')}
        payload = {'owned_monitors': [monitor] * step.get('count', 1)}
        if step.get('reject'):
            journey.reject(intent, 'requirements', payload)
        else:
            journey.change(intent, 'requirements', payload, step.get('supported'))
    elif kind == 'quantity':
        rows = workbench.rank(journey.state)
        products = {p['id']: p for p in workbench.catalog(journey.state)['products']}
        count = sum(item['quantity'] for item in rows[0]['items'] if products[item['product_id']]['kind'] == 'monitor') if rows else None
        journey.observe(intent, {'purchase_quantity_matches_inventory': count == step['expected']},
                        {'expected_purchased_monitors': step['expected']}, note=f'Actual purchased-monitor quantity: {count}')
    elif kind == 'preview':
        before = deepcopy(journey.state)
        result = workbench.counterfactual(journey.state, step['scenarios'])
        journey.observe(intent, {'preview_does_not_mutate': journey.state == before,
                                'preview_has_no_checkout': result['checkout_supported'] is False,
                                'all_requested_scenarios_returned': len(result['scenarios']) == len(step['scenarios'])},
                        {'scenarios': step['scenarios']}, note=json.dumps(result, sort_keys=True))
    elif kind == 'source':
        journey.source(step['value'])
    elif kind == 'accept':
        journey.change(intent, 'accept_source', {'proposal_id': journey.state['workbench']['pending_source']['id'],
                       'reviewed': True}, step['supported'])
    elif kind == 'invalid_source':
        source = deepcopy(workbench.catalog(journey.state)['sources'][SOURCE])
        source['url'] = 'https://fictional-user:fictional-pass@plugable.com/review'
        journey.reject(intent, 'propose_source', {'source_id': SOURCE, 'replacement': source,
                        'reason': 'Fictional invalid input; not account credentials'})
    elif kind == 'duplicate_offer':
        cat = workbench.catalog(journey.state)
        product = next(p for p in cat['products'] if p['kind'] == 'monitor')
        payload = journey.offer(product_id=product['id'], variant=product['variant'], price_cents=15000)
        journey.reject(intent, 'offer', payload)
    elif kind == 'invalid_comparison':
        before = deepcopy(journey.state)
        rows = workbench.rank(journey.state)
        basket = rows[0]['id'] if rows else 'fictional-unavailable-basket'
        error = None
        try:
            agent.compare(journey.state, basket, basket, 'a')
        except ValueError as exc:
            error = str(exc)
        journey.observe(intent, {'invalid_comparison_rejected': error is not None,
                                'no_preference_evidence_invented': journey.state == before}, note=error)
    elif kind == 'report':
        text = workbench.decision_report(journey.state)
        journey.observe(intent, {'explanation_retains_no_checkout': 'Checkout authority: none' in text,
                                'report_binds_current_revision': f"Revision: {journey.state['revision']}" in text})
    else:
        raise ValueError('Unknown bounded scenario instruction: ' + kind)


def stress(journey, condition):
    if condition == 'ordinary':
        return 'Primary workflow only; no extra perturbation.'
    prior = deepcopy(journey.state)
    prior_support = bool(workbench.rank(prior))
    driver = prior['goal']['allow_driver']
    requirements = workbench.settings(prior)
    if condition == 'late-cost-ambiguity':
        tax = None if requirements.tax_cents is None else requirements.tax_cents + 1500
        journey.change('A late note adds USD 15 to the tax allowance while shipping is unresolved',
                       'requirements', {'tax_cents': tax, 'shipping_cents': None}, supported=False)
        if journey.persona['reactions'][0] == 'extend':
            journey.change('Explicitly resolve the shipping note using the prior scenario declaration',
                           'requirements', {'shipping_cents': requirements.shipping_cents})
            journey.change('Explicitly add a USD 15 discretionary scenario allowance', 'revise_goal',
                           {'budget_cents': prior['goal']['budget_cents'] + 1500}, supported=prior_support)
            journey.drive('Request a fresh decision without waiving any technical requirement', prior_support, driver)
            return 'Resolve the cost note and explicitly extend the hypothetical ceiling; hard constraints remain.'
        journey.drive('Stop with the all-in cost unresolved instead of assuming a larger allowance', False, driver)
        return 'Stop: this fictional persona does not grant the larger discretionary allowance.'
    if condition == 'conflicting-inventory':
        wrong = {'name': 'Fictional stale inventory note', 'height': 720, 'hz': 60, 'connector': 'hdmi'}
        journey.change('A second inventory note describes an insufficient owned-screen resolution',
                       'requirements', {'owned_monitors': [wrong]}, supported=False)
        if journey.persona['reactions'][1] == 'correct':
            journey.change('Explicitly restore the earlier fictional inventory declaration', 'requirements',
                           {'owned_monitors': requirements.owned_monitors}, supported=prior_support)
            journey.drive('Ask for a fresh decision after reconciling the scenario notes', prior_support, driver)
            return 'Correct the fictional note; this is not physical equipment verification.'
        journey.drive('Keep the inventory conflict unresolved and defer', False, driver)
        return 'Stop: this fictional persona cannot resolve the contradictory inventory note.'
    if condition == 'stale-offer-after-interruption':
        journey.state = json.loads(json.dumps(journey.state))
        journey.observe('Resume a serialized scenario after a scripted interruption',
                        {'exact_record_roundtrip': journey.state == prior,
                         'support_unchanged_by_roundtrip': bool(workbench.rank(journey.state)) == prior_support},
                        note='JSON round trip only, not an actual browser restart or human distraction.')
        product = next(p for p in workbench.catalog(journey.state)['products'] if p['id'] == DOCK)
        earlier_offer = prior.get('workbench', {}).get('offers', {}).get(DOCK)
        current = journey.offer(price_cents=product['price_cents']) if earlier_offer is None else deepcopy(earlier_offer)
        journey.reject('Return to a copied offer with a mismatched variant after the interruption',
                       'offer', {**current, 'variant': 'fictional-obsolete-model'})
        journey.change('Correct the variant but retain an eight-day-old scenario offer',
                       'offer', {**current, 'observed_on': (journey.as_of-timedelta(days=8)).isoformat()}, supported=False)
        if journey.persona['reactions'][2] == 'refresh':
            journey.change('Explicitly refresh the fictional offer declaration without changing its price',
                           'offer', {**current, 'observed_on': journey.as_of.isoformat()}, supported=prior_support)
            journey.drive('Request a fresh decision after variant and date review', prior_support, driver)
            return 'Refresh the declaration; no merchant lookup or authenticity claim.'
        journey.drive('Decline to treat the expired copied offer as current', False, driver)
        return 'Stop: this fictional persona cannot refresh the offer declaration.'
    raise ValueError('Unknown authored condition.')


def run_profile(profile, condition, as_of):
    journey = Journey(profile, {'id': 'baseline', 'unexpected_cost_cents': 0,
                              'resume_from_snapshot': False}, as_of)
    reason = None
    try:
        if profile.get('prior_workflow'):
            journey.run()
        else:
            for instruction in profile['script']:
                execute(journey, instruction)
        primary_step_count = len(journey.steps)
        primary_final = deepcopy(journey.steps[-1]['state'])
        decision = stress(journey, condition)
    except (ValueError, KeyError, IndexError, RuntimeError) as exc:
        # Keep an unexpected failed path in the report instead of silently dropping it.
        reason = f'{type(exc).__name__}: {exc}'
        journey.observe('Unexpected scenario execution failure retained', {'execution_completed': False}, note=reason)
        primary_step_count = None
        primary_final = None
        decision = 'Execution failed; retained for correction and analysis.'
    return {'persona_id': profile['id'], 'condition': condition, 'is_fictional': True,
            'primary_step_count': primary_step_count, 'primary_final': primary_final,
            'scripted_recovery_decision': decision, 'unexpected_error': reason,
            'steps': journey.steps,
            'all_checks_pass': all(all(s['checks'].values()) for s in journey.steps)}


def evaluate(as_of):
    if type(as_of) is not date:
        raise ValueError('Use an explicit frozen scenario date.')
    protocol, profiles = load_protocol()
    with patch.object(workbench, 'current_day', return_value=as_of):
        journeys = [run_profile(p, condition, as_of) for p in profiles for condition in protocol['conditions']]
    files = ['scripts/rehearse_persona_cohort.py', 'scripts/rehearse_complex_personas.py',
             'scripts/rehearse_workstation.py', str(PROTOCOL.relative_to(ROOT)), protocol['prior_profiles'],
             'intentcart/agent.py', 'intentcart/workbench.py', 'intentcart/missions.py',
             'intentcart/evidence_catalog.py', 'intentcart/workspace_preferences.py',
             'intentcart/data/evidence-catalog.json', 'intentcart/data/missions-catalog.json']
    endings = {}
    for j in journeys:
        final = j['steps'][-1]['state']['status']
        endings[final] = endings.get(final, 0) + 1
    return {'schema': 'intentcart-fictional-persona-cohort-report/1',
            'evidence_class': 'synthetic_scripted_scenarios', 'notice': protocol['notice'],
            'snapshot_date': as_of.isoformat(), 'human_participants': 0, 'consent_records': 0,
            'provider_requests': 0, 'payment_operations': 0, 'cash_spend_usd': 0,
            'fictional_personas': len(profiles), 'conditions': protocol['conditions'],
            'correlated_journeys': len(journeys), 'steps': sum(len(j['steps']) for j in journeys),
            'checks': sum(len(s['checks']) for j in journeys for s in j['steps']),
            'passed_checks': sum(sum(s['checks'].values()) for j in journeys for s in j['steps']),
            'all_checks_pass': all(j['all_checks_pass'] for j in journeys),
            'software_endings': endings, 'profiles': profiles, 'journeys': journeys,
            'sources': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files},
            'limitations': [
                'All identities, contexts, mental models, pressures and reactions are authored fiction, not observed people.',
                'Recovery thresholds and branches are design hypotheses; no behavioral distribution or realism validation exists.',
                'Journeys, steps and repeated invariant checks share one curated catalog and validator; they are correlated software coverage.',
                'The eight previous workflows are reused and sixteen new workflows are added; these are not 96 independently invented tasks.',
                'Scripted permission and source-review inputs are simulations; zero human consent records were collected.',
                'Direct Python execution does not measure UI discoverability, accessibility, task time, emotions, satisfaction or comprehension.',
                'A JSON round trip does not establish actual browser restart, concurrent-session safety or human memory effects.',
                'No external inference, merchant fetch, physical hardware test, payment, recruiting or participant study occurred.',
                'Expected guards and the same final validator are not independent compatibility truth or general robustness evidence.',
                'Frozen-date scenario freshness is distinct from current runtime freshness; existing external evidence gates remain pending.',
            ]}


def markdown(report):
    lines = ['# Expanded fictional persona cohort', '', '**Fictional simulation. Zero human participants.**', '',
             'The stories, pressures and reactions are authored design hypotheses. Only the recorded local software states and checks were executed and measured.', '',
             f"Snapshot: {report['snapshot_date']}. **{report['fictional_personas']} fictional personas · {len(report['conditions'])} conditions · {report['correlated_journeys']} correlated journeys · {report['steps']} steps · {report['passed_checks']}/{report['checks']} specified checks.**", '',
             'The denominator includes repeated guard checks at each step. It is software coverage, not people, independent tasks or a usability success rate. Eight earlier workflows are retained; sixteen new workflows add distinct combinations of constraints.', '',
             '| Condition | What changes after the primary workflow |', '|---|---|',
             '| Ordinary | The persona completes the primary script, including intentional deferrals. |',
             '| Late cost ambiguity | A USD 15 hypothetical tax increase and unknown shipping require an explicit ceiling revision or a stop. |',
             '| Conflicting inventory | A second note declares a lower-resolution owned screen; each persona either corrects the fictional note or stops. |',
             '| Stale offer after interruption | A JSON round trip precedes a wrong variant and expired offer; explicit refresh or deferral follows. |', '',
             '## Cast and outcomes', '', '| Fictional persona | Primary conflict | Ordinary final state |', '|---|---|---|']
    for profile in report['profiles']:
        run = next(j for j in report['journeys'] if j['persona_id'] == profile['id'] and j['condition'] == 'ordinary')
        lines.append(f"| {profile['name']} | {profile['primary_goal']} | {run['steps'][-1]['state']['status']} |")
    for profile in report['profiles']:
        lines += ['', f"## {profile['name']} — fictional", '', profile['context'], '',
                  '**Goal.** '+profile['primary_goal'], '', '**Tensions.** '+'; '.join(profile['competing_priorities'])+'.', '',
                  '**Starting assumption.** '+profile['initial_assumption'], '',
                  '**Scripted behavior.** '+profile['behavior_rule'], '',
                  '**Who owns the decision.** '+profile['decision_owner'], '',
                  '**Correction trigger.** '+profile['correction_trigger'], '',
                  '**Recovery.** '+profile['recovery'], '', '**Stopping boundary.** '+profile['stop_condition'], '',
                  '**Not established.** '+'; '.join(profile['not_simulated'])+'.', '',
                  '| Condition | Scripted recovery decision | Final state | Checks |', '|---|---|---|---:|']
        runs = [j for j in report['journeys'] if j['persona_id'] == profile['id']]
        for j in runs:
            total = sum(len(s['checks']) for s in j['steps'])
            passed = sum(sum(s['checks'].values()) for s in j['steps'])
            lines.append(f"| {j['condition']} | {j['scripted_recovery_decision']} | {j['steps'][-1]['state']['status']} | {passed}/{total} |")
        lines += ['', 'Executed ordinary path:', '']
        for s in runs[0]['steps']:
            failures = [k for k, v in s['checks'].items() if not v]
            lines.append(f"{s['sequence']}. {s['authored_intent']} → {s['state']['status']}, {s['state']['supported_baskets']} supported baskets." + (f" FAILED: {', '.join(failures)}" if failures else ''))
    lines += ['', '## Limits and reproduction', ''] + ['- '+value for value in report['limitations']]
    lines += ['', '```sh', f".venv/bin/python scripts/rehearse_persona_cohort.py --as-of {report['snapshot_date']} --output output/persona-cohort.json --markdown output/persona-cohort.md", '```', '',
              'The companion JSON preserves every input, stage, failed check if any, primary versus perturbed outcome and source hash. Existing output files cannot be overwritten by the runner.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', type=date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--markdown', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.markdown.resolve() or any(p.exists() for p in (args.output, args.markdown)):
        parser.error('Supply distinct new files; preserve existing evidence.')
    report = evaluate(args.as_of)
    for path, content in ((args.output, json.dumps(report, indent=2)+'\n'), (args.markdown, markdown(report))):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x') as handle:
            handle.write(content)
    print(json.dumps({k: report[k] for k in ('fictional_personas', 'correlated_journeys', 'steps', 'passed_checks', 'checks', 'all_checks_pass', 'software_endings', 'human_participants')}))
    return 0 if report['all_checks_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
