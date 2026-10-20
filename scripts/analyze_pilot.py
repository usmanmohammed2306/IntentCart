"""Aggregate a private local pilot DB read-only. Never exports free text or IDs.

The operator must distinguish real consented participants from test sessions.
No significance/efficacy inference is performed for this small usability pilot.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart.study import model, POLICIES


def aggregate(records, products):
    result = {'schema': 'intentcart-pilot-aggregate/1', 'assigned_records': len(records),
              'note': 'Local records, not verified unique human participants. Operator must exclude declared tests before a human report. No efficacy inference.',
              'policies': {}}
    for policy in POLICIES:
        assigned = [r for r in records if r['policy'] == policy]
        complete = [r for r in assigned if r['phase'] == 'complete']
        metrics = []
        for record in complete:
            utilities, weights = model(record, products, record['controller_config']['decay'])
            means = weights @ utilities
            pairs = [(a, b, c) for a, b, c in record['after'] if c in ('a', 'b')]
            agreement = float(np.mean([(means[a] > means[b]) == (c == 'a') for a, b, c in pairs])) if pairs else None
            metrics.append({'questions': len(record['history']), 'binary_after_pairs': len(pairs),
                            'after_pair_agreement': agreement, 'burden': record['survey']['burden'],
                            'correct_total': record['survey']['correct_total'],
                            'approval_understood': record['survey']['approval_understood'],
                            'elapsed_seconds': record['completed']-record['started']})
        mean = lambda key: float(np.mean([r[key] for r in metrics if r[key] is not None])) if any(r[key] is not None for r in metrics) else None
        result['policies'][policy] = {'assigned': len(assigned), 'complete': len(complete),
            'incomplete': len(assigned)-len(complete), 'binary_pair_denominator': sum(r['binary_after_pairs'] for r in metrics),
            'participant_record_denominator_for_agreement': sum(r['after_pair_agreement'] is not None for r in metrics),
            'means_at_record_level': {key: mean(key) for key in ('questions', 'after_pair_agreement', 'burden', 'correct_total', 'approval_understood', 'elapsed_seconds')}}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro', uri=True) as db:
        records = [json.loads(row[0]) for row in db.execute('SELECT data FROM studies')]
    products = json.loads((ROOT/'intentcart/data/catalog.json').read_text())
    result = aggregate(records, products)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(f'Aggregated {len(records)} local records without exporting IDs. Not proof of verified human participation.')


if __name__ == '__main__':
    main()
