"""Private, network-free document retrieval using Sentence Transformers/Qdrant.

Indexes contain only the explicitly supplied owned passages. No remote Qdrant,
query persistence, background indexing or model download is permitted here.
"""
from collections import OrderedDict
from functools import lru_cache
import hashlib
import re
import threading
from . import semantic

LOCK=threading.RLock()
CACHE=OrderedDict()
MAX_CHUNKS=96


def chunks(pages):
    from llama_index.core import Document
    from llama_index.core.node_parser import SentenceSplitter
    splitter=SentenceSplitter(chunk_size=160,chunk_overlap=24,tokenizer=lambda s:re.findall(r'\S+',s),chunking_tokenizer_fn=lambda s:re.split(r'(?<=[.!?。？！])\s+',s),include_metadata=False,include_prev_next_rel=False)
    result=[];seen=set()
    for page in pages:
        nodes=splitter.get_nodes_from_documents([Document(text=page['text'])],show_progress=False)
        for node in nodes:
            text=node.get_content().strip()
            if text:
                digest=hashlib.sha256((str(page['page'])+'\n'+text).encode()).hexdigest()
                if digest not in seen:
                    seen.add(digest);result.append({'id':digest[:24],'page':page['page'],'text':text[:6000]})
    if not result or len(result)>MAX_CHUNKS:raise ValueError('Use a shorter document with readable text.')
    return result


@lru_cache(maxsize=1)
def encoder(path,identity):
    # Validate the same pinned manifest before any framework model construction.
    semantic.load()
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.sentence_transformer.modules import Transformer,Pooling,Normalize
    transformer=Transformer(path,max_seq_length=256,model_kwargs={'local_files_only':True,'trust_remote_code':False,'use_safetensors':True},processor_kwargs={'local_files_only':True,'trust_remote_code':False})
    model=SentenceTransformer(modules=[transformer,Pooling(384,'mean'),Normalize()],device='cpu',local_files_only=True,trust_remote_code=False)
    model.eval()
    return model


def search(query,passages,limit=5):
    if type(query) is not str or not query.strip() or len(query)>1000 or type(limit) is not int or not 1<=limit<=6:
        raise ValueError('Enter a question of up to1000 characters.')
    if not 1<=len(passages)<=MAX_CHUNKS or len({p['id'] for p in passages})!=len(passages):
        raise ValueError('Invalid owned passage set.')
    directory=semantic.directory()
    if directory is None:raise ValueError('Local document search needs the reviewed encoder.')
    from qdrant_client import QdrantClient,models
    with LOCK:
        model=encoder(str(directory),semantic.configured_identity())
        keys=[hashlib.sha256(p['text'].encode()).hexdigest() for p in passages]
        missing=list(dict.fromkeys(k for k in keys if k not in CACHE));texts=dict(zip(keys,[p['text'] for p in passages]))
        for start in range(0,len(missing),16):
            batch=missing[start:start+16]
            vectors=model.encode([texts[k] for k in batch],batch_size=16,convert_to_numpy=True,normalize_embeddings=True,show_progress_bar=False,device='cpu')
            for key,vector in zip(batch,vectors):CACHE[key]=vector.tolist()
        vectors=[CACHE[k] for k in keys]
        for key in keys:CACHE.move_to_end(key)
        while len(CACHE)>256:CACHE.popitem(last=False)
        vector=model.encode([query],convert_to_numpy=True,normalize_embeddings=True,show_progress_bar=False,device='cpu')[0].tolist()
        client=QdrantClient(':memory:')
        try:
            client.create_collection('owned',vectors_config=models.VectorParams(size=384,distance=models.Distance.COSINE))
            client.upsert('owned',points=[models.PointStruct(id=i,vector=v,payload={'passage_id':p['id']}) for i,(p,v) in enumerate(zip(passages,vectors))])
            matches=client.query_points('owned',query=vector,limit=min(limit,len(passages)),with_payload=True).points
            by_id={p['id']:p for p in passages}
            rows=[{**by_id[m.payload['passage_id']],'score':round(m.score,6)} for m in matches]
            return {'method':'Sentence Transformers CPU embeddings + exact local Qdrant cosine search','hits':rows,'notice':'Passages from your file, not verified product facts. Similarity is not confidence. No query or file was sent to a model service.'}
        finally:client.close()
