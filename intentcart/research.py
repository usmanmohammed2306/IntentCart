"""Read-only, source-bound local research artifacts. Never executes a trace."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = {
    'validity': ('validity-evaluation.json', 'scripts/evaluate_validity.py'),
    'reliability': ('reliability-evaluation.json', 'scripts/evaluate_reliability.py'),
    'acquisition': ('acquisition-evaluation.json', 'scripts/evaluate_acquisition.py'),
    'agent': ('agent-evaluation.json', 'scripts/evaluate_agent.py'),
    'learned': ('learned-evaluation.json', 'scripts/evaluate_learned_acquisition.py'),
    'budget': ('budget-roadmap-evaluation.json','scripts/evaluate_budget_roadmap.py'),
    'preferences': ('preference-workbench-evaluation.json','scripts/evaluate_preference_workbench.py'),
}
SCHEMAS = {'validity':'intentcart-validity-evaluation/1',
           'acquisition':'intentcart-acquisition-evaluation/1',
           'reliability':'intentcart-reliability-v1', 'agent':'intentcart-agent-evaluation/1',
           'learned':'intentcart-learned-evaluation/1',
           'budget':'intentcart-budget-roadmap-evaluation/1','preferences':'intentcart-preference-workbench-evaluation/1'}
SOURCES = {
    'agent': {'intentcart/workbench.py','intentcart/agent.py','intentcart/evidence_catalog.py','intentcart/workspace_preferences.py',
              'intentcart/missions.py','intentcart/data/missions-catalog.json','intentcart/data/evidence-catalog.json',
              'scripts/missions_oracle.py','scripts/evaluate_agent.py','intentcart/data/agent-protocol.json'},
    'budget': {'intentcart/finite_budget.py','intentcart/acquisition.py','intentcart/learned_acquisition.py',
               'scripts/evaluate_budget_roadmap.py','docs/protocols/roadmap-offline.json'},
    'preferences': {'intentcart/workspace_preferences.py','intentcart/missions.py','intentcart/data/missions-catalog.json',
                    'scripts/evaluate_preference_workbench.py','docs/protocols/preference-workbench.json'},
    'learned': {'intentcart/acquisition.py','intentcart/learned_acquisition.py',
                'scripts/evaluate_learned_acquisition.py','intentcart/data/learned-protocol.json'},
    'validity': {'intentcart/missions.py','intentcart/validity.py',
                 'intentcart/data/missions-catalog.json','scripts/evaluate_validity.py'},
    'acquisition': {'intentcart/acquisition.py','scripts/evaluate_acquisition.py',
                    'scripts/missions_oracle.py','intentcart/data/missions-catalog.json',
                    'intentcart/data/acquisition-protocol.json','intentcart/data/acquisition-cases.json'},
    'reliability': {'intentcart/procurement.py','intentcart/data/it-catalog.json','intentcart/workbench.py','intentcart/workbench_routes.py','intentcart/finite_budget.py','intentcart/learned_acquisition.py','intentcart/acquisition.py','intentcart/replay.py','intentcart/app.py','intentcart/paypal.py','intentcart/paypal_limits.py',
                    'intentcart/config.py','intentcart/missions.py','intentcart/validity.py',
                    'intentcart/assurance.py','intentcart/data/missions-catalog.json',
                    'scripts/evaluate_reliability.py','intentcart/agent.py','intentcart/agent_routes.py',
                    'intentcart/evidence_catalog.py','intentcart/workspace_preferences.py',
                    'intentcart/gateway.py','intentcart/research.py','intentcart/orchestrator.py',
                    'intentcart/orchestrator_routes.py','intentcart/workflow.py','intentcart/observability.py',
                    'intentcart/semantic.py','intentcart/sdk_transport.py', 'intentcart/production.py', 'intentcart/accounts.py','intentcart/studio.py','intentcart/trained_agent.py', 'intentcart/astro_auth.py', 'intentcart/installation.py', 'intentcart/__main__.py', 'intentcart/model_usage.py', 'intentcart/progress.py', 'intentcart/documents.py', 'intentcart/document_routes.py', 'intentcart/vector_search.py','intentcart/data/evidence-catalog.json'},
}


class EvidenceError(ValueError):
    pass


def read_report(kind):
    if kind not in REPORTS:
        raise EvidenceError('Unknown research artifact.')
    filename, command = REPORTS[kind]
    path = ROOT / 'intentcart' / 'data' / filename
    if not path.is_file():
        raise EvidenceError(f'No saved result. Run python {command} locally.')
    try:
        report = json.loads(path.read_text())
        sources = report['source_sha256']
        if (report.get('schema') != SCHEMAS[kind] or not isinstance(sources, dict)
                or set(sources) != SOURCES[kind]):
            raise ValueError('Missing source identities')
        for name, expected in sources.items():
            source = (ROOT / name).resolve()
            if (not source.is_relative_to(ROOT.resolve()) or
                    not source.is_file() or source.suffix not in ('.py', '.json') or
                    hashlib.sha256(source.read_bytes()).hexdigest() != expected):
                raise ValueError('Source mismatch')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise EvidenceError(f'Saved result is stale or invalid. Run python {command} locally.') from exc
    return report


def exported_trace(report, trace_id):
    try:
        for case in report.get('cases', []):
            if case['id'] == trace_id and isinstance(case['trace'], dict):
                return case['trace']
        for mutation in report.get('mutations', []):
            if 'mutation-' + mutation['id'] == trace_id and isinstance(mutation['shrunk_trace'], dict):
                return mutation['shrunk_trace']
    except (KeyError, TypeError, AttributeError) as exc:
        raise EvidenceError('The saved trace is malformed; regenerate the local report.') from exc
    raise EvidenceError('This saved trace does not exist.')
