"""Stateful, explicitly fictional persona scenarios over the real local planner."""
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
from scripts.rehearse_workstation import finish, snapshot

PROTOCOL = ROOT / 'docs/protocols/complex-workstation-personas.json'
DOCK = 'plugable-ud6950pdh'
SOURCE = DOCK + '-displays'


class Journey:
    def __init__(self, persona, variant, as_of):
        self.persona, self.variant, self.as_of = persona, variant, as_of
        self.steps = []
        self.driver = persona['id'] != 'noah'
        self.state = finish(agent.create('Fictional complex workstation scenario',
                            {'budget_cents': 40000}, 'curated', 32, True), self.driver)
        self.observe('Initial scripted planning request', {'initial_terminal_state': self.state['status'] != 'ACTIVE'})
        self.change('Record the scenario cost allowance', 'requirements',
                    {'tax_cents': variant['unexpected_cost_cents']})
        self.drive('Request a fresh recommendation after the allowance change', expected=self.driver)
        if variant['resume_from_snapshot']:
            before = deepcopy(self.state)
            self.state = json.loads(json.dumps(self.state))
            self.observe('Resume a JSON state snapshot after a scripted interruption',
                         {'state_roundtrip_exact': self.state == before,
                          'rank_roundtrip_exact': workbench.rank(self.state) == workbench.rank(before)},
                         note='Serialization round trip only; no actual browser restart or observed human memory.')

    def observe(self, intent, checks, payload=None, note=None):
        self.steps.append({'sequence': len(self.steps) + 1, 'authored_intent': intent,
                           'input_provenance': 'fictional deterministic script',
                           'scripted_input': payload, 'state': snapshot(self.state),
                           'checks': {k: bool(v) for k, v in checks.items()}, 'note': note})

    def change(self, intent, operation, payload, supported=None):
        before = deepcopy(self.state)
        changed = workbench.mutate(self.state, operation, payload)
        unchanged = self.state == before
        self.state = changed
        checks = {'prior_record_unchanged': unchanged,
                  'revision_increased': changed['revision'] > before['revision'],
                  'recommendation_cleared': changed['recommended_id'] is None}
        if supported is not None:
            checks['support_matches_expected'] = bool(workbench.rank(changed)) == supported
        self.observe(intent, checks, {'operation': operation, 'payload': payload})

    def reject(self, intent, operation, payload):
        before = deepcopy(self.state)
        error = None
        try:
            workbench.mutate(self.state, operation, payload)
        except ValueError as exc:
            error = str(exc)
        self.observe(intent, {'invalid_input_rejected': error is not None,
                              'rejection_preserves_record': self.state == before},
                     {'operation': operation, 'payload': payload}, note=error)

    def drive(self, intent, expected, driver=None):
        self.state = finish(self.state, self.driver if driver is None else driver)
        self.observe(intent, {'support_matches_expected': bool(workbench.rank(self.state)) == expected,
                              'recommendation_matches_expected': (self.state['recommended_id'] is not None) == expected,
                              'terminal_state': self.state['status'] != 'ACTIVE'},
                     {'policy': 'local_targeted', 'scripted_driver_answer': self.driver if driver is None else driver})

    def offer(self, **changes):
        product = next(p for p in workbench.catalog(self.state)['products'] if p['id'] == DOCK)
        return {'product_id': DOCK, 'variant': product['variant'],
                'merchant': 'Fictional scenario merchant', 'offer_id': 'FICTIONAL-OFFER-1',
                'price_cents': 19999, 'observed_on': self.as_of.isoformat(),
                'available': True, **changes}

    def source(self, value):
        replacement = deepcopy(workbench.catalog(self.state)['sources'][SOURCE])
        replacement['value'] = value
        self.change('Propose a hypothetical display-count correction', 'propose_source',
                    {'source_id': SOURCE, 'replacement': replacement,
                     'reason': 'Fictional disputed specification; not independently verified'})

    def run(self):
        who = self.persona['id']
        if who == 'mira':
            cost = self.variant['unexpected_cost_cents']
            self.change('Remember the reimbursement ceiling after seeing a plan', 'revise_goal',
                        {'budget_cents': 35000}, supported=cost == 0)
            self.change('Notice tax has not actually been settled', 'requirements', {'tax_cents': None}, supported=False)
            self.change('Enter an explicitly hypothetical reviewed tax allowance', 'requirements', {'tax_cents': cost}, supported=cost == 0)
            if cost <= 500:
                self.change('Explicitly confirm the ceiling with at most USD 5 discretionary allowance', 'revise_goal',
                            {'budget_cents': 35000 + cost}, supported=True)
            self.drive('Resolve the current budget without claiming a merchant quote', expected=cost <= 500)
        elif who == 'noah':
            self.change('Try a larger hardware allowance without granting installation permission', 'revise_goal',
                        {'budget_cents': 80000, 'allow_driver': False}, supported=False)
            self.drive('Decline again when the same installation issue returns', expected=False, driver=False)
            self.observe('Stop because a hardware allowance cannot override the restriction',
                         {'driver_still_denied': not self.state['goal']['allow_driver']})
        elif who == 'leena':
            self.reject('Copy a similar-looking but wrong variant from another tab', 'offer', self.offer(variant='wrong-model-suffix'))
            self.change('Correct the identity but use an eight-day-old discount', 'offer',
                        self.offer(price_cents=18999, observed_on=(self.as_of-timedelta(days=8)).isoformat()), supported=False)
            self.change('Refresh the explicit declaration, without a retailer lookup', 'offer', self.offer(price_cents=18999), supported=True)
            self.change('Discover shipping is still unknown', 'requirements', {'shipping_cents': None}, supported=False)
            self.change('Resolve shipping using a scenario allowance', 'requirements', {'shipping_cents': 500}, supported=True)
            self.drive('Request a fresh plan after identity, date and all-in cost review', expected=True)
        elif who == 'jules':
            self.change('Remember evening gaming and protected-video needs', 'requirements', {'gaming': True, 'hdcp': True}, supported=False)
            self.change('Drop gaming but keep protected-video support as a hard requirement', 'requirements', {'gaming': False}, supported=False)
            self.drive('Check that resolving one requirement does not resolve the other', expected=False)
            self.change('Explicitly narrow the scenario to productivity only', 'requirements', {'hdcp': False}, supported=True)
            self.drive('Request a work-only recommendation', expected=True)
        elif who == 'sam':
            original = self.state
            before = deepcopy(self.state)
            self.state = agent.revise(self.state, exclude=DOCK)
            self.observe('Remove the selected dock while preserving the other component plan',
                         {'prior_record_unchanged': original == before,
                          'missing_dock_blocks_support': not workbench.rank(self.state),
                          'recommendation_cleared': self.state['recommended_id'] is None})
            self.change('Record the reviewed offer as unavailable', 'offer', self.offer(available=False), supported=False)
            self.change('Restore the catalog listing while its offer is still unavailable', 'restore_product', {'product_id': DOCK}, supported=False)
            self.change('Explicitly revise the scenario offer availability', 'offer', self.offer(), supported=True)
            self.drive('Request a fresh supported repair plan', expected=True)
            self.observe('Check that recovery did not replace unaffected component slots',
                         {'no_component_slot_changes': not workbench.changed_slots(self.state, workbench.rank(self.state)[0])})
        elif who == 'ari':
            self.source(1)
            self.observe('Keep proposed evidence separate from accepted evidence',
                         {'old_value_retained_until_acceptance': workbench.catalog(self.state)['sources'][SOURCE]['value'] == 2})
            self.reject('Return to an obsolete review identifier after switching tabs', 'accept_source',
                        {'proposal_id': 'fictional-obsolete-review', 'reviewed': True})
            self.change('Accept the exact pending correction', 'accept_source',
                        {'proposal_id': self.state['workbench']['pending_source']['id'], 'reviewed': True}, supported=False)
            self.observe('Require the accepted changed field to be inspected again', {'inspection_invalidated': SOURCE not in self.state['inspected']})
            self.drive('Inspect the reduced display count and defer', expected=False)
            self.source(2)
            self.change('Accept a separately proposed reversal of the mistaken correction', 'accept_source',
                        {'proposal_id': self.state['workbench']['pending_source']['id'], 'reviewed': True}, supported=False)
            self.drive('Reinspect again before recommending the restored specification', expected=True)
        elif who == 'tess':
            inspected = list(self.state['inspected'])
            self.change('Withdraw permission for the shared-machine scenario', 'withdraw_driver', {}, supported=False)
            self.drive('Answer no when the controller revisits permission', expected=False, driver=False)
            self.change('Explore a separately explicit permissive planning revision', 'revise_goal', {'allow_driver': True}, supported=True)
            self.drive('Request a plan under that temporary permissive assumption', expected=True)
            self.change('Return to the shared machine and withdraw permission again', 'withdraw_driver', {}, supported=False)
            self.drive('Finish with the final explicit refusal', expected=False, driver=False)
            self.observe('Retain observations while honoring the latest permission',
                         {'previous_inspections_retained': set(inspected) <= set(self.state['inspected']),
                          'final_permission_denied': not self.state['goal']['allow_driver']})
        elif who == 'dev':
            monitor = {'name': 'Fictional shared monitor', 'height': 1080, 'hz': 60, 'connector': 'hdmi'}
            self.reject('Accidentally enter three owned monitors for a two-display goal', 'requirements', {'owned_monitors': [monitor] * 3})
            self.change('Correct the count but copy a lower resolution from an old note', 'requirements', {'owned_monitors': [{**monitor, 'height': 720}]}, supported=False)
            self.change('Correct the declared monitor resolution', 'requirements', {'owned_monitors': [monitor]}, supported=True)
            self.change('Add a new high-power charging requirement', 'requirements', {'charging_watts': 140}, supported=False)
            self.change('Explicitly remove the unsupported charging target', 'requirements', {'charging_watts': 0}, supported=True)
            before = deepcopy(self.state)
            preview = workbench.counterfactual(self.state, [{'budget_cents': 10000}])
            self.observe('Explore a small budget without replacing the active scenario',
                         {'preview_cannot_support_low_budget': preview['scenarios'][0]['supported'] == 0,
                          'active_record_unchanged': self.state == before,
                          'preview_has_no_checkout': preview['checkout_supported'] is False})
            self.drive('Return to the corrected active inventory', expected=True)
        else:
            raise ValueError('Unknown fictional persona')
        return {'persona_id': who, 'variant': self.variant['id'], 'is_fictional': True,
                'steps': self.steps, 'all_checks_pass': all(all(s['checks'].values()) for s in self.steps)}


