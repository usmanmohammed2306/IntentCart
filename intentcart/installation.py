"""Explicit single-instance installation; existing usage is never renewed."""
import hashlib,json,os,re,secrets
from pathlib import Path
from . import config,production


def prepare():
    from . import app
    if production.mode()!='production':raise ValueError('Managed installation requires the production profile')
    allocation=os.getenv('INTENTCART_ALLOCATION_ID','')
    if not re.fullmatch(r'[a-z0-9-]{8,80}',allocation):raise ValueError('An explicit fixed allocation ID is required')
    try:calls=int(os.environ['INTENTCART_BASELINE_CALLS']);reserved=int(os.environ['INTENTCART_BASELINE_RESERVED_MICROUSD'])
    except (KeyError,ValueError):raise ValueError('Explicit reviewed migration totals are required') from None
    if not 0<=calls<=config.CALL_LIMIT or not 0<=reserved<=config.ASTRO_BUDGET:raise ValueError('Migration totals exceed the configured allocation')
    declaration={'allocation':allocation,'calls':calls,'reserved_microusd':reserved,'call_limit':config.CALL_LIMIT,'reservation_limit':config.ASTRO_BUDGET}
    fingerprint=hashlib.sha256(json.dumps(declaration,sort_keys=True).encode()).hexdigest()
    path=Path(config.DATABASE_PATH).resolve();marker=path.parent/'.intentcart-volume';fresh=not path.exists()
    if fresh:
        if marker.exists():raise ValueError('Marked storage lost its ledger; reconcile a backup before restarting')
        if os.getenv('INTENTCART_FIRST_INSTALL_APPROVED')!='true':raise ValueError('Fresh storage requires explicit one-time installation approval')
        path.parent.mkdir(parents=True,exist_ok=True)
    elif not marker.is_file():raise ValueError('Existing storage has no installation marker')
    app.initialize()
    with app.database() as db:
        db.execute('CREATE TABLE IF NOT EXISTS installation (id INTEGER PRIMARY KEY CHECK(id=1),fingerprint TEXT NOT NULL)')
        counts=dict(db.execute('SELECT name,count FROM calls'))
        if fresh:
            if counts:raise ValueError('Fresh installation unexpectedly has usage; refusing replacement')
            db.executemany('INSERT INTO calls VALUES (?,?)',[('astro',calls),('astro_reserved_microusd',reserved)])
            db.execute('INSERT INTO installation VALUES (1,?)',(fingerprint,))
        else:
            row=db.execute('SELECT fingerprint FROM installation WHERE id=1').fetchone()
            if not row or row['fingerprint']!=fingerprint:raise ValueError('The fixed allocation declaration changed; automatic renewal is forbidden')
            if counts.get('astro',-1)<calls or counts.get('astro_reserved_microusd',-1)<reserved:raise ValueError('Usage moved backwards; refusing automatic repair')
    if fresh:
        fd=os.open(marker,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as file:file.write(secrets.token_hex(32)+'\n')
    production.validate(config)
    return {'installation':'approved-new-volume' if fresh else 'existing-ledger-retained','automatic_renewal':False}
