"""Owned, revision-checked agent endpoints; no new payment route."""
import json
from typing import Literal
from fastapi import Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from . import agent, gateway, config, evidence_catalog, research

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Start(Strict):
    query: str = Field(default='', max_length=1000)
    goal: dict
    catalog_kind: Literal['curated', 'fixture'] = 'curated'
    inspection_budget: int = Field(default=16, ge=0, le=32, strict=True)
    scenario_confirmed: bool = Field(default=False, strict=True)

class Revision(Strict):
    revision: int = Field(ge=1, strict=True)

class Step(Revision):
    policy: Literal['targeted', 'census'] = 'targeted'

class ModelStep(Revision):
    controller: Literal['direct', 'guided'] = 'direct'

class Answer(Revision):
    allow_driver: bool = Field(strict=True)

class Change(Revision):
    goal: dict | None = None
    exclude: str | None = Field(default=None, max_length=100)
    scenario_confirmed: bool | None = Field(default=None, strict=True)

class Compare(Revision):
    a: str = Field(max_length=40)
    b: str = Field(max_length=40)
    choice: Literal['a', 'b', 'tie', 'skip']

def register(module):
    app = module.app
    def current(state, revision=None):
        record = state.get('evidence_agent')
        if not record:
            raise HTTPException(409, 'Start a reviewed evidence task first.')
        if revision is not None and record['revision'] != revision:
            raise HTTPException(409, 'Task changed. Refresh before continuing.')
        try:
            agent.ensure_current(record)
        except agent.AgentError as exc:
            raise HTTPException(409, str(exc)) from exc
        return record

    def store(db, sid, state, record):
        state['evidence_agent'] = record
        state['version'] += 1
        # Agent changes do not alter the independent sandbox mission/quote.
        module.save(db, sid, state)
        return agent.view(record)

    def mutate(body, request, fn):
        with module.database() as db:
            sid, state = module.owner(request, db, True)
            try:
                return store(db, sid, state, fn(current(state, body.revision)))
            except (agent.AgentError, ValueError, KeyError, TypeError) as exc:
                raise HTTPException(409, str(exc)) from exc

    @app.get('/agent')
    def page():
        return FileResponse(module.ROOT / 'web/agent.html')

    @app.get('/api/agent/catalog')
    def catalog(kind: Literal['curated', 'fixture'] = 'curated'):
        return evidence_catalog.public_catalog(agent.catalog_for(kind)) if kind == 'curated' else module.outcomes.public_catalog()

    @app.get('/api/agent/evaluation')
    def evaluation(kind: Literal['agent', 'learned'] = 'agent', full: bool = False):
        try:
            report = research.read_report(kind)
            return report if full else {k: v for k, v in report.items() if k not in ('records', 'model')}
        except research.EvidenceError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get('/api/agent')
    def status(request: Request):
        with module.database() as db:
            _, state = module.owner(request, db)
            record = state.get('evidence_agent')
            try:
                return {'task': agent.view(record), 'model_enabled': module.outcome_model_status()['enabled']}
            except agent.AgentError as exc:
                return {'task': None, 'stale': True, 'notice': str(exc), 'model_enabled': False}

    @app.post('/api/agent')
    def start(body: Start, request: Request):
        with module.database() as db:
            sid, state = module.owner(request, db, True)
            try:
                record = agent.create(body.query, body.goal, body.catalog_kind, body.inspection_budget,
                                      body.scenario_confirmed, state.get('evidence_agent', {}).get('revision', 0) + 1)
                return store(db, sid, state, record)
            except (ValueError, KeyError, TypeError) as exc:
                raise HTTPException(422, str(exc)) from exc

    @app.post('/api/agent/step')
    def step(body: Step, request: Request):
        return mutate(body, request, lambda r: agent.step(r, agent.local_action(r, body.policy)))

    @app.post('/api/agent/answer')
    def answer(body: Answer, request: Request):
        return mutate(body, request, lambda r: agent.answer(r, body.allow_driver))

    @app.post('/api/agent/revise')
    def change(body: Change, request: Request):
        return mutate(body, request, lambda r: agent.revise(r, body.goal, body.exclude, body.scenario_confirmed))

    @app.post('/api/agent/preference')
    def preference(body: Compare, request: Request):
        return mutate(body, request, lambda r: agent.compare(r, body.a, body.b, body.choice))

    @app.post('/api/missions/preference')
    def mission_preference(body: Compare, request: Request):
        with module.database() as db:
            sid, state = module.owner(request, db, True)
            record = module.outcome_record(state, body.revision)
            try:
                return module.store_outcome(db, sid, state, module.outcomes.prefer(record, body.a, body.b, body.choice))
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc

    @app.get('/api/agent/export')
    def export(request: Request):
        with module.database() as db:
            _, state = module.owner(request, db)
            result = agent.view(current(state))
        return JSONResponse(result, headers={'Content-Disposition': 'attachment; filename="intentcart-agent-decision.json"'})

    @app.post('/api/agent/model-step')
    def model_step(body: ModelStep, request: Request):
        with module.database() as db:
            sid, state = module.owner(request, db, True)
            record = current(state, body.revision)
            if record['pending_question'] or record['status'] != 'ACTIVE' or record.get('tool_count', 0) >= agent.MAX_STEPS:
                raise HTTPException(409, 'Task is paused or stopped. No model request was sent.')
            if not module.outcome_model_status()['enabled']:
                raise HTTPException(409, 'Inference is disabled. No credits used; local tool policies remain available.')
            used = db.execute("SELECT COALESCE(SUM(count),0) AS n FROM calls WHERE name IN ('channel3','astro')").fetchone()['n']
            if used >= config.CALL_LIMIT:
                raise HTTPException(429, 'External call ceiling reached; no request sent.')
            payload = agent.model_body(record, config.ASTRO_MODEL, body.controller)
            reserve = gateway.reservation(payload, config.ASTRO_INPUT_RATE, config.ASTRO_OUTPUT_RATE)
            row = db.execute("SELECT count FROM calls WHERE name='astro_reserved_microusd'").fetchone()
            if (row['count'] if row else 0) + reserve > config.ASTRO_BUDGET:
                raise HTTPException(429, 'Model budget reservation exhausted; no request sent.')
            db.execute("INSERT INTO calls VALUES ('astro',1) ON CONFLICT(name) DO UPDATE SET count=count+1")
            db.execute("INSERT INTO calls VALUES ('astro_reserved_microusd',?) ON CONFLICT(name) DO UPDATE SET count=count+excluded.count", (reserve,))
            db.commit()  # Lost responses retain reservations, no automatic retry.
        try:
            payload = gateway.raw_call(config.ASTRO_URL, config.ASTRO_KEY, payload)
            raw = payload['choices'][0]['message']['content']
            action = agent.Action.model_validate_json(gateway.action_json(raw))
        except (gateway.GatewayError, ValueError, TypeError, KeyError, IndexError) as exc:
            raise HTTPException(502, 'Model action failed strict validation; reservation retained and task unchanged. No retry sent.') from exc
        with module.database() as db:
            sid, state = module.owner(request, db, True)
            try:
                # Any concurrent human change rejects the stale model response.
                record = agent.step(current(state, body.revision), action, origin='model')
                result = store(db, sid, state, record)
                usage = payload.get('usage', {})
                result['usage'] = {k: v for k, v in usage.items() if k in ('prompt_tokens', 'completion_tokens', 'total_tokens') and type(v) is int and v >= 0} if isinstance(usage, dict) else {}
                result['reserved_microusd'] = reserve
                model = payload.get('model')
                reported = isinstance(model, str) and 0 < len(model) <= 100
                result['model_id'] = model if reported else config.ASTRO_MODEL
                result['model_id_basis'] = 'provider_response' if reported else 'server_configuration'
                result['controller'] = body.controller
                return result
            except agent.AgentError as exc:
                raise HTTPException(409, str(exc)) from exc