def evaluate(as_of):
    if type(as_of) is not date:
        raise ValueError('Supply an explicit snapshot date.')
    protocol = json.loads(PROTOCOL.read_text())
    with patch.object(workbench, 'current_day', return_value=as_of):
        journeys = [Journey(p, v, as_of).run() for p in protocol['personas'] for v in protocol['variants']]
    files = ['scripts/rehearse_complex_personas.py', 'scripts/rehearse_workstation.py',
             str(PROTOCOL.relative_to(ROOT)), 'intentcart/agent.py', 'intentcart/workbench.py',
             'intentcart/missions.py', 'intentcart/evidence_catalog.py', 'intentcart/workspace_preferences.py',
             'intentcart/data/evidence-catalog.json', 'intentcart/data/missions-catalog.json']
    return {'schema': 'intentcart-complex-persona-rehearsal/1',
            'evidence_class': 'synthetic_scripted_scenarios', 'notice': protocol['notice'],
            'snapshot_date': as_of.isoformat(), 'clock': 'explicit frozen scenario date',
            'human_participants': 0, 'consent_records': 0, 'provider_requests': 0, 'payment_operations': 0,
            'fictional_personas': len(protocol['personas']), 'authored_variants': protocol['variants'],
            'correlated_journeys': len(journeys), 'steps': sum(len(j['steps']) for j in journeys),
            'checks': sum(len(s['checks']) for j in journeys for s in j['steps']),
            'passed_checks': sum(sum(s['checks'].values()) for j in journeys for s in j['steps']),
            'all_checks_pass': all(j['all_checks_pass'] for j in journeys),
            'profiles': protocol['personas'], 'journeys': journeys,
            'sources': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files},
            'limitations': [
                'Realistic detail is authored fiction; behavioral realism has not been validated with people.',
                'Names, motivations, mental models and decision thresholds are design hypotheses, not observed traits.',
                'All variants share one catalog and validator; journeys, steps and checks are correlated, not participant counts.',
                'Execution is deterministic local policy plus scripted choices, not an autonomous language-model user simulator.',
                'Only the software states and guard outcomes were measured; no emotions, task times, satisfaction or comprehension scores were measured.',
                'The interruption is a JSON state round trip, not a browser crash/restart or real observed distraction.',
                'Direct Python calls do not test UI discoverability, accessibility, session security or sandbox transactions.',
                'No actual study occurred. Roadmap 88 remains pending; all external gates remain unchanged.',
            ]}


