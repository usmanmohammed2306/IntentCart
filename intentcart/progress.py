"""Owned, bounded server-sent progress. Reading never advances the agent."""
import asyncio
import json
import threading
import time
from fastapi import Request,HTTPException,Query
from fastapi.responses import StreamingResponse
from . import orchestrator as flow

DURATION=20
ACTIVE={}
LOCK=threading.Lock()


def register(module):
    @module.app.get('/api/agent/research/events')
    def events(request:Request,run_id:str=Query(pattern=r'^[a-f0-9]{32}$')):
        with module.database() as db:
            sid,state=module.owner(request,db)
            run,record=state.get('research_run'),state.get('evidence_agent')
            if not run or run['id']!=run_id:raise HTTPException(404,'Owned investigation not found.')
            try:flow.ensure(run,record)
            except (ValueError,KeyError) as exc:raise HTTPException(409,'Investigation changed. Refresh it first.') from exc
        with LOCK:
            now=time.monotonic()
            for key in list(ACTIVE):
                if ACTIVE[key]<now:del ACTIVE[key]
            if sid in ACTIVE:raise HTTPException(429,'A progress view is already open.')
            if len(ACTIVE)>=64:raise HTTPException(429,'Progress capacity reached. Please try again shortly.')
            ACTIVE[sid]=now+DURATION+10
        async def stream():
            started=time.monotonic();previous=None
            try:
                while time.monotonic()-started<DURATION:
                    if await request.is_disconnected():break
                    with module.database() as db:
                        try:
                            owner,current=module.owner(request,db)
                            value=current.get('research_run');record=current.get('evidence_agent')
                            if owner!=sid or not value or value['id']!=run_id:break
                            flow.ensure(value,record)
                        except (HTTPException,ValueError,KeyError):break
                        snapshot={k:value[k] for k in ('id','revision','phase','status')}
                        snapshot['inflight']=bool(value.get('inflight'))
                    serialized=json.dumps(snapshot,separators=(',',':'))
                    if serialized!=previous:
                        yield 'data: '+serialized+'\n\n';previous=serialized
                    else:yield ': checkpoint unchanged\n\n'
                    if snapshot['status'] in ('COMPLETE','CANCELLED','PAUSED','WAITING_FOR_USER'):break
                    await asyncio.sleep(.5)
                yield 'event: end\ndata: {}\n\n'
            finally:
                with LOCK:ACTIVE.pop(sid,None)
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'private,no-store','X-Accel-Buffering':'no'})
