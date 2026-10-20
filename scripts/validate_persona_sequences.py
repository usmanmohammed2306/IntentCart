"""Every authored disruption word of length zero through three for 24 personas."""
import argparse
from copy import deepcopy
from datetime import date
import gzip
import hashlib
from itertools import product
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart import agent, workbench
from scripts.rehearse_complex_personas import Journey
from scripts.rehearse_workstation import finish
from scripts.rehearse_persona_cohort import load_protocol, execute, stress
from scripts.validate_matrix import source_hashes

EVENTS = ('late-cost-ambiguity', 'conflicting-inventory', 'stale-offer-after-interruption')
MAX_LENGTH = 3


def words(max_length=MAX_LENGTH):
    if type(max_length) is not int or not 0 <= max_length <= MAX_LENGTH:
        raise ValueError('The declared disruption language has length zero through three.')
    for length in range(max_length+1):
        yield from product(EVENTS, repeat=length)


class BoundedJourney(Journey):
    def drive(self, intent, expected, driver=None):
        answer = self.driver if driver is None else driver
        self.state = finish(self.state, answer)
        bounded_stop = self.state['status'] == 'STEP_STOP'
        checks = {'support_matches_declared_recovery': bool(workbench.rank(self.state)) == expected,
                  'recommendation_matches_support_and_step_authority': (self.state['recommended_id'] is not None) == (expected and not bounded_stop),
                  'terminal_state': self.state['status'] != 'ACTIVE'}
        if bounded_stop:
            checks['step_stop_occurs_at_declared_bound'] = self.state['tool_count'] == agent.MAX_STEPS
            checks['step_stop_has_no_recommendation'] = self.state['recommended_id'] is None
        self.observe(intent, checks, {'policy': 'local_targeted', 'scripted_driver_answer': answer},
                     note='A supported configuration still cannot bypass the declared tool-step bound.' if bounded_stop else None)


def run_word(profile, events, as_of):
    journey = BoundedJourney(profile, {'id': 'baseline', 'unexpected_cost_cents': 0, 'resume_from_snapshot': False}, as_of)
    decisions = []
    primary_steps = None
    unexpected = None
    try:
        if profile.get('prior_workflow'):
            journey.run()
        else:
            for instruction in profile['script']:
                execute(journey, instruction)
        primary_steps = len(journey.steps)
        for event in events:
            first = len(journey.steps)
            decision = stress(journey, event)
            decisions.append({'event': event, 'first_step': first+1, 'last_step': len(journey.steps), 'scripted_decision': decision})
    except (ValueError, KeyError, IndexError, RuntimeError) as exc:
        unexpected = f'{type(exc).__name__}: {exc}'
        journey.observe('Unexpected sequence failure retained', {'sequence_completed': False}, note=unexpected)
    return {'suite': 'persona_disruption_words', 'persona_id': profile['id'], 'is_fictional': True,
            'events': list(events), 'primary_steps': primary_steps, 'scripted_decisions': decisions,
            'unexpected_error': unexpected, 'steps': journey.steps,
            'all_checks_pass': all(all(s['checks'].values()) for s in journey.steps)}


def evaluate(as_of, max_length=MAX_LENGTH, emit=None, progress=None):
    protocol, profiles = load_protocol()
    sequences = list(words(max_length))
    emit = emit or (lambda row: None)
    count = failed = steps = checks = passed = 0
    final_states = {}
    first_failures = []
    with patch.object(workbench, 'current_day', return_value=as_of):
        for profile in profiles:
            for events in sequences:
                result = run_word(profile, events, as_of)
                result['id'] = count
                emit(result)
                count += 1
                failed += not result['all_checks_pass']
                steps += len(result['steps'])
                checks += sum(len(s['checks']) for s in result['steps'])
                passed += sum(sum(s['checks'].values()) for s in result['steps'])
                final = result['steps'][-1]['state']['status']
                final_states[final] = final_states.get(final, 0)+1
                if not result['all_checks_pass'] and len(first_failures) < 10:
                    first_failures.append({'id': result['id'], 'persona_id': result['persona_id'], 'events': result['events'],
                        'failed_steps': [s for s in result['steps'] if not all(s['checks'].values())]})
                if progress and count % 120 == 0:
                    progress({'persona_sequences_completed': count, 'target': len(profiles)*len(sequences)})
    paths = ['scripts/validate_persona_sequences.py', 'scripts/rehearse_persona_cohort.py',
             'scripts/rehearse_complex_personas.py', 'scripts/rehearse_workstation.py',
             'docs/protocols/persona-cohort.json', protocol['prior_profiles']]
    return {'schema': 'intentcart-persona-disruption-sequences/1', 'snapshot_date': as_of.isoformat(),
            'evidence_class': 'fictional_persona_sequence_validation', 'events': list(EVENTS),
            'maximum_word_length': max_length, 'fictional_personas': len(profiles),
            'persona_ids': [p['id'] for p in profiles], 'words_per_persona': len(sequences),
            'declared_full_words_per_persona': sum(len(EVENTS)**k for k in range(MAX_LENGTH+1)),
            'complete_declared_language': max_length == MAX_LENGTH,
            'sequences': count, 'steps': steps, 'checks': checks, 'passed_checks': passed,
            'failed_sequences': failed, 'first_failures': first_failures, 'final_states': final_states,
            'all_checks_pass': failed == 0, 'human_participants': 0, 'provider_requests': 0, 'payment_operations': 0,
            'sources': source_hashes(paths),
            'limits': ['Authored deterministic personas, not observed or psychologically validated people.',
                       'Fresh primary workflow execution for each word; no primary-prefix copy counted as another execution.',
                       'Repeats and order are covered only up to length three over these three specific disruptions.',
                       'Recovery checks compare with the prior supported state; these are metamorphic checks, not an independent hardware oracle.',
                       'A stop means no recommendation under the current script state; a later event can reopen that fictional scenario.',
                       'JSON round trips are not browser restarts; no human UX, account, model or payment behavior is measured.',
                       'All failed sequence details remain in the compressed trace; the summary includes ten witnesses.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', type=date.fromisoformat, required=True)
    parser.add_argument('--max-length', type=int, default=MAX_LENGTH)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--trace', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.trace.resolve() or any(p.exists() for p in (args.output,args.trace)):
        parser.error('Use distinct new paths; previous reports cannot be overwritten.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.trace.parent.mkdir(parents=True, exist_ok=True)
    with args.trace.open('xb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as stream:
        def emit(row):
            stream.write((json.dumps(row, sort_keys=True, separators=(',',':'))+'\n').encode())
        report = evaluate(args.as_of, args.max_length, emit, lambda row: print(json.dumps(row), flush=True))
    report['trace'] = {'filename': args.trace.name, 'sha256': hashlib.sha256(args.trace.read_bytes()).hexdigest()}
    with args.output.open('x') as out:
        out.write(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key: report[key] for key in ('fictional_personas','sequences','steps','passed_checks','checks','failed_sequences','final_states','all_checks_pass')}))
    return 0 if report['all_checks_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