def markdown(report):
    lines = ['# Complex fictional workstation personas', '', '**Authored simulation. Zero human participants.**', '',
             'The identities and circumstances below are invented design hypotheses. The software outcomes come from executing the real local controller and workbench, with scripted decisions and a frozen scenario date.', '',
             f"Snapshot: {report['snapshot_date']}. {report['fictional_personas']} fictional profiles × three authored conditions = {report['correlated_journeys']} correlated journeys; {report['steps']} steps; {report['passed_checks']}/{report['checks']} specified checks passed. These counts are software coverage, not people or a usability success rate.", '',
             'Each profile runs with a declared zero additional-cost allowance, a USD 15 cost surprise, and a USD 5 allowance plus a scripted snapshot/resume interruption. These are hypothetical planning allowances, not live tax estimates. Branching thresholds are authored, not estimated from human behavior.', '']
    for p in report['profiles']:
        lines += [f"## {p['name']} — fictional", '', p['context'], '',
                  '**Goal.** ' + p['primary_goal'], '',
                  '**Competing priorities.** ' + '; '.join(p['competing_priorities']) + '.', '',
                  '**Starting mental model.** ' + p['initial_assumption'], '',
                  '**Scripted decision rule.** ' + p['behavior_rule'], '',
                  '**Correction trigger.** ' + p['correction_trigger'], '',
                  '**Recovery.** ' + p['recovery'], '', '**Stopping boundary.** ' + p['stop_condition'], '',
                  '**Outside this simulation.** ' + '; '.join(p['not_simulated']) + '.', '',
                  '| Condition | Executed steps | Passed checks | Final software state |', '|---|---:|---:|---|']
        runs = [j for j in report['journeys'] if j['persona_id'] == p['id']]
        for j in runs:
            checks = sum(len(s['checks']) for s in j['steps'])
            passed = sum(sum(s['checks'].values()) for s in j['steps'])
            final = j['steps'][-1]['state']
            lines.append(f"| {j['variant']} | {len(j['steps'])} | {passed}/{checks} | {final['status']}; {final['supported_baskets']} supported baskets |")
        lines += ['', 'One executed path (baseline):', '']
        for s in runs[0]['steps']:
            failed = [k for k, v in s['checks'].items() if not v]
            lines.append(f"{s['sequence']}. {s['authored_intent']} → {s['state']['status']}, {s['state']['supported_baskets']} supported baskets" + (f"; FAILED: {', '.join(failed)}" if failed else '') + '.')
        lines += ['']
    lines += ['## Interpretation', '', 'A deferral is an intended outcome when the represented requirements remain unsupported. An ACTIVE state after an edit is distinct from a fresh recommendation. Nothing in these trajectories grants payment authority.', '']
    lines += ['- ' + value for value in report['limitations']]
    lines += ['', '## Reproduce', '', '```sh',
              f".venv/bin/python scripts/rehearse_complex_personas.py --as-of {report['snapshot_date']} --output output/complex-personas.json --markdown output/complex-personas.md",
              '```', '', 'The companion JSON contains all scripted inputs, stage snapshots, failed checks if any, full profiles and source hashes. Existing reports are never overwritten.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', type=date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--markdown', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.markdown.resolve() or any(p.exists() for p in (args.output, args.markdown)):
        parser.error('Supply distinct new output files; preserve previous evidence.')
    report = evaluate(args.as_of)
    for path, content in ((args.output, json.dumps(report, indent=2)+'\n'), (args.markdown, markdown(report))):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x') as handle:
            handle.write(content)
    print(json.dumps({k: report[k] for k in ('fictional_personas', 'correlated_journeys', 'steps', 'passed_checks', 'checks', 'all_checks_pass', 'human_participants')}))
    return 0 if report['all_checks_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
