"""Offline workstation report preparation. No recruitment, collection or network.

Fictional records remain synthetic. Entered human records are observer claims,
not independent proof of actual participants or identities.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TASKS = ('evidence','repair','source-change')
QUESTIONS = ('approval','evidence','price')


class Sheet(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    local_id: str = Field(pattern=r'^P[0-9]{3}$')
    consent: bool
    adult_confirmed: bool
    status: Literal['completed','incomplete','withdrawn','declined']
    tasks: dict[str,Literal['completed','incomplete','not_attempted']] = Field(default_factory=dict)
    comprehension: dict[str,Literal['yes','no','unsure']] = Field(default_factory=dict)
    elapsed_seconds: int | None = Field(default=None,ge=0,le=7200)
    voluntary_rating_1_to_7: int | None = Field(default=None,ge=1,le=7)


def analyze(payload):
    if type(payload) is not dict or set(payload) != {'schema','evidence_kind','records'} or payload['schema'] != 'intentcart-workstation-observation-sheets/1':
        raise ValueError('Use the closed workstation observation-sheet schema.')
    kind = payload['evidence_kind']
    if kind not in ('fictional','human_observer_entry'):
        raise ValueError('Declare fictional or human-observer provenance explicitly.')
    if type(payload['records']) is not list or len(payload['records']) > 256:
        raise ValueError('Supply zero through 256 bounded sheets.')
    sheets = [Sheet.model_validate(row) for row in payload['records']]
    ids = [s.local_id for s in sheets]
    if len(ids) != len(set(ids)):
        raise ValueError('Repeated local IDs cannot manufacture extra records.')
    for sheet in sheets:
        if set(sheet.tasks)-set(TASKS) or set(sheet.comprehension)-set(QUESTIONS):
            raise ValueError('Use only the three declared tasks and questions.')
        if sheet.status in ('completed','incomplete') and not (sheet.consent and sheet.adult_confirmed):
            raise ValueError('Active observer sheets require explicit adult and voluntary-consent declarations.')
        if sheet.status in ('withdrawn','declined') and (sheet.tasks or sheet.comprehension or sheet.elapsed_seconds is not None or sheet.voluntary_rating_1_to_7 is not None):
            raise ValueError('Withdrawn/declined sheets must contain no answers, timings or ratings.')
        if sheet.status == 'completed' and (set(sheet.tasks) != set(TASKS) or any(v != 'completed' for v in sheet.tasks.values()) or set(sheet.comprehension) != set(QUESTIONS)):
            raise ValueError('A completed sheet requires every task and comprehension answer, including errors.')
    active = [s for s in sheets if s.status in ('completed','incomplete')]
    human = len(active) if kind == 'human_observer_entry' else 0
    completed = sum(s.status == 'completed' for s in active)
    questions = {}
    for key in QUESTIONS:
        answers = Counter(s.comprehension[key] for s in active if key in s.comprehension)
        questions[key] = {'answered':sum(answers.values()),'correct_no':answers['no'],
                          'incorrect_yes':answers['yes'],'unsure':answers['unsure'],
                          'unanswered':len(active)-sum(answers.values())}
    return {'schema':'intentcart-workstation-pilot-report/1', 'evidence_kind':kind,
            'study_status':'not_conducted' if not human else 'observer_entered_claims_not_independently_verified',
            'recorded_active_human_participants':human,'independently_verified_participants':0,
            'fictional_records':len(active) if kind=='fictional' else 0,
            'entered_records':len(sheets),'completed_records':completed,
            'incomplete_records':len(active)-completed,
            'withdrawn_records_excluded':sum(s.status=='withdrawn' for s in sheets),
            'declined_records_excluded':sum(s.status=='declined' for s in sheets),
            'tasks':{key:dict(Counter(s.tasks.get(key,'not_attempted') for s in active)) for key in TASKS},
            'comprehension':questions,
            'elapsed_seconds':{'reported_records':sum(s.elapsed_seconds is not None for s in active),
                               'values':[s.elapsed_seconds for s in active if s.elapsed_seconds is not None]},
            'voluntary_rating':{'scale':'1..7, optional, observer-entered',
                                'reported_records':sum(s.voluntary_rating_1_to_7 is not None for s in active),
                                'values':[s.voluntary_rating_1_to_7 for s in active if s.voluntary_rating_1_to_7 is not None]},
            'provider_requests':0,'payment_operations':0,
            'notice':'Fictional records never count as humans. Local IDs/consent entries do not prove unique people. Withdrawn/declined records contribute no task/comprehension/rating results. Descriptive only; no causal benefit or usability superiority is inferred.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Use a new output path to preserve prior outcomes.')
    payload={'schema':'intentcart-workstation-observation-sheets/1','evidence_kind':'fictional','records':[]}
    if args.input:
        if args.input.is_symlink() or args.input.stat().st_size > 1024*1024:parser.error('Supply a bounded ordinary local file.')
        payload=json.loads(args.input.read_text())
    report=analyze(payload)
    if payload['evidence_kind']=='human_observer_entry':
        private=(ROOT/'output/private-pilot').resolve()
        if not args.output.resolve().is_relative_to(private):parser.error('Human aggregates stay in ignored output/private-pilot for privacy review; no automatic public export.')
    report['protocol_sha256']=hashlib.sha256((ROOT/'docs/protocols/workstation-pilot.json').read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with args.output.open('x') as out:out.write(json.dumps(report,indent=2)+'\n')
    args.output.chmod(0o600)
    print(json.dumps({k:report[k] for k in ('study_status','evidence_kind','recorded_active_human_participants','fictional_records')}))
    return 0


if __name__=='__main__':raise SystemExit(main())
