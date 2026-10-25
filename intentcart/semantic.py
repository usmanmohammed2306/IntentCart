"""Offline PyTorch/Hugging Face retrieval over already observable evidence.

Only the explicit setup command downloads the pinned public encoder. Runtime
loads safetensors from a reviewed local manifest, always on CPU, without remote
code, provider calls, GPU deployment or background indexing.
"""
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import threading

REPO = 'sentence-transformers/all-MiniLM-L6-v2'
REVISION = '173eb854beababc71d6c2962980f98ac8f7a975d'
MAX_DOCS = 256
LOCK = threading.RLock()
_MODEL = None
_MODEL_ID = None
_CACHE = OrderedDict()


class EncoderUnavailable(ValueError):
    pass


def directory():
    value = os.getenv('INTENTCART_EMBEDDING_DIR', '')
    return Path(value).resolve() if value else None


def configured_identity():
    root = directory()
    if root is None:
        return 'bm25-only'
    try:
        raw = (root/'manifest.json').read_bytes()
        if len(raw) > 32000:
            return 'invalid-manifest'
        return hashlib.sha256(raw).hexdigest()
    except OSError:
        return 'missing-manifest'


def source_text(source):
    return ' '.join(str(source.get(k) or '') for k in
                    ('product_id','field','value','unit','summary','excerpt'))[:3000]


def load():
    global _MODEL, _MODEL_ID
    root = directory()
    if root is None:
        raise EncoderUnavailable('not_configured')
    identity = configured_identity()
    if _MODEL is not None and (str(root),identity) == _MODEL_ID:
        return _MODEL
    try:
        manifest = json.loads((root/'manifest.json').read_text())
        if manifest.get('repo') != REPO or manifest.get('revision') != REVISION or manifest.get('dimension') != 384:
            raise EncoderUnavailable('invalid_manifest')
        files = manifest['files']
        required = {'config.json','model.safetensors','tokenizer.json','tokenizer_config.json','vocab.txt'}
        if not required <= set(files) or len(files) > 20:
            raise EncoderUnavailable('invalid_manifest')
        for name, expected in files.items():
            path = (root/name).resolve()
            if not path.is_relative_to(root) or path.suffix not in ('.json','.safetensors','.txt','.md'):
                raise EncoderUnavailable('invalid_manifest')
            if path.stat().st_size > 120_000_000 or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise EncoderUnavailable('artifact_mismatch')
        config = json.loads((root/'config.json').read_text())
        if config.get('model_type') != 'bert' or config.get('hidden_size') != 384 or config.get('auto_map'):
            raise EncoderUnavailable('unsupported_encoder')
        # These affect only this local library; no token/account is supplied.
        os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
        import torch
        from transformers import AutoModel, AutoTokenizer
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        tokenizer = AutoTokenizer.from_pretrained(str(root), local_files_only=True, trust_remote_code=False)
        model = AutoModel.from_pretrained(str(root), local_files_only=True,
                                         trust_remote_code=False, use_safetensors=True).to('cpu').eval()
        _MODEL = (torch, tokenizer, model)
        _MODEL_ID = (str(root),identity)
        _CACHE.clear()
        return _MODEL
    except EncoderUnavailable:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        raise EncoderUnavailable('local_encoder_unavailable') from exc


def _encode(texts, runtime):
    torch, tokenizer, model = runtime
    with torch.inference_mode():
        batch = tokenizer(texts, padding=True, truncation=True, max_length=256, return_tensors='pt')
        output = model(**batch).last_hidden_state
        mask = batch['attention_mask'].unsqueeze(-1).to(output.dtype)
        pooled = (output*mask).sum(1)/mask.sum(1).clamp(min=1e-9)
        return torch.nn.functional.normalize(pooled, p=2, dim=1).cpu()


def rank(query, docs):
    if type(query) is not str or not query.strip() or len(query) > 1000 or not 1 <= len(docs) <= MAX_DOCS:
        raise EncoderUnavailable('invalid_retrieval_bounds')
    ids = [d['source_id'] for d in docs]
    if len(set(ids)) != len(ids):
        raise EncoderUnavailable('duplicate_sources')
    with LOCK:
        runtime = load()
        torch = runtime[0]
        texts = [source_text(d['source']) for d in docs]
        keys = [hashlib.sha256(t.encode()).hexdigest() for t in texts]
        missing = list(dict.fromkeys(k for k in keys if k not in _CACHE))
        by_key = dict(zip(keys,texts))
        for start in range(0,len(missing),16):
            part = missing[start:start+16]
            vectors = _encode([by_key[k] for k in part], runtime)
            for key, vector in zip(part, vectors):
                _CACHE[key] = vector.clone()
        # Form the matrix before eviction when a batch introduces many sources.
        matrix = torch.stack([_CACHE[k] for k in keys])
        for key in keys:
            _CACHE.move_to_end(key)
        while len(_CACHE) > MAX_DOCS:
            _CACHE.popitem(last=False)
        query_vector = _encode([query], runtime)[0]
        scores = (matrix @ query_vector).tolist()
        if not all(isinstance(s,float) and -1.0001 <= s <= 1.0001 for s in scores):
            raise EncoderUnavailable('invalid_encoder_output')
    return sorted([{'source_id':sid,'cosine':round(max(-1,min(1,score)),6)}
                   for sid,score in zip(ids,scores)], key=lambda x:(-x['cosine'],x['source_id']))


def fuse(query, docs, lexical, limit):
    """RRF over separate lexical/semantic rank orders; no confidence claim."""
    semantic = rank(query, docs)
    by_id = {d['source_id']:d['source'] for d in docs}
    scores = {}; lexical_scores = {}
    for index, hit in enumerate(lexical,1):
        scores[hit['source_id']] = 1/(60+index)
        lexical_scores[hit['source_id']] = hit['score']
    semantic_scores = {}
    for index, hit in enumerate(semantic,1):
        sid = hit['source_id'];scores[sid] = scores.get(sid,0)+1/(60+index)
        semantic_scores[sid] = hit['cosine']
    return [{'source_id':sid,'source':by_id[sid],'score':round(score,9),
             'bm25_score':lexical_scores.get(sid,0),'cosine':semantic_scores[sid]}
            for sid,score in sorted(scores.items(),key=lambda x:(-x[1],x[0]))[:limit]]
