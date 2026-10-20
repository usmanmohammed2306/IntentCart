"""Generate the local reliability report, export a trace, or replay one safely.

All runs use disposable app storage, separate persisted fake-provider truth,
blank credentials, blocked network transports and a zero sponsor ceiling.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart.replay import ReplayError, evaluate_suite, load_trace, run_trace, MAX_TRACE_BYTES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'intentcart/data/reliability-evaluation.json')
    parser.add_argument('--replay', type=Path, help='Replay one exported strict source-bound JSON trace.')
    parser.add_argument('--export-trace', help='Export a saved case ID, mutant-ID or minimal-mutant-ID from --report.')
    parser.add_argument('--report', type=Path, default=ROOT / 'intentcart/data/reliability-evaluation.json')
    parser.add_argument('--trace-output', type=Path, help='Required destination for --export-trace.')
    args = parser.parse_args()
    if args.replay and args.export_trace:
        parser.error('Choose replay or export, not both.')
    try:
        if args.replay:
            if args.replay.stat().st_size > MAX_TRACE_BYTES:
                raise ReplayError('Trace exceeds the 64 KiB limit.')
            trace = load_trace(json.loads(args.replay.read_text()))
            result = run_trace(trace)
            print(json.dumps(result, indent=2))
            return 0
        if args.export_trace:
            if not args.trace_output:
                parser.error('--export-trace requires --trace-output.')
            report = json.loads(args.report.read_text())
            choices = {case['id']: case['trace'] for case in report['cases']}
            choices.update({'mutant-' + case['id']: case['trace'] for case in report['mutations']})
            choices.update({'minimal-mutant-' + case['id']: case['shrunk_trace'] for case in report['mutations']})
            if args.export_trace not in choices:
                raise ReplayError('Unknown trace ID. Available: ' + ', '.join(choices))
            trace = load_trace(choices[args.export_trace])
            args.trace_output.parent.mkdir(parents=True, exist_ok=True)
            args.trace_output.write_text(json.dumps(trace.model_dump(), indent=2) + '\n')
            print(f'Exported {trace.id} to {args.trace_output}; replay with --replay PATH.')
            return 0
        result = evaluate_suite()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'saved': str(args.output), 'denominators': result['denominators'],
                          'checks': result['checks'], 'live_provider_calls': 0}, indent=2))
        return 0 if all(result['checks'].values()) else 1
    except (ReplayError, OSError, ValueError, KeyError, TypeError) as exc:
        print('Reliability replay rejected: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
