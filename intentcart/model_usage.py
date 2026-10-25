"""Shared durable model allowance. Callers hold the app's database transaction."""
from fastapi import HTTPException
from . import config,gateway,production


def remaining(module,db):
    used=db.execute("SELECT COALESCE(SUM(count),0) AS n FROM calls WHERE name IN ('channel3','astro')").fetchone()['n']
    row=db.execute("SELECT count FROM calls WHERE name='astro_reserved_microusd'").fetchone()
    reserved=row['count'] if row else 0
    calls=max(0,config.CALL_LIMIT-used);budget=max(0,config.ASTRO_BUDGET-reserved)
    return {'profile':production.mode(),'enabled':module.outcome_model_status()['enabled'] and calls>0 and budget>0,'remaining_calls':calls,'remaining_reservation_microusd':budget,'notice':'Conservative remaining reservation, not actual billed spend.'}


def reserve(module,db,payload):
    if not module.outcome_model_status()['enabled']:raise HTTPException(409,'Inference is disabled. No request sent.')
    budget=remaining(module,db)
    if not budget['remaining_calls']:raise HTTPException(429,'External call ceiling reached. No request sent.')
    amount=gateway.reservation(payload,config.ASTRO_INPUT_RATE,config.ASTRO_OUTPUT_RATE)
    if amount>budget['remaining_reservation_microusd']:raise HTTPException(429,'Durable model budget exhausted. No request sent.')
    db.execute("INSERT INTO calls VALUES ('astro',1) ON CONFLICT(name) DO UPDATE SET count=count+1")
    db.execute("INSERT INTO calls VALUES ('astro_reserved_microusd',?) ON CONFLICT(name) DO UPDATE SET count=count+excluded.count",(amount,))
    return amount
