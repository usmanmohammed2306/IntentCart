"""Read-only deployment check; explicit storage initialization never resets state."""
import argparse
import json
import os
from pathlib import Path
import secrets
from . import config, production


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--init-storage',action='store_true')
    args=parser.parse_args()
    if args.init_storage:
        root=Path(config.DATABASE_PATH).resolve().parent
        root.mkdir(parents=True,exist_ok=True)
        marker=root/'.intentcart-volume'
        if not marker.exists():
            fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f:f.write(secrets.token_hex(32)+'\n')
    result=production.configuration(config)
    print(json.dumps(result,indent=2))
    return 0 if result['configuration_ready'] else 1

if __name__=='__main__':raise SystemExit(main())
