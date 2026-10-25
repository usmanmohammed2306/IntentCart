"""Bounded local OpenTelemetry spans. No exporter endpoint or background thread.

Prompts, source text, keys, provider payloads and exception messages are never
attributes. Reading traces is scoped to the current owned run by the route.
"""
from collections import deque
from contextlib import contextmanager
import threading
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode

ALLOWED = frozenset({'agent.run_id', 'agent.phase', 'agent.task_revision', 'agent.engine', 'agent.role'})


class LocalSpans(SpanExporter):
    def __init__(self):
        self.lock = threading.Lock()
        self.rows = deque(maxlen=128)

    def export(self, spans):
        with self.lock:
            for span in spans:
                context = span.get_span_context()
                self.rows.append({'name': span.name, 'trace_id': f'{context.trace_id:032x}',
                    'span_id': f'{context.span_id:016x}', 'start_time_ns': span.start_time,
                    'end_time_ns': span.end_time, 'duration_ms': round((span.end_time-span.start_time)/1e6, 3),
                    'status': span.status.status_code.name,
                    'attributes': {k:v for k,v in span.attributes.items() if k in ALLOWED}})
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=30000):
        return True


_exporter = LocalSpans()
_provider = TracerProvider(resource=Resource.create({'service.name': 'intentcart'}))
_provider.add_span_processor(SimpleSpanProcessor(_exporter))
_tracer = _provider.get_tracer('intentcart.agent', '1')


@contextmanager
def span(name, run, record, role=None):
    attributes = {'agent.run_id': run['id'], 'agent.phase': run['phase'],
                  'agent.task_revision': record['revision'], 'agent.engine': run['options']['engine']}
    if role:
        attributes['agent.role'] = role
    with _tracer.start_as_current_span(name, attributes=attributes,
                                      record_exception=False, set_status_on_exception=False) as current:
        try:
            yield current
        except Exception:
            current.set_status(Status(StatusCode.ERROR, 'Operation rejected'))
            raise


def read(run_id):
    with _exporter.lock:
        rows = [{**r, 'attributes': dict(r['attributes'])} for r in _exporter.rows
                if r['attributes'].get('agent.run_id') == run_id]
    return {'schema': 'intentcart-local-traces/1', 'run_id': run_id, 'spans': rows,
            'retention': 'Last 128 spans in this process; reset on restart.',
            'export': 'Local only. No network exporter, prompt capture or background worker.'}
