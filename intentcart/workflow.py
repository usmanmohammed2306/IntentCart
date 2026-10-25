"""LangGraph execution of one guarded transition per invocation.

SQLite and route CAS remain the durable authority. A graph invocation never
makes a model call, retries, grants consent or creates work in the background.
"""
from functools import lru_cache
from typing import Any, TypedDict
from langgraph.graph import StateGraph, START, END
from langsmith import tracing_context
from . import observability


class State(TypedDict):
    run: dict
    record: dict
    proposal: Any


@lru_cache(maxsize=1)
def compiled():
    graph = StateGraph(State)

    def transition(state):
        from . import orchestrator
        with observability.span('agent.transition', state['run'], state['record']):
            run, record = orchestrator._transition(state['run'], state['record'], state['proposal'])
        return {'run': run, 'record': record}

    phases = ('plan', 'investigate', 'verify', 'stress', 'report')
    for phase in phases:
        graph.add_node(phase, transition)
        graph.add_edge(phase, END)
    graph.add_conditional_edges(START, lambda state: state['run']['phase'], {p:p for p in phases})
    return graph.compile()


def advance(run, record, proposal=None):
    from . import orchestrator
    orchestrator.ensure(run, record)
    if run['phase'] not in ('plan', 'investigate', 'verify', 'stress', 'report'):
        raise orchestrator.ResearchError('This investigation has already stopped.')
    # LangSmith's environment-driven remote tracing is explicitly suppressed.
    with tracing_context(enabled=False):
        state = compiled().invoke({'run': run, 'record': record, 'proposal': proposal},
                                  config={'recursion_limit': 4, 'callbacks': []})
    return state['run'], state['record']
