"""Read-only integrity/coverage audit of retained local validation artifacts."""
import argparse
from collections import Counter
from datetime import date
import gzip
import hashlib
from itertools import permutations, product
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.combination_fixture import AXES, TOTAL_CASES, case_from_id, expected_support, subtotal
from scripts.validate_matrix import source_hashes, projections
from scripts.validate_state_sequences import GATES, SEEDS
from scripts.validate_persona_sequences import words
from scripts.validate_api_matrix import DOMAINS, expected_status


def require(condition, message):
    if not condition:
        raise ValueError(message)


def all_true(checks):
    return bool(checks) and all(type(value) is bool and value for value in checks.values())


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            value.update(chunk)
    return value.hexdigest()


def records(report, directory):
    filename = report['trace']['filename']
    require(Path(filename).name == filename, 'Trace must be an adjacent plain filename.')
    path = (directory/filename).resolve()
    require(path.is_relative_to(directory.resolve()), 'Trace escapes its evidence directory.')
    require(digest(path) == report['trace']['sha256'], 'Trace checksum mismatch.')
    with gzip.open(path, 'rt') as stream:
        for line in stream:
            require(len(line) <= 1024*1024, 'Oversized trace record.')
            yield json.loads(line)


def audit_matrix(report, directory):
    require(report['axes'] == AXES, 'Matrix axes differ from the declared protocol.')
    require(report['sources'] == source_hashes(), 'Matrix sources changed or were omitted.')
    count = supported = 0
    inputs = hashlib.sha256()
    for row in records(report, directory):
        require(row['suite'] == 'matrix' and row['id'] == count, 'Missing, duplicate or reordered matrix ID.')
        case = case_from_id(count)
        require(row['case'] == case, 'Case ID does not decode to its declared input.')
        expected = bool(expected_support(case))
        require(type(row['expected']) is bool and row['expected'] == expected, 'Stored expectation disagrees with finite oracle.')
        require(type(row['observed']) is bool and row['observed'] == expected, 'Observed matrix disagreement retained.')
        require(row['unexpected_error'] is None and row['price_matches_fixture_arithmetic'] is True and row['index_decodes_to_input'] is True,
                'Matrix trace contains an execution/index/price failure.')
        require(row['observed_total_cents'] == (subtotal(case['displays']) if expected else None), 'Supported price differs from independent arithmetic.')
        inputs.update(json.dumps(case, sort_keys=True, separators=(',',':')).encode()+b'\n')
        supported += expected
        count += 1
    require(count == report['cases'] == report['requested_limit'], 'Matrix denominator does not match its trace.')
    require(supported == report['expected_supported'] == report['observed_supported'], 'Support denominator mismatch.')
    require(inputs.hexdigest() == report['input_sha256'], 'Matrix input hash mismatch.')
    complete = count == TOTAL_CASES
    require(report['complete_cartesian_enumeration'] == complete, 'Invalid exhaustive-coverage claim.')
    require(report['all_checks_pass'] and not any(report[k] for k in ('false_acceptances','false_rejections','unexpected_errors','total_price_mismatches','index_decode_mismatches')),
            'Matrix header does not describe a passing run.')
    require(report['projection_coverage']['pair_assignments'] == (projections(2) if complete else None), 'Pair projection count mismatch.')
    require(report['projection_coverage']['triple_assignments'] == (projections(3) if complete else None), 'Triple projection count mismatch.')
    return {'cases': count, 'supported': supported, 'complete': complete,
            'pair_assignments_implied_by_enumeration': projections(2) if complete else None,
            'triple_assignments_implied_by_enumeration': projections(3) if complete else None}


