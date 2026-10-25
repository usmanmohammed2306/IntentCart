"""Explicit private SQLite snapshot verification; no upload or scheduling."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
from . import config


def snapshot(destination):
    source=Path(config.DATABASE_PATH).resolve();target=Path(destination).resolve()
    if not source.is_file() or target.exists() or source==target:raise ValueError('Select an existing source and a new private destination.')
    target.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True) as original,sqlite3.connect(target) as copy:
        original.backup(copy)
        if copy.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Backup integrity check failed.')
        calls=dict(original.execute('SELECT name,count FROM calls'));saved=dict(copy.execute('SELECT name,count FROM calls'))
        if calls!=saved:raise ValueError('Usage changed during backup verification; take another snapshot before migration.')
    target.chmod(0o600)
    return {'integrity':'ok','usage_ledger_matches':True,'notice':'Private backup may contain sessions,files and sandbox records.Keep it out of Git and public artifacts.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    print(json.dumps(snapshot(parser.parse_args().output),indent=2))
