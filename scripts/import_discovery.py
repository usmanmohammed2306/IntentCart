"""Print reviewed Channel3 export candidates at zero external calls."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from intentcart import evidence_catalog,discovery_import

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);args=p.parse_args()
    try:
        if args.input.stat().st_size>64000:raise ValueError('Discovery export is too large.')
        print(json.dumps(discovery_import.review(json.loads(args.input.read_text()),evidence_catalog.load_catalog()),indent=2))
    except (OSError,ValueError) as e:print('Discovery review stopped:',str(e));return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