def audit_state_sequences(report, directory):
    require(report['sources'] == source_hashes(['scripts/validate_state_sequences.py']), 'State sequence sources changed or omitted.')
    order_ids, review_ids = set(), set()
    boundaries = set()
    faults = controls = detected = alarms = 0
    for row in records(report, directory):
        require(row['all_checks_pass'] is True, 'State sequence trace retains a failed record.')
        suite = row['suite']
        if suite in ('event_orders','source_review_orders'):
            require(all(all_true(step['checks']) for step in row['steps']), 'Failed or non-boolean state-machine step.')
        if suite == 'event_orders':
            key = (row['seed'], tuple(row['block_order']), tuple(row['restore_order']))
            require(key not in order_ids, 'Duplicate event-order sequence.')
            order_ids.add(key)
            require(len(row['steps']) == 9, 'An event-order path omitted a declared edit.')
        elif suite == 'source_review_orders':
            key = (row['requested_displays'], tuple(row['events']))
            require(key not in review_ids, 'Duplicate source-review sequence.')
            review_ids.add(key)
            require(len(row['steps']) == 5, 'A source-review path omitted an event.')
        elif suite == 'freshness_os_cost_boundaries':
            key = tuple(row[k] for k in ('evidence_age_days','offer_age_days','os_version','tax_cents','shipping_cents'))
            require(key not in boundaries, 'Duplicate freshness boundary.')
            boundaries.add(key)
            expected = 0 <= key[0] <= 90 and 0 <= key[1] <= 7 and key[2] != '11.9' and key[3] is not None and key[4] is not None
            require(row['expected'] == row['observed'] == expected, 'Boundary predicate disagreement.')
        elif suite == 'mutation_challenge':
            if row['is_noop_control']:
                controls += 1
                alarms += row['detected']
                require(not row['detected'] and row['mutant'] == row['baseline'], 'No-op false alarm.')
            else:
                faults += 1
                detected += row['detected']
                require(row['detected'] and row['baseline'] == row['expected'] and row['mutant'] != row['expected'], 'Undetected deliberate fault.')
        else:
            raise ValueError('Unknown state-trace suite.')
    if report['complete_event_orders']:
        expected_ids = {(seed, left, right) for seed in range(len(SEEDS)) for left, right in product(permutations(GATES), repeat=2)}
        require(order_ids == expected_ids, 'Missing an event-order permutation.')
    if report['complete_review_orders']:
        expected_ids = {(displays, order) for displays in (2,3) for order in permutations(('propose_low','propose_high','accept_low','accept_high','inspect'))}
        require(review_ids == expected_ids, 'Missing a source-review permutation.')
    expected_boundaries = set(product((-1,0,90,91),(-1,0,7,8),('11.9','12.0','12.0.0','13.0'),(None,0,1),(None,0,1)))
    require(boundaries == expected_boundaries, 'Missing a freshness/OS/cost boundary combination.')
    require(len(order_ids) == report['event_order_sequences'] and len(review_ids) == report['source_review_sequences'], 'Sequence counts disagree with trace.')
    require(report['mutation_operations'] == 9*len(order_ids), 'Mutation-operation count mismatch.')
    require(len(boundaries) == report['boundary_cases'], 'Boundary count mismatch.')
    require(faults == detected == report['seeded_faults'] == report['detected_faults'] == 11, 'Mutation challenge denominator mismatch.')
    require(controls == report['noop_controls'] == 1 and alarms == report['noop_false_alarms'] == 0, 'No-op control mismatch.')
    require(report['all_checks_pass'] and report['failed_records'] == 0, 'State header retains a failure.')
    return {'event_order_sequences': len(order_ids), 'source_review_sequences': len(review_ids),
            'boundary_cases': len(boundaries), 'faults_detected': detected, 'faults_seeded': faults, 'noop_false_alarms': alarms}


