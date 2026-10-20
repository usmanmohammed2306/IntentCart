"""Analyze a local reviewed transcript; never fetches URLs or runs a provider."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from intentcart.transcripts import analyze

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('--output',type=Path);args=p.parse_args()
    try:
        if args.input.stat().st_size>1000000:raise ValueError('Transcript exceeds one MiB review bound.')
        result=analyze(json.loads(args.input.read_text()))
        text=json.dumps(result,indent=2)+'\n'
        if args.output:
            if args.output.exists():raise ValueError('Choose a new output path; raw evidence is never overwritten.')
            args.output.write_text(text)
        else:print(text)
    except (OSError,ValueError) as e:print('Transcript analysis stopped:',str(e));return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
