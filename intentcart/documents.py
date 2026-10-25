"""Bounded document extraction in a short-lived, network-disabled process."""
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading

MAX_BYTES=1_500_000
MAX_TEXT=40_000
SLOTS=threading.BoundedSemaphore(2)


def extract(raw,suffix):
    if suffix not in ('.pdf','.md','.txt') or not raw or len(raw)>MAX_BYTES:
        raise ValueError('Use a PDF,Markdown or text file, up to 1.5 MB.')
    if not SLOTS.acquire(blocking=False):raise ValueError('Two files are being read. Please try again shortly.')
    try:
        with tempfile.TemporaryDirectory(prefix='intentcart-document-') as tmp:
            path=Path(tmp)/('upload'+suffix);path.write_bytes(raw);path.chmod(0o600)
            env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false')
            # A parser receives no account credentials and never model endpoints.
            for key in list(env):
                if any(word in key for word in ('API_KEY','SECRET','TOKEN','PASSWORD')):env.pop(key,None)
            result=subprocess.run([sys.executable,'-m','intentcart.documents','--worker',str(path)],cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,timeout=25)
            if result.returncode or len(result.stdout)>400_000:raise ValueError('Could not read this file. Use a short text-based PDF or text file.')
            payload=json.loads(result.stdout)
            if not payload.get('pages') or sum(len(p['text']) for p in payload['pages'])>MAX_TEXT:raise ValueError('Use a document with up to 40,000 readable characters.')
            return payload
    except (subprocess.TimeoutExpired,json.JSONDecodeError) as exc:raise ValueError('Reading the file stopped safely. Try a smaller text file.') from exc
    finally:SLOTS.release()


def worker(path):
    # Process-local network guard: external resources in files are never fetched.
    import socket
    def blocked(*args,**kwargs):raise OSError('Network disabled in document parser.')
    socket.socket.connect=blocked;socket.socket.connect_ex=blocked;socket.create_connection=blocked
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU,(18,18))
        resource.setrlimit(resource.RLIMIT_FSIZE,(2_000_000,2_000_000))
    except (ImportError,ValueError):pass
    path=Path(path);raw=path.read_bytes()
    if len(raw)>MAX_BYTES:raise ValueError('File too large.')
    pages=[]
    if path.suffix=='.pdf':
        from pypdf import PdfReader
        doc=PdfReader(BytesIO(raw),strict=True)
        if doc.is_encrypted or not 1<=len(doc.pages)<=8:raise ValueError('Use an unencrypted PDF of at most 8 pages.')
        for n,page in enumerate(doc.pages):pages.append({'page':n+1,'text':page.extract_text() or ''})
        method='pypdf text extraction + Docling Markdown structure; no OCR'
    else:
        text=raw.decode('utf-8-sig')
        if '\x00' in text:raise ValueError('Binary files are not supported.')
        pages=[{'page':1,'text':text}];method='Docling Markdown structure'
    if sum(len(p['text']) for p in pages)>MAX_TEXT:raise ValueError('Document too long.')
    from docling.backend.md_backend import MarkdownDocumentBackend
    from docling.datamodel.document import InputDocument
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.backend_options import MarkdownBackendOptions
    for page in pages:
        stream=BytesIO(page['text'].encode())
        document=InputDocument(path_or_stream=stream,format=InputFormat.MD,backend=MarkdownDocumentBackend,filename='page.md')
        options=MarkdownBackendOptions(enable_local_fetch=False,enable_remote_fetch=False,fetch_images=False,max_image_data_base64_bytes=1024,max_image_pixels=1)
        structured=MarkdownDocumentBackend(document,stream,options=options).convert()
        page['text']=structured.export_to_markdown().strip()
    pages=[p for p in pages if p['text']]
    if not pages or sum(len(p['text']) for p in pages)>MAX_TEXT:raise ValueError('No bounded readable text.')
    return {'pages':pages,'method':method,'source_authority':'Unverified user file, not accepted compatibility evidence.'}

if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--worker':raise SystemExit(2)
    try:print(json.dumps(worker(sys.argv[2]),ensure_ascii=True))
    except Exception:raise SystemExit(2)
