"""Single-device free-Colab TPU SFT with PEFT; no Drive mount, secrets or paid API."""
import os,json,math,time,random,hashlib
from pathlib import Path
os.environ.update(HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false',WANDB_DISABLED='true')
import torch
from importlib.metadata import version
from transformers import AutoModelForCausalLM,AutoTokenizer,set_seed
from peft import LoraConfig,get_peft_model,get_peft_model_state_dict
from safetensors.torch import save_file
BASE='Qwen/Qwen3-0.6B';REV='c1899de289a04d12100db370d81485cdf75e47ca'
SEED=107;STEPS=360;BATCH=8;LENGTH=256
ROOT=Path('/content/intentcart-training');OUT=ROOT/'run360';OUT.mkdir(parents=True,exist_ok=True)
set_seed(SEED);torch.set_num_threads(2);device=torch.device('tpu')
assert str(device).startswith('tpu'), 'TPU is required; refusing an unnoticed CPU run.'
tok=AutoTokenizer.from_pretrained(BASE,revision=REV,token=False,trust_remote_code=False);tok.pad_token=tok.eos_token
rows=[json.loads(x) for x in (ROOT/'training/data/train.jsonl').read_text().splitlines()]
samples=[]
for row in rows:
 prompt=tok.apply_chat_template([{'role':'system','content':row['system']},{'role':'user','content':row['input']}],tokenize=False,add_generation_prompt=True,enable_thinking=False)
 prefix=tok.encode(prompt,add_special_tokens=False);completion=tok.encode(row['output']+tok.eos_token,add_special_tokens=False)
 ids=prefix+completion;assert len(ids)<=LENGTH,(len(ids),row['kind'])
 samples.append((ids+([tok.pad_token_id]*(LENGTH-len(ids))),[-100]*len(prefix)+completion+[-100]*(LENGTH-len(ids)),[1]*len(ids)+[0]*(LENGTH-len(ids))))
model=AutoModelForCausalLM.from_pretrained(BASE,revision=REV,token=False,trust_remote_code=False,dtype=torch.bfloat16,attn_implementation='sdpa');model.config.use_cache=False
model=get_peft_model(model,LoraConfig(r=8,lora_alpha=16,lora_dropout=.05,target_modules=['q_proj','v_proj'],task_type='CAUSAL_LM'));model.to(device);model.train()
optimizer=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=3e-4,weight_decay=0)
manifest={'schema':'intentcart-trained-agent/1','base':BASE,'revision':REV,'license':'Apache-2.0','seed':SEED,'device':str(device),'hardware':os.environ.get('TPU_ACCELERATOR_TYPE','Colab v5e-1 selected'),'torch':torch.__version__,'torch_tpu':version('torch_tpu'),'steps_planned':STEPS,'batch':BATCH,'sequence_length':LENGTH,'method':'Completion-only supervised LoRA, r8 alpha16 q_proj/v_proj, bfloat16. Declared synthetic template and finite-expert supervision. No RL or human feedback.','total_parameters':sum(p.numel() for p in model.parameters()),'trainable_parameters':sum(p.numel() for p in model.parameters() if p.requires_grad),'dataset':json.loads((ROOT/'training/data/manifest.json').read_text()),'started':time.time()}
(OUT/'run.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(manifest),flush=True)
rng=random.Random(SEED);order=list(range(len(samples)));rng.shuffle(order);cursor=0;start=time.perf_counter()
def save(step):
 dest=OUT/'adapter';dest.mkdir(exist_ok=True)
 torch.accelerator.synchronize();weights={k:v.detach().cpu().contiguous() for k,v in get_peft_model_state_dict(model).items()};save_file(weights,str(dest/'adapter_model.safetensors'));model.peft_config['default'].save_pretrained(dest)
 (OUT/'progress.json').write_text(json.dumps({'completed_steps':step,'elapsed_seconds':time.perf_counter()-start,'adapter_sha256':hashlib.sha256((dest/'adapter_model.safetensors').read_bytes()).hexdigest()},indent=2))
for step in range(1,STEPS+1):
 if cursor+BATCH>len(order):rng.shuffle(order);cursor=0
 batch=[samples[i] for i in order[cursor:cursor+BATCH]];cursor+=BATCH
 ids,labels,mask=[torch.tensor([b[k] for b in batch],dtype=torch.long,device=device) for k in range(3)]
 optimizer.zero_grad(set_to_none=True)
 loss=model(input_ids=ids,attention_mask=mask,labels=labels).loss;loss.backward()
 torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad],1.)
 lr=3e-4*min(step/10,1.)*.5*(1+math.cos(math.pi*max(0,step-10)/(STEPS-10)))
 for group in optimizer.param_groups:group['lr']=lr
 optimizer.step()
 if step==1 or step%5==0:
  value=float(loss.detach().cpu());assert math.isfinite(value),'Non-finite loss; stop.'
  row={'step':step,'loss':value,'learning_rate':lr,'elapsed_seconds':time.perf_counter()-start};print(json.dumps(row),flush=True)
  with (OUT/'steps.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
 if step%60==0:save(step)
save(STEPS);manifest.update(completed_steps=STEPS,finished=time.time(),elapsed_seconds=time.perf_counter()-start);(OUT/'run.json').write_text(json.dumps(manifest,indent=2));print('TRAINING COMPLETE',flush=True)
import zipfile
with zipfile.ZipFile('/content/intentcart-trained-agent-360.zip','w',zipfile.ZIP_DEFLATED) as z:
 for p in OUT.rglob('*'):
  if p.is_file():z.write(p,str(p.relative_to(OUT)))
print('Adapter and evidence ready for download. No base weights or secrets in the archive.',flush=True)
