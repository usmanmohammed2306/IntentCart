"""Strict offline transcript ingestion. Imported claims are not verified live runs."""
from collections import Counter,defaultdict
from hashlib import sha256
import json
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from .agent import Action

class Attempt(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    outcome:Literal['ok','timeout','http_error','schema_error','revision_conflict','budget_stop','unattempted']
    http_status:int|None=Field(default=None,ge=100,le=599)
    paid_microusd:int|None=Field(default=None,ge=0,le=100000000)
    reserved_microusd:int|None=Field(default=None,ge=0,le=100000000)
    input_tokens:int|None=Field(default=None,ge=0,le=10000000)
    output_tokens:int|None=Field(default=None,ge=0,le=10000000)
    action:Action|None=None
    uncertain_transport:bool=False

class Trial(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    task_id:str=Field(min_length=1,max_length=100)
    controller:str=Field(min_length=1,max_length=80)
    model_id:str=Field(min_length=1,max_length=100)
    repeat_id:str=Field(min_length=1,max_length=80)
    evidence_kind:Literal['local_fixture','mock_provider','live_imported']
    status:Literal['supported','deferred','failed','capped','unattempted']
    decision_id:str|None=Field(default=None,max_length=100)
    attempts:list[Attempt]=Field(default_factory=list,max_length=48)


def analyze(payload):
    if type(payload) is not dict or set(payload)!={'schema','trials'} or payload['schema']!='intentcart-transcripts/1':raise ValueError('Unsupported transcript collection.')
    if type(payload['trials']) is not list or not 1<=len(payload['trials'])<=256:raise ValueError('Supply one to 256 bounded trials.')
    trials=[Trial.model_validate(t) for t in payload['trials']];seen=set();groups=defaultdict(list)
    for trial in trials:
        key=(trial.task_id,trial.controller,trial.model_id,trial.repeat_id,trial.evidence_kind)
        if key in seen:raise ValueError('Duplicate repeat identity cannot manufacture repeated evidence.')
        seen.add(key);groups[key[:3]+(trial.evidence_kind,)].append(trial)
        if trial.status=='supported' and (not trial.decision_id or not trial.attempts or any(a.uncertain_transport or a.outcome!='ok' for a in trial.attempts)):
            raise ValueError('A supported imported trial needs a decision, attempts and no unresolved error.')
    results=[]
    for key,rows in groups.items():
        attempts=[a for r in rows for a in r.attempts];supported=sum(r.status=='supported' for r in rows)
        costs_known=bool(attempts) and all(a.paid_microusd is not None for a in attempts)
        paid=sum(a.paid_microusd or 0 for a in attempts)
        decisions=Counter(r.decision_id for r in rows if r.status=='supported')
        results.append({'task_id':key[0],'controller':key[1],'model_id':key[2],'evidence_kind':key[3],
                        'trials':len(rows),'supported_claims':supported,'attempts':len(attempts),
                        'errors':dict(Counter(a.outcome for a in attempts if a.outcome!='ok')),
                        'uncertain_transport':sum(a.uncertain_transport for a in attempts),
                        'paid_microusd':paid if costs_known else None,
                        'reserved_microusd':sum(a.reserved_microusd or 0 for a in attempts),
                        'cost_per_supported_completion_microusd':paid/supported if costs_known and supported else None,
                        'repeated_supported_decision_agreement':max(decisions.values())/supported if supported>=2 else None,
                        'statuses':dict(Counter(r.status for r in rows))})
    return {'schema':'intentcart-transcript-analysis/1','input_sha256':sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest(),
            'groups':results,'verified_live':False,'notice':'Strictly parsed imported claims, not independently verified provider calls, receipts, human participants or model quality. Failure cost remains in the numerator; unknown billed amounts remain unknown. Single trials have no repeat-consistency estimate.'}
