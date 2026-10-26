"""Paired greedy base/adapter evaluation on frozen authored phrase families.

Run on held-out files without generating labels from evaluated model output.
Exact-match rates measure this small task family, not general reasoning quality.
"""
import argparse,json,time,os,hashlib
from pathlib import Path
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TOKENIZERS_PARALLELISM='false',HF_HUB_DISABLE_TELEMETRY='1')
import torch
from transformers import AutoModelForCausalLM,AutoTokenizer
from peft import PeftModel
ROOT=Path(__file__).resolve().parent

def main():
 p=argparse.ArgumentParser();p.add_argument('--base',required=True);p.add_argument('--adapter',required=True);p.add_argument('--split',choices=['dev','test'],default='dev');p.add_argument('--out',required=True);p.add_argument('--base-report');a=p.parse_args()
 torch.set_num_threads(2);torch.mps.set_per_process_memory_fraction(.4)
 tok=AutoTokenizer.from_pretrained(a.base,local_files_only=True);tok.padding_side='left';tok.pad_token=tok.eos_token
 model=AutoModelForCausalLM.from_pretrained(a.base,local_files_only=True,trust_remote_code=False,dtype=torch.bfloat16,attn_implementation='sdpa')
 model=PeftModel.from_pretrained(model,a.adapter,is_trainable=False);model.to('mps');model.eval();model.config.use_cache=True
 data=[json.loads(x) for x in (ROOT/'data'/f'{a.split}.jsonl').read_text().splitlines()];results=[];start=time.perf_counter()
 cached=json.loads(Path(a.base_report).read_text()) if a.base_report else None
 if cached:
  assert cached['split']==a.split and cached['dataset_sha256']==hashlib.sha256((ROOT/'data'/f'{a.split}.jsonl').read_bytes()).hexdigest();results.extend(r for r in cached['results'] if r['model']=='base')
 for label in (['trained'] if cached else ['base','trained']):
  for kind in ['command','intake','policy']:
   rows=[r for r in data if r['kind']==kind]
   for offset in range(0,len(rows),4):
    batch=rows[offset:offset+4];texts=[tok.apply_chat_template([{'role':'system','content':r['system']},{'role':'user','content':r['input']}],tokenize=False,add_generation_prompt=True,enable_thinking=False) for r in batch]
    inputs=tok(texts,return_tensors='pt',padding=True).to('mps');t=time.perf_counter()
    with torch.inference_mode():
     if label=='base':
      with model.disable_adapter():output=model.generate(**inputs,do_sample=False,max_new_tokens=40 if kind=='intake' else 12,pad_token_id=tok.eos_token_id)
     else:output=model.generate(**inputs,do_sample=False,max_new_tokens=40 if kind=='intake' else 12,pad_token_id=tok.eos_token_id)
    decoded=tok.batch_decode(output[:,inputs.input_ids.shape[1]:],skip_special_tokens=True)
    for row,pred in zip(batch,decoded):results.append({'model':label,'kind':kind,'input':row['input'],'expected':row['output'],'predicted':pred.strip(),'exact':pred.strip()==row['output'],'batch_latency_seconds':time.perf_counter()-t})
   print(json.dumps({'model':label,'kind':kind,'correct':sum(r['exact'] for r in results if r['model']==label and r['kind']==kind),'n':len(rows)}),flush=True)
 summary={label:{kind:{'correct':sum(r['exact'] for r in results if r['model']==label and r['kind']==kind),'n':sum(r['model']==label and r['kind']==kind for r in results)} for kind in ['command','intake','policy']} for label in ['base','trained']}
 report={'schema':'intentcart-trained-evaluation/1','split':a.split,'dataset_sha256':hashlib.sha256((ROOT/'data'/f'{a.split}.jsonl').read_bytes()).hexdigest(),'adapter_sha256':hashlib.sha256((Path(a.adapter)/'adapter_model.safetensors').read_bytes()).hexdigest(),'device':'Apple M5 MPS; evaluation only, TPU training recorded separately','cached_base_report':a.base_report,'decoding':'paired identical prompts, greedy, same token limits, no grammar constraints or retry','elapsed_seconds':time.perf_counter()-start,'summary':summary,'results':results,'limits':'Authored template-family holdout. Finite-policy teacher is declared. No human utility, independent test source, broad reasoning, production traffic or hardware speed comparison claimed.'}
 Path(a.out).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(summary),flush=True)
if __name__=='__main__':main()
