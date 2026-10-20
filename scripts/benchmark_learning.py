"""Paired CPU timing against the exact 2.1 kernel; no live providers or user DB.

Thread ceilings are set before NumPy import. Repeats are aggregated by workload;
bootstrap units are workloads, not correlated timing repetitions. This measures
local computation and in-process TestClient requests, not network throughput.
"""
import os
for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[key] = '1'
for key in ('PAYPAL_CLIENT_ID', 'PAYPAL_CLIENT_SECRET', 'CHANNEL3_API_KEY',
            'SANDBOX_BUYER_EMAIL', 'SANDBOX_BUYER_PASSWORD'):
    os.environ[key] = ''
os.environ['EXTERNAL_CALL_LIMIT'] = '0'

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import tempfile
import time
import tracemalloc
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart.learning import PARTICLES, choose_pair, posterior
from scripts.benchmarks.learning_v2_1 import choose_pair as reference_pair


def timed(function):
    start = time.perf_counter_ns()
    result = function()
    return result, (time.perf_counter_ns() - start) / 1e6


def summarize(records, seed):
    baseline = np.array([np.median(r['baseline_ms']) for r in records])
    optimized = np.array([np.median(r['optimized_ms']) for r in records])
    indexes = np.random.default_rng(seed).integers(len(records), size=(2000, len(records)))
    ratios = np.median(baseline[indexes], axis=1) / np.median(optimized[indexes], axis=1)
    before, after = float(np.median(baseline)), float(np.median(optimized))
    return {'workloads': len(records), 'timed_pairs': sum(len(r['baseline_ms']) for r in records),
            'baseline_median_ms': round(before, 6), 'optimized_median_ms': round(after, 6),
            'speedup_ratio': round(before / after, 3),
            'latency_reduction_percent': round(100 * (1 - after / before), 2),
            'speedup_workload_bootstrap_ci95': [round(float(x), 3) for x in np.quantile(ratios, [.025, .975])],
            'baseline_p95_call_ms': round(float(np.quantile([x for r in records for x in r['baseline_ms']], .95)), 6),
            'optimized_p95_call_ms': round(float(np.quantile([x for r in records for x in r['optimized_ms']], .95)), 6),
            'median_definition': 'Median across workload medians; seven paired repeats per workload by default.',
            'bootstrap_unit': 'Workload; 2,000 resamples. Timing is machine-specific, not a service SLA.'}


