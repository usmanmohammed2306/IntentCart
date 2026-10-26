"""Required task-trained local language model. No silent policy fallback.

A generated bounded instruction is a proposal; validators retain tool authority.
Only the configured public base and hash-bound safetensors adapter are loaded.
"""
import hashlib,json,os,re,threading,time,uuid,copy
from collections import OrderedDict
from pathlib import Path
ROOT=Path(__file__).parent
SYSTEM='You are IntentCart. Translate the request into one permitted workspace instruction. Output only the instruction. Never approve purchases, software installation, accounts or secrets. Unknown requests output clarify.'
POLICY='You are IntentCart investigator. Read the observed state and choose exactly one tool: search, inspect, clarify, recommend, defer. Search before inspecting. Ask unresolved software permission only when needed. Inspect unresolved decision-relevant facts before recommending. Never invent evidence or grant permission.'
PARTS=('laptop','monitor','dock','power','cable')
_lock=threading.Lock();_model=None;_tokenizer=None;_identity=None;_serving=None;_serving_sha=None
_policy_cache=OrderedDict()
POLICY_CACHE_LIMIT=256
POLICY_CACHE_TTL=900
class ModelError(ValueError):pass

def paths():
 return Path(os.getenv('INTENTCART_MODEL_HOME',str(ROOT/'data/trained-agent/base'))),ROOT/'data/trained-agent/adapter',ROOT/'data/trained-agent/manifest.json'
def device():
 value=os.getenv('INTENTCART_MODEL_DEVICE','cpu')
 if value not in ('cpu','mps'):raise ModelError('Only local CPU or explicitly selected Apple MPS is supported.')
 return value

def _read_identity():
 base,adapter,manifest=paths()
 try:
  m=json.loads(manifest.read_text());weights=adapter/'adapter_model.safetensors'
  if m['completed_steps']<1 or m['base']!='Qwen/Qwen3-0.6B' or not weights.is_file():raise ValueError()
  if hashlib.sha256(weights.read_bytes()).hexdigest()!=m['adapter_sha256']:raise ValueError()
  if device()=='cpu':
   serving=json.loads((ROOT/'data/trained-agent/serving.json').read_text());f=base/'workspace-q8.gguf'
   if serving.get('schema')!='intentcart-trained-serving/1' or serving.get('format')!='Q8_0' or not re.fullmatch('[a-f0-9]{64}',serving.get('gguf_sha256','')):raise ValueError()
   if serving['adapter_sha256']!=m['adapter_sha256'] or serving['base_revision']!=m['revision'] or f.stat().st_size!=serving['bytes']:raise ValueError()
   m['serving_sha256']=serving['gguf_sha256']
  for name,digest in m['base_files'].items():
   if device()=='cpu' and name=='model.safetensors':continue
   path=base/name
   if not path.is_file() or path.stat().st_size!=digest['bytes']:raise ValueError()
  return m
 except (OSError,ValueError,KeyError,TypeError):raise ModelError('The trained agent is not installed or its artifact is invalid. Run the documented model setup; no baseline was substituted.') from None