def audit_persona_sequences(report, directory):
    extras = ['scripts/validate_persona_sequences.py','scripts/rehearse_persona_cohort.py',
              'scripts/rehearse_complex_personas.py','scripts/rehearse_workstation.py',
              'docs/protocols/persona-cohort.json','docs/protocols/complex-workstation-personas.json']
    require(report['sources'] == source_hashes(extras), 'Persona sequence sources changed or omitted.')
    from scripts.rehearse_persona_cohort import load_protocol
    _, profiles = load_protocol()
    persona_ids = [p['id'] for p in profiles]
    require(report['persona_ids'] == persona_ids, 'Persona identities do not match the authored protocol.')
    language = list(words(report['maximum_word_length']))
    count = steps = checks = passed = 0
    endings = Counter()
    for row in records(report, directory):
        require(row['suite'] == 'persona_disruption_words' and row['id'] == count, 'Missing or duplicate persona sequence ID.')
        profile_index, word_index = divmod(count, len(language))
        require(profile_index < len(persona_ids) and row['persona_id'] == persona_ids[profile_index] and tuple(row['events']) == language[word_index],
                'Persona/word identity does not match its enumeration index.')
        require(row['all_checks_pass'] and row['unexpected_error'] is None and row['is_fictional'], 'Failed or mislabeled persona word.')
        require(all(all_true(s['checks']) for s in row['steps']), 'Persona trace contains failed or non-boolean checks.')
        require(len(row['scripted_decisions']) == len(row['events']), 'Persona word omitted an event.')
        endings[row['steps'][-1]['state']['status']] += 1
        steps += len(row['steps'])
        checks += sum(len(s['checks']) for s in row['steps'])
        passed += sum(sum(s['checks'].values()) for s in row['steps'])
        count += 1
    require(count == report['sequences'] == len(persona_ids)*len(language), 'Missing persona sequence words.')
    require(steps == report['steps'] and checks == passed == report['checks'] == report['passed_checks'], 'Persona step/check denominator mismatch.')
    require(dict(endings) == report['final_states'], 'Persona ending counts mismatch.')
    require(report['all_checks_pass'] and report['failed_sequences'] == 0, 'Persona header retains a failed word.')
    return {'fictional_personas': len(persona_ids), 'words_per_persona': len(language),
            'sequences': count, 'steps': steps, 'checks': checks, 'endings': dict(endings)}


def audit_api(report):
    extras = ['scripts/validate_api_matrix.py','intentcart/app.py','intentcart/agent_routes.py',
              'intentcart/workbench_routes.py','intentcart/config.py']
    require(report['sources'] == source_hashes(extras) and report['domains'] == DOMAINS, 'API guard protocol/sources changed.')
    seen = set()
    duplicates = 0
    statuses = Counter()
    for row in report['records']:
        require(row['all_checks_pass'] is True and all_true(row['checks']), 'Failed or non-boolean API guard record.')
        statuses[str(row['observed_status'])] += 1
        if row['suite'] == 'api_guard_matrix':
            key = tuple(row['case'][axis] for axis in DOMAINS)
            require(key not in seen, 'Duplicate API guard case.')
            seen.add(key)
            expected = expected_status(row['case'])
            require(row['expected_status'] == row['observed_status'] == expected, 'API guard precedence mismatch.')
            require((row['owner_before_sha256'] != row['owner_after_sha256']) == (expected == 200), 'Rejected API case changed owner state.')
        else:
            require(row['suite'] == 'api_duplicate_revision' and row['observed_status'] == 409, 'Invalid duplicate-revision record.')
            duplicates += 1
    require(seen == set(product(*DOMAINS.values())), 'Incomplete API guard Cartesian product.')
    require(report['matrix_cases'] == len(seen) and report['duplicate_revision_cases'] == duplicates == 1, 'API denominator mismatch.')
    require(report['status_counts'] == dict(statuses), 'API status denominator mismatch.')
    require(report['blocked_network_attempts'] == report['blocked_provider_attempts'] == report['failed_records'] == 0 and report['all_checks_pass'], 'API report retains a blocked external attempt or failure.')
    return {'matrix_cases': len(seen), 'duplicate_revision_cases': duplicates, 'statuses': dict(statuses)}


