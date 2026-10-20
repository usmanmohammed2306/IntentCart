"""Explicit, local-only export. Output may contain voluntarily supplied personal text."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from intentcart import config

parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
db=sqlite3.connect(config.DATABASE_PATH)
rows=db.execute('SELECT data,created FROM feedback ORDER BY created').fetchall()
Path(args.output).write_text(json.dumps([{'response':json.loads(data),'created':created} for data,created in rows],indent=2)+'\n')
print(f'Exported {len(rows)} consented responses locally. These are not validated human-study results.')