def kernel_benchmark(count, repeats, seed):
    catalog = json.loads((ROOT / 'intentcart/data/catalog.json').read_text())
    rng = np.random.default_rng(seed)
    records = []
    max_error = 0.
    for number in range(count):
        size = [4, 8, 16, 24][number % 4]
        available = sorted(int(i) for i in rng.choice(24, size, replace=False))
        history, used = [], set()
        for _ in range((number // 4) % 4):
            a, b = (int(i) for i in rng.choice(available, 2, replace=False))
            history.append({'a': catalog[a]['id'], 'b': catalog[b]['id'],
                            'choice': str(rng.choice(['a', 'b', 'tie']))})
            used.add(tuple(sorted((a, b))))
        utilities, weights = posterior(catalog, history, rng.integers(0, 2, 7).tolist())
        functions = {'baseline': lambda: reference_pair(utilities, weights, available, used),
                     'optimized': lambda: choose_pair(utilities, weights, available, used)}
        for _ in range(2):
            for function in functions.values():
                function()
        record = {'workload': number, 'feasible_products': size, 'history_length': len(history),
                  'baseline_ms': [], 'optimized_ms': []}
        for _ in range(repeats):
            outcomes = {}
            order = ['baseline', 'optimized'] if rng.integers(2) else ['optimized', 'baseline']
            for name in order:
                outcomes[name], elapsed = timed(functions[name])
                record[name + '_ms'].append(elapsed)
            a, b = outcomes['baseline'], outcomes['optimized']
            assert a[:2] == b[:2], (number, a, b)
            error = abs(a[2] - b[2]); max_error = max(max_error, error)
            assert error < 5e-13, (number, error)
        a = reference_pair(utilities, weights, available, used, 'uncertainty')
        b = choose_pair(utilities, weights, available, used, 'uncertainty')
        assert a[:2] == b[:2] and abs(a[2] - b[2]) < 5e-13
        records.append(record)
    # Separate traced allocation check, excluded from latency timing.
    utilities, weights = posterior(catalog, [])
    peaks = {}
    for name, function in [('baseline', reference_pair), ('optimized', choose_pair)]:
        tracemalloc.start()
        function(utilities, weights, list(range(24)))
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peaks[name + '_traced_peak_bytes'] = peak
    return {'summary': summarize(records, seed + 1), 'max_gain_absolute_error': max_error,
            'untimed_uncertainty_parity_cases': count,
            'allocation_probe': {**peaks, 'scope': 'One 24-product call; Python/NumPy traced allocations, not process RSS.'},
            'records': records}


def api_benchmark(repeats, seed):
    with tempfile.TemporaryDirectory(prefix='intentcart-performance-') as directory:
        os.environ['DATABASE_PATH'] = str(Path(directory) / 'benchmark.sqlite3')
        from fastapi.testclient import TestClient
        from intentcart import app as module, config
        compute, select = module.compute, module.choose_pair
        class NoProvider:
            calls = 0
            def __getattr__(self, name):
                def forbidden(*args, **kwargs):
                    self.calls += 1
                    raise AssertionError('Provider access is forbidden in this benchmark.')
                return forbidden
        provider = NoProvider(); module.provider = provider
        rng = np.random.default_rng(seed)
        records = []
        try:
            with TestClient(module.app) as client:
                session = client.get('/api/session').json()
                client.headers.update({'origin': config.PUBLIC_URL, 'x-csrf-token': session['csrf_token']})
                for budget in [8000, 9000, 11500, 15000]:
                    for answers in [0, 1, 3, 4]:
                        module.RATES.clear()
                        module.compute, module.choose_pair = compute, select
                        response = client.post('/api/mission', json={'text': 'Comfortable rainy campus commute',
                            'budget_cents': budget, 'laptop_inches': 16, 'min_capacity_l': 20})
                        assert response.status_code == 200
                        state = response.json()
                        for choice in ['a', 'a', 'b', 'b'][:answers]:
                            response = client.post('/api/answer', json={'question_id': state['question']['id'], 'choice': choice})
                            assert response.status_code == 200
                            state = response.json()
                        record = {'budget_cents': budget, 'answers': answers, 'baseline_ms': [], 'optimized_ms': []}
                        expected = None
                        for repeat in range(-2, repeats):
                            order = ['baseline', 'optimized'] if rng.integers(2) else ['optimized', 'baseline']
                            for name in order:
                                # Restore the previous pipeline's unused question work and exact kernel.
                                module.compute = (lambda state, **kwargs: compute(state, include_question=True)) if name == 'baseline' else compute
                                module.choose_pair = reference_pair if name == 'baseline' else select
                                module.RATES.clear()  # Harness isolation only; production limiter is unchanged.
                                response, elapsed = timed(lambda: client.get('/api/rehearsal'))
                                assert response.status_code == 200
                                body = response.json()
                                if expected is None:
                                    expected = body
                                assert body == expected, (budget, answers, name)
                                if repeat >= 0:
                                    record[name + '_ms'].append(elapsed)
                        records.append(record)
                module.compute, module.choose_pair = compute, select
                assert client.get('/api/orders').json() == []
            assert provider.calls == 0
        finally:
            module.compute, module.choose_pair = compute, select
        return {'summary': summarize(records, seed + 2), 'responses_identical': True,
                'provider_calls': provider.calls, 'orders_created': 0,
                'scope': 'In-process FastAPI TestClient GET /api/rehearsal, including routing/serialization/SQLite; no TCP, production load or external providers.',
                'baseline': 'Same route/ranking with include_question forced True and byte-identical 2.1 acquisition kernel; reproduces prior unused-question work.',
                'records': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workloads', type=int, default=96)
    parser.add_argument('--repeats', type=int, default=7)
    parser.add_argument('--seed', type=int, default=20261010)
    parser.add_argument('--output', type=Path, default=ROOT / 'intentcart/data/performance.json')
    args = parser.parse_args()
    if args.workloads < 16 or args.repeats < 3:
        parser.error('At least 16 workloads and 3 paired repeats are required.')
    provenance = json.loads((ROOT / 'scripts/benchmarks/PROVENANCE.json').read_text())
    baseline = ROOT / 'scripts/benchmarks/learning_v2_1.py'
    assert hashlib.sha256(baseline.read_bytes()).hexdigest() == provenance['sha256']
    result = {'date': '2026-10-10', 'created_utc': datetime.now(timezone.utc).isoformat(),
              'seed': args.seed, 'repeats': args.repeats,
              'environment': {'system': platform.system(), 'machine': platform.machine(),
                              'python': platform.python_version(), 'numpy': np.__version__, 'cpu_count': os.cpu_count(),
                              'thread_ceilings': {key: os.environ[key] for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS')}},
              'design': 'Seeded fixed workloads; two warmups per variant; randomized paired order; float64; 2,048 hypotheses; actual 24-product catalog.',
              'kernel': kernel_benchmark(args.workloads, args.repeats, args.seed),
              'rehearsal_api': api_benchmark(args.repeats, args.seed + 3000),
              'limits': 'Local CPU timing and in-process API benchmark; no human study, model-quality improvement, concurrent-load or production SLA claim.'}
    result['source_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in ['intentcart/learning.py', 'intentcart/app.py', 'scripts/benchmark_learning.py', 'scripts/benchmarks/learning_v2_1.py']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({name: result[name]['summary'] for name in ['kernel', 'rehearsal_api']}, indent=2))
    print('Saved:', args.output)

if __name__ == '__main__':
    main()
