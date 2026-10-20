"""One-request inference compatibility probe. Default is a no-network dry run."""
import argparse,json,sys
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.inference_preflight import inspect


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true');p.add_argument('--server',default='http://127.0.0.1:4000');p.add_argument('--expected-model');p.add_argument('--output',type=Path);args=p.parse_args()
    gates=inspect()
    if not args.execute:
        print(json.dumps({'mode':'dry_run','provider_requests':0,'maximum_execution_requests':1,'preflight':gates,'live_verified':False},indent=2));return 0
    url=urlsplit(args.server)
    if url.scheme!='http' or url.hostname not in ('127.0.0.1','localhost') or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):
        p.error('Use a local-only plain HTTP server origin.')
    if not gates['configured_enabled']:p.error('Server call, credit, budget and reviewed-price gates must be explicitly enabled first. No request sent.')
    if not args.expected_model:p.error('Specify the operator-reviewed expected model ID.')
    if not args.output or args.output.exists():p.error('Choose a new output path to preserve all probe outcomes.')
    import httpx
    from scripts.evaluate_live_agent import run
    protocol=json.loads((ROOT/'intentcart/data/agent-protocol.json').read_text())
    task=protocol['tasks'][0]
    with httpx.Client(base_url=args.server,timeout=30,follow_redirects=False,trust_env=False) as client:
        report=run(client,[task],1,args.expected_model,args.server,controllers=('direct',))
    args.output.write_text(json.dumps(report,indent=2)+'\n');print('Probe outcomes retained. Inspect errors, identity and reservations before any live-success claim.');return 0
if __name__=='__main__':raise SystemExit(main())