def audit(directory):
    filenames = ('combination-matrix.json','state-sequence-validation.json','persona-sequence-validation.json','api-guard-matrix.json')
    reports = [json.loads((directory/name).read_text()) for name in filenames]
    require(len({r['snapshot_date'] for r in reports}) == 1, 'Reports use different snapshot dates.')
    for report in reports:
        require(report['human_participants'] == report['provider_requests'] == report['payment_operations'] == 0,
                'Synthetic/local artifacts must not imply people or external operations.')
    results = {'matrix': audit_matrix(reports[0], directory),
               'state_sequences': audit_state_sequences(reports[1], directory),
               'persona_sequences': audit_persona_sequences(reports[2], directory),
               'api_guards': audit_api(reports[3])}
    require(reports[0]['complete_cartesian_enumeration'] and reports[1]['complete_event_orders'] and reports[1]['complete_review_orders']
            and reports[2]['complete_declared_language'], 'Aggregate audit requires all declared suites, not smoke subsets.')
    return {'schema': 'intentcart-combinatorial-audit/1', 'snapshot_date': reports[0]['snapshot_date'],
            'all_checks_pass': True, 'results': results,
            'reports_sha256': {name: digest(directory/name) for name in filenames},
            'auditor_sha256': digest(Path(__file__)),
            'human_participants': 0, 'provider_requests': 0, 'payment_operations': 0,
            'limits': ['This audit verifies artifact integrity, denominators and declared finite coverage; it is not outside reproduction or universal correctness.',
                       'Source hashes are local content identities, not signatures or proof of an independent human reviewer.',
                       'Fictional persona checks are authored and correlated. The 17-axis hardware oracle is synthetic, not real product truth.']}


