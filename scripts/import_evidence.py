"""Validate an operator-curated evidence collection without changing the app.

No URL fetching, model extraction or merchant authorization. Import is explicit
CLI work; accepted output is still a curated assertion requiring source review.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart.evidence_catalog import validate_catalog, identity

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, help='Optional validated copy; never overwrites the active catalog.')
    args = parser.parse_args()
    try:
        if args.input.is_symlink() or args.input.stat().st_size > 262144:
            raise ValueError('Use a regular JSON file no larger than 256 KiB.')
        result = validate_catalog(json.loads(args.input.read_text()))
        if args.output:
            active = ROOT / 'intentcart/data/evidence-catalog.json'
            if args.output.resolve() == active.resolve() or args.output.exists():
                raise ValueError('Choose a new output file; the active catalog and existing files are not overwritten.')
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'validated': True, 'products': len(result['products']), 'sources': len(result['sources']),
                          'source_sha256': identity(result), 'checkout_supported': False}))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print('Evidence import rejected: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