_identity_verified_key=None
_identity_verified_value=None
_identity_layout_key=None
_identity_layout_paths=None
_identity_verification_lock=threading.RLock()
def _stamp(path):
 st=os.stat(path);return (path,st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
def identity():
 """Cache checksum results only while all artifact metadata remains unchanged.
 Manifest, inode, size, mtime and ctime are checked; changed files revalidate.
 """
 global _identity_verified_key,_identity_verified_value,_identity_layout_key,_identity_layout_paths
 base,adapter,manifest=paths();target=device();manifest_path=str(manifest)
 try:
  manifest_stamp=_stamp(manifest_path);layout_key=(str(base),target,manifest_stamp)
  with _identity_verification_lock:
   if layout_key!=_identity_layout_key:
    metadata=json.loads(manifest.read_text());files=[str(adapter/'adapter_model.safetensors')]
    if target=='cpu':files += [str(ROOT/'data/trained-agent/serving.json'),str(base/'workspace-q8.gguf')]
    files += [str(base/name) for name in metadata['base_files'] if not(target=='cpu' and name=='model.safetensors')]
    _identity_layout_key=layout_key;_identity_layout_paths=tuple(files)
   key=(layout_key,tuple(_stamp(f) for f in _identity_layout_paths))
   if key!=_identity_verified_key or _identity_verified_value is None:
    verified=_read_identity();_identity_verified_key=key;_identity_verified_value=verified
   return copy.deepcopy(_identity_verified_value)
 except (OSError,ValueError,KeyError,TypeError):return _read_identity()

def status():
 try:
  m=identity();return {'ready':True,'model':'IntentCart Workspace Agent','base':m['base'],'adapter_sha256':m['adapter_sha256'],'completed_steps':m['completed_steps'],'external_requests':False,'training':'Supervised LoRA on authored synthetic examples; limited workstation scope.'}
 except ModelError as exc:return {'ready':False,'notice':str(exc),'external_requests':False}

def _load():
 global _model,_tokenizer,_identity,_serving,_serving_sha
 if _model is not None:return
 from transformers import AutoTokenizer
 base,adapter,_=paths();m=identity();target=device()
 for name,entry in m['base_files'].items():
  if target=='cpu' and name=='model.safetensors':continue
  h=hashlib.sha256()
  with (base/name).open('rb') as f:
   for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
  if h.hexdigest()!=entry['sha256']:raise ModelError('Public tokenizer/base checksum failed. No model was loaded.')
 _tokenizer=AutoTokenizer.from_pretrained(base,local_files_only=True,trust_remote_code=False)
 if target=='cpu':
  from llama_cpp import Llama
  import atexit
  weights=base/'workspace-q8.gguf';h=hashlib.sha256()
  with weights.open('rb') as f:
   for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
  if h.hexdigest()!=m['serving_sha256']:raise ModelError('Trained CPU artifact checksum failed. No model was loaded.')
  threads=max(1,min(4,int(os.getenv('INTENTCART_MODEL_THREADS','1'))))
  model=Llama(model_path=str(weights),n_ctx=512,n_batch=128,n_threads=threads,n_threads_batch=threads,n_gpu_layers=0,verbose=False,seed=107)
  atexit.register(model.close);_serving='llama.cpp CPU Q8_0, merged trained LoRA; GPU layers disabled';_serving_sha=m['serving_sha256']
 else:
  import torch
  from transformers import AutoModelForCausalLM
  from peft import PeftModel
  torch.set_num_threads(max(1,min(4,int(os.getenv('INTENTCART_MODEL_THREADS','2')))))
  model=AutoModelForCausalLM.from_pretrained(base,local_files_only=True,trust_remote_code=False,dtype=torch.bfloat16,attn_implementation='sdpa')
  model=PeftModel.from_pretrained(model,adapter,local_files_only=True,is_trainable=False).to('mps');model.eval();_serving='Apple MPS bfloat16 with trained PEFT adapter';_serving_sha=None
 _model=model;_identity=m['adapter_sha256']

def generate(text,system=SYSTEM,max_tokens=40):
 if not isinstance(text,str) or not 1<=len(text)<=1200:raise ModelError('Use a short workspace request, up to 1,200 characters.')
 if not _lock.acquire(blocking=False):raise ModelError('The agent is helping with another request. Try again in a moment.')
 try:
  request_start=time.perf_counter();cold=_model is None
  current=identity()
  if _model is not None and (_identity!=current['adapter_sha256'] or _serving_sha!=current.get('serving_sha256')):raise ModelError('Model identity changed while loaded. Restart before generating or reusing a decision.')
  cache_key=None
  if system==POLICY and max_tokens==8 and os.getenv('INTENTCART_POLICY_CACHE','on')=='on':
   try:
    state=json.loads(text)
    keys={'discovered','decision_facts_missing','software_candidate','software_answered','supported_basket','remaining_steps','budget_cents'}
    if set(state)==keys and all(isinstance(v,(bool,int)) for v in state.values()):
     canonical=json.dumps(state,sort_keys=True,separators=(',',':'));cache_key=hashlib.sha256(json.dumps([canonical,system,max_tokens,current['adapter_sha256'],current.get('serving_sha256'),device(),107],separators=(',',':')).encode()).hexdigest()
   except (ValueError,TypeError):pass
  now=time.monotonic()
  if cache_key in _policy_cache:
   saved=_policy_cache.pop(cache_key)
   if now-saved['created']<=POLICY_CACHE_TTL:
    _policy_cache[cache_key]=saved;receipt=dict(saved['receipt']);receipt.update(cache_hit=True,inference_performed=False,generated_tokens=0,reused_generated_tokens=saved['receipt']['generated_tokens'],cold_start_ms=0,latency_ms=round((time.perf_counter()-request_start)*1000,2));return saved['raw'],receipt
  _load();start=time.perf_counter();cold_ms=round((start-request_start)*1000,2) if cold else 0
  prompt=_tokenizer.apply_chat_template([{'role':'system','content':system},{'role':'user','content':text}],tokenize=False,add_generation_prompt=True,enable_thinking=False)
  if device()=='cpu':
   tokens=_model.tokenize(prompt.encode('utf-8'),add_bos=False,special=True)
   if len(tokens)>256:raise ModelError('Please shorten the request so the agent can review all of it.')
   out=_model.create_completion(prompt=tokens,max_tokens=max_tokens,temperature=0,repeat_penalty=1,seed=107,stop=['<|im_end|>'])
   raw=out['choices'][0]['text'].strip();generated=out['usage']['completion_tokens']
  else:
   import torch
   inputs=_tokenizer(prompt,return_tensors='pt')
   if inputs.input_ids.shape[1]>256:raise ModelError('Please shorten the request so the agent can review all of it.')
   inputs={k:v.to(_model.device) for k,v in inputs.items()}
   with torch.inference_mode():out=_model.generate(**inputs,max_new_tokens=max_tokens,do_sample=False,use_cache=True,pad_token_id=_tokenizer.eos_token_id)
   raw=_tokenizer.decode(out[0,inputs['input_ids'].shape[1]:],skip_special_tokens=True).strip();generated=out.shape[1]-inputs['input_ids'].shape[1]
  receipt={'model_id':'intentcart-qwen3-0.6b-lora','adapter_sha256':_identity,'serving_sha256':_serving_sha,'latency_ms':round((time.perf_counter()-start)*1000,2),'cold_start_ms':cold_ms,'generated_tokens':generated,'external_requests':0,'reserved_microusd':0,'serving':_serving,'cache_hit':False,'inference_performed':True,'decision_id':uuid.uuid4().hex}
  if cache_key and raw in ('search','inspect','clarify','recommend','defer'):
   _policy_cache[cache_key]={'raw':raw,'receipt':dict(receipt),'created':time.monotonic()}
   while len(_policy_cache)>POLICY_CACHE_LIMIT:_policy_cache.popitem(last=False)
  return raw,receipt
 except ModelError:raise
 except Exception as exc:raise ModelError('The trained agent could not complete this request. Nothing was changed; no fallback or external request was sent.') from exc
 finally:_lock.release()

def request(text,kind):
 from . import agent
 raw,receipt=generate(text);words=raw.split();result={'kind':'clarify','message':'Try a workspace change, such as “move the dock left”, or describe your laptop, screens and budget.','receipt':receipt}
 if not words:return result
 op=words[0]
 if op=='plan' and len(words)==7:
  try:
   goal={'displays':int(words[1]),'budget_cents':round(float(words[2])*100),'laptop_id':words[3],'height':int(words[4]),'hz':int(words[5]),'reuse_monitor':{'true':True,'false':False}[words[6]],'allow_driver':False}
   validated=agent.goal_for(goal,kind,agent.catalog_for(kind))
   return {'kind':'plan','suggestions':validated.model_dump(),'review_required':True,'receipt':receipt}
  except (ValueError,KeyError,TypeError):return result
 if op in ('undo','redo','reset','spread','assemble') and len(words)==1:return {'kind':'scene','action':{'op':op},'receipt':receipt}
 if op in ('finish','light') and len(words)==2 and words[1] in ({'sand','moss','graphite'} if op=='finish' else {'aurora','studio','warm'}):return {'kind':'scene','action':{'op':op,'value':words[1]},'receipt':receipt}
 if op=='screens' and len(words)==2 and words[1] in ('1','2','3','4'):
  if kind=='fixture' and int(words[1])>2:return result
  return {'kind':'requirements','displays':int(words[1]),'review_required':True,'receipt':receipt}
 if op in ('move','rotate','scale') and len(words)==3 and words[1] in PARTS and words[2] in ({'left','right','forward','back','up','down'} if op=='move' else {'left','right'} if op=='rotate' else {'larger','smaller'}):return {'kind':'scene','action':{'op':op,'target':words[1],'value':words[2]},'receipt':receipt}
 return result

def policy(record):
 from . import agent,missions,workbench
 cat=workbench.catalog(record);result=agent.solve(record)
 useful=[i for i in result['investigations'] if i['could_improve_cost']]
 software=any(p['kind']=='dock' and p['id'] not in record['excluded'] and missions.fact(p,'protocol',record['inspected'],catalog=cat)['value']=='displaylink' for p in cat['products'])
 state={'discovered':bool(record['discovered']),'decision_facts_missing':min(9,len(useful)),'software_candidate':software,'software_answered':record['goal']['allow_driver'] or record.get('driver_answered') is not None,'supported_basket':bool(result['plan']),'remaining_steps':max(0,agent.MAX_STEPS-record['tool_count']),'budget_cents':record['goal']['budget_cents']}
 raw,receipt=generate(json.dumps(state,separators=(',',':')),POLICY,8)
 if raw not in ('search','inspect','clarify','recommend','defer'):raise ModelError('The trained agent returned an unsupported tool. No action was applied.')
 target=''
 if raw=='inspect':
  if not useful:raise ModelError('The agent requested an unavailable inspection. No action was applied.')
  target=useful[0]['source_ids'][0]
 if raw=='clarify':target='allow_driver'
 if raw=='recommend':
  if not result['plan']:raise ModelError('The agent requested an unsupported recommendation. No action was applied.')
  target=result['plan']['id']
 return agent.Action(action=raw,target=target,reason='Task-trained local model selected this tool; the evidence validator controls execution.'),receipt