def markdown(report):
    r = report['results']
    lines = ['# Combinatorial validation', '', '**Local, offline validation. Fictional/synthetic scenarios; zero human participants.**', '',
             f"Snapshot: {report['snapshot_date']}. Saved trace integrity, source identities, case uniqueness and the declared coverage denominators were audited.", '',
             '| Suite | Executed coverage | Result |', '|---|---|---|',
             f"| Synthetic hardware matrix | {r['matrix']['cases']:,} distinct configurations across 17 listed axes; {r['matrix']['supported']:,} supported | Zero false acceptances/rejections against the separately stated finite oracle |",
             f"| Block and recovery order | {r['state_sequences']['event_order_sequences']:,} sequences: 4! blocking orders × 4! recovery orders × three seeds | Input immutability, revision, acceptance invalidation and restored semantics pass |",
             f"| Source review order | {r['state_sequences']['source_review_sequences']:,} sequences: 5! events × two display requests | Obsolete/missing acceptance and repeated inspection handled as declared |",
             f"| Freshness, OS and cost boundaries | {r['state_sequences']['boundary_cases']:,} configurations | Exact-boundary, future-date and unknown-cost cases pass |",
             f"| Fictional persona chains | {r['persona_sequences']['sequences']:,} journeys; {r['persona_sequences']['fictional_personas']} profiles × {r['persona_sequences']['words_per_persona']} ordered words | Every declared disruption chain through length three, including repetitions |",
             f"| Actual local API guards | {r['api_guards']['matrix_cases']} combinations + one duplicate-revision request | Expected status and durable-owner-state checks pass |",
             f"| Deliberate fault challenge | {r['state_sequences']['faults_detected']}/{r['state_sequences']['faults_seeded']} seeded faults detected; one no-op control | Zero no-op false alarms |", '',
             'These are separate denominators. Repeated per-step assertions are not additional independent configurations, users or benchmark tasks.', '',
             '## What the matrix covers', '',
             'Six capability-versus-requirement pairs (display count, resolution, refresh, charging, HDCP and gaming), dock protocol, driver permission, reviewed availability, known versus unknown cost, and a budget one cent below/at/above the independently calculated subtotal.', '',
             'The fixtures have one synthetic product per component kind and one explicitly declared owned screen. Capabilities are fictional declarations. The reference predicate reads the declared world and request directly and never calls the planner or reuses its check results.', '',
             f"The full Cartesian enumeration implies all {r['matrix']['pair_assignments_implied_by_enumeration']:,} declared two-axis assignments and {r['matrix']['triple_assignments_implied_by_enumeration']:,} three-axis assignments. The audit decodes each numbered trace input and rejects missing/duplicate/reordered IDs; these are projections of the same matrix, not extra executions.", '',
             '## Ordered persona disruptions', '',
             'For each of the existing 24 fictional profiles, execute every word of length zero, one, two or three over: late cost ambiguity, conflicting inventory, and an expired offer after a serialized interruption. This is 1 + 3 + 9 + 27 = 40 words per profile. The primary workflow is executed afresh for each word. Repeated disturbances can accumulate unresolved constraints; a later event may reopen a previously stopped fictional scenario.', '',
             f"The persona chains contain {r['persona_sequences']['steps']:,} executed steps and {r['persona_sequences']['checks']:,} repeated contract checks. Those checks are not a measure of human realism or independent trial count.", '',
             '## Faults challenged', '',
             'Test-only patches bypass driver permission, display count, the resolution path, refresh, charging target, HDCP, gaming, offer availability and unknown all-in cost. Two further patches incorrectly reject exact-budget equality or always defer. The no-op control preserves behavior. Detecting these eleven constructed faults does not establish detection of arbitrary defects.', '',
             '## Retained evidence and reproduction', '',
             'Each suite saves its complete trace, including failures if any, rather than only a success count. Gzip files are streamed, CRC-checked on read and bound by SHA-256. Reports carry source manifests. Existing outputs cannot be overwritten by the runners.', '',
             '```sh',
             '.venv/bin/python scripts/validate_matrix.py --as-of 2026-10-19 --output output/recheck/combination-matrix.json --trace output/recheck/combination-matrix-cases.jsonl.gz',
             '.venv/bin/python scripts/validate_state_sequences.py --as-of 2026-10-19 --output output/recheck/state-sequence-validation.json --trace output/recheck/state-sequence-cases.jsonl.gz',
             '.venv/bin/python scripts/validate_persona_sequences.py --as-of 2026-10-19 --output output/recheck/persona-sequence-validation.json --trace output/recheck/persona-sequence-cases.jsonl.gz',
             '.venv/bin/python scripts/validate_api_matrix.py --as-of 2026-10-19 --output output/recheck/api-guard-matrix.json',
             '.venv/bin/python scripts/audit_combinations.py --directory output/recheck --output output/recheck/audit.json --markdown output/recheck/REPORT.md',
             '```', '',
             '## Limits', '',
             'The finite matrix is exhaustive only for its listed values. Raw constructed states test the validator; the separate in-process API suite tests the listed guards. Neither establishes arbitrary browser flows, real concurrency, load capacity, production authentication, physical compatibility or live payment reliability. Rate buckets are cleared between API guard cases, so that suite does not measure rate limiting.', '',
             'A frozen snapshot date tests declared source-age boundaries. It is not a claim that current merchant or hardware data was refreshed. JSON round trips are not actual browser restarts. The persona stories and reactions are authored hypotheses, with no measured psychological validity, task times, human satisfaction or usability benefit. Live-model and consented-participant gates remain pending.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT/'submission')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--markdown', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.markdown.resolve() or any(p.exists() for p in (args.output,args.markdown)):
        parser.error('Supply distinct new files; preserve previous audit evidence.')
    try:
        report = audit(args.directory)
    except (ValueError, KeyError, OSError) as exc:
        report = {'schema': 'intentcart-combinatorial-audit/1', 'all_checks_pass': False,
                  'failure': f'{type(exc).__name__}: {exc}', 'auditor_sha256': digest(Path(__file__))}
    for path, content in ((args.output,json.dumps(report,indent=2)+'\n'),
                          (args.markdown,markdown(report) if report['all_checks_pass'] else '# Validation audit failed\n\n'+report['failure']+'\n')):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x') as out:
            out.write(content)
    print(json.dumps(report.get('results', {'all_checks_pass':False,'failure':report.get('failure')})))
    return 0 if report['all_checks_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
