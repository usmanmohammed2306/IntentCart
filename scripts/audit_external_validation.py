"""Check retained public live/sandbox artifacts offline; never contact providers.

This establishes local artifact consistency, not independent attestation of
network calls, billing, identities or human participation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from intentcart import transcripts

def require(condition,message):
    if not condition:raise ValueError(message)

def evaluate(directory=ROOT/'submission',root=ROOT):
    live=json.loads((directory/'live-validation.json').read_text())
    payment=json.loads((directory/'workstation-sandbox-verification.json').read_text())
    for report in (live,payment):
        require(bool(report['source_sha256']),'Missing source identities.')
        for name,expected in report['source_sha256'].items():
            path=(root/name).resolve()
            require(path.is_relative_to(root.resolve()) and path.is_file() and not path.is_symlink(), 'Unsafe source path.')
            require(hashlib.sha256(path.read_bytes()).hexdigest()==expected,'External evidence source changed: '+name)
    require(live['schema']=='intentcart-external-live-evidence/1','Unknown live schema.')
    require(0<live['actual_model_requests']<=live['authorization']['max_requests']<=48,'Live request allowance mismatch.')
    require(0<=live['account_gateway_usage_usd_observed']<=live['authorization']['max_free_credit_usd']<=1,'Credit allowance mismatch.')
    require(live['strict_actions_accepted']+live['strict_outputs_rejected']==live['actual_model_requests'],'Lost failed model requests.')
    require(sum(p['request_attempts'] for p in live['phases'])+1==live['actual_model_requests'],'Diagnostic request missing from total.')
    native=next(p for p in live['phases'] if p['run']=='approved-wrapper')
    require(native['compatibility_response_observed'],'No successful live compatibility response.')
    for phase in live['phases']:
        require(transcripts.analyze({'schema':'intentcart-transcripts/1','trials':phase['trials']})==phase['analysis'],'Transcript analysis changed.')
        require(all(t['model_id']==live['reported_model_id'] for t in phase['trials'] if t['attempts']),'Model identities differ between attempted trials.')
    groups=native['analysis']['groups']
    require(len(groups)==2 and {g['controller'] for g in groups}=={'direct','guided'},'Matched controllers missing.')
    require(all(g['trials']==2 and g['supported_claims']==2 and g['repeated_supported_decision_agreement']==1 for g in groups),'Declared native repeats do not match.')
    harder=next(p for p in live['phases'] if p['run']=='approved-driver-task')
    require([t['status'] for t in harder['trials']]==['supported','failed','unattempted','unattempted'],'Harder-task failure or stopped trials lost.')
    require(harder['trials'][1]['attempts'][-1]['reserved_microusd']>0,'Failed request reservation must remain counted.')
    require(payment['schema']=='intentcart-workstation-sandbox-evidence/1' and payment['environment']=='PayPal sandbox only','Wrong payment environment.')
    require(payment['server_api_requests']<=payment['approved_server_api_ceiling']<=12,'Sandbox API allowance exceeded.')
    require(payment['total_cents']==27900 and payment['currency']=='USD' and payment['shipping_cents']==payment['tax_cents']==0,'Basket terms changed.')
    require(payment['capture_amount']==payment['refund_amount']=={'currency_code':'USD','value':'279.00'},'Full refund amount mismatch.')
    require((payment['order_status'],payment['capture_status'],payment['refund_status'],payment['application_status'])==('COMPLETED','REFUNDED','COMPLETED','REFUNDED'),'Sandbox payment not fully refunded.')
    require(bool(payment['checks']) and all(v is True for v in payment['checks'].values()),'Incomplete sandbox checks.')
    require(payment['cash_usd']==live['authorization']['cash_usd']==0 and live['human_participants']==0,'Cash or human evidence mislabeled.')
    return {'schema':'intentcart-external-validation-audit/1','checked_offline':True,
            'artifact_sha256':{name:hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in ('live-validation.json','workstation-sandbox-verification.json')},
            'completed_bounded_external_milestones':[78,79,81,84],'pending_human_milestones':[88],
            'actual_model_requests':live['actual_model_requests'],'sandbox_server_api_requests':payment['server_api_requests'],
            'account_gateway_usage_usd_observed':live['account_gateway_usage_usd_observed'],
            'cash_usd':0,'human_participants':0,'all_checks_pass':True,
            'notice':'Offline local consistency audit of operator-observed artifacts. No independent external attestation, population model-quality claim, human study or production certification.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=ROOT/'submission')
    args=parser.parse_args()
    print(json.dumps(evaluate(args.directory),indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
