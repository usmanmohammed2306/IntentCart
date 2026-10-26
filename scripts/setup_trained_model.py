"""Explicit, pinned local build of the required task-trained CPU model."""
import argparse,hashlib,json,os,shutil,subprocess,sys,tarfile,tempfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SDIST_URL='https://files.pythonhosted.org/packages/ec/e9/e7de2b0463ea3ffbf0ede6cb21b58c1258a8f6521aae45ca773a59fe7cf3/llama_cpp_python-0.3.36.tar.gz'
SDIST_SHA='832db0699007f1be95a7e41ef12e88926b02ba836461e36a36372db2760c1a2e'
def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def verify(base,manifest):
 for name,entry in manifest['base_files'].items():
  if Path(name).name!=name:raise ValueError('Unsafe manifest path.')
  f=base/name
  if f.stat().st_size!=entry['bytes'] or digest(f)!=entry['sha256']:raise ValueError('Pinned base verification failed: '+name)
def merge_model(base,merged):
 import torch
 from transformers import AutoModelForCausalLM,AutoTokenizer
 from peft import PeftModel
 torch.set_num_threads(1)
 model=AutoModelForCausalLM.from_pretrained(base,local_files_only=True,trust_remote_code=False,dtype=torch.float32)
 model=PeftModel.from_pretrained(model,ROOT/'intentcart/data/trained-agent/adapter',local_files_only=True,is_trainable=False)
 model=model.merge_and_unload().to(torch.float16);model.save_pretrained(merged,safe_serialization=True,max_shard_size='2GB')
 tokenizer=AutoTokenizer.from_pretrained(base,local_files_only=True,trust_remote_code=False);tokenizer.save_pretrained(merged)
 for name in ('vocab.json','merges.txt'):shutil.copy2(base/name,merged/name)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,default=ROOT/'intentcart/data/trained-agent/base');p.add_argument('--base-directory',type=Path,help='Reuse a local pinned base after full checksum verification.');a=p.parse_args();target=a.directory.resolve();target.mkdir(parents=True,exist_ok=True)
 m=json.loads((ROOT/'intentcart/data/trained-agent/manifest.json').read_text());serving=json.loads((ROOT/'intentcart/data/trained-agent/serving.json').read_text());adapter=ROOT/'intentcart/data/trained-agent/adapter';assert m['base']=='Qwen/Qwen3-0.6B' and m['license']=='Apache-2.0'
 if digest(adapter/'adapter_model.safetensors')!=m['adapter_sha256'] or serving['adapter_sha256']!=m['adapter_sha256']:raise ValueError('Task adapter verification failed.')
 with tempfile.TemporaryDirectory(prefix='intentcart-model-build-') as temp:
  work=Path(temp);base=a.base_directory.resolve() if a.base_directory else work/'base'
  if not a.base_directory:
   from huggingface_hub import snapshot_download
   snapshot_download(repo_id=m['base'],revision=m['revision'],local_dir=str(base),allow_patterns=list(m['base_files']),token=False)
  verify(base,m)
  os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_IMPLICIT_TOKEN='1')
  merged=work/'merged'
  subprocess.run([sys.executable,str(Path(__file__).resolve()),'--merge-child',str(base),str(merged)],check=True)
  archive=work/'source.tar.gz'
  with urllib.request.urlopen(SDIST_URL,timeout=60) as response,archive.open('wb') as f:
   total=0
   while chunk:=response.read(1024*1024):
    total+=len(chunk)
    if total>80*1024*1024:raise ValueError('Converter archive exceeded its bounded size.')
    f.write(chunk)
  if digest(archive)!=SDIST_SHA:raise ValueError('Converter checksum failed.')
  with tarfile.open(archive) as t:t.extractall(work/'source',filter='data')
  converter=work/'source/llama_cpp_python-0.3.36/vendor/llama.cpp/convert_hf_to_gguf.py';out=work/'workspace-q8.gguf'
  subprocess.run([sys.executable,str(converter),str(merged),'--outtype','q8_0','--outfile',str(out),'--model-name','IntentCart Workspace Agent'],check=True)
  if out.stat().st_size!=serving['bytes'] or digest(out)!=serving['gguf_sha256']:raise ValueError('CPU conversion differs from the qualified artifact. Nothing was installed; retain the failure for review.')
  for name in m['base_files']:
   if name!='model.safetensors':shutil.copy2(base/name,target/name)
  shutil.copy2(out,target/'.workspace-q8.gguf.part');os.replace(target/'.workspace-q8.gguf.part',target/'workspace-q8.gguf')
 print('Task-trained CPU Q8 artifact and tokenizer verified. Runtime is offline; no provider key, paid API, GPU or training job was used.')
if __name__=='__main__':
 if len(sys.argv)==4 and sys.argv[1]=='--merge-child':merge_model(Path(sys.argv[2]),Path(sys.argv[3]))
 else:main()
