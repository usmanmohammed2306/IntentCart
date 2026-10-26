"""Install the pinned CPU runtime; scope native-build settings to this process.

On macOS, test the active toolchain and select a compatible *already installed*
SDK if its default cannot link. Never changes xcode-select or system settings.
"""
import argparse,os,platform,re,shlex,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def probe(sdk=None,environment=None):
 env=dict(os.environ if environment is None else environment)
 if sdk:env['SDKROOT']=str(sdk)
 with tempfile.TemporaryDirectory(prefix='intentcart-compiler-') as folder:
  folder=Path(folder)
  for variable,default,suffix,code in [('CC','clang','.c','int main(void){return 0;}'),('CXX','clang++','.cpp','#include <vector>\nint main(){std::vector<int> v(1);return v[0];}')]:
   compiler=shlex.split(env.get(variable,default));source=folder/('probe'+suffix);source.write_text(code);command=[*compiler,str(source),'-o',str(folder/'probe')]
   if sdk:command+=['-isysroot',str(sdk)]
   try:result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=30)
   except (OSError,subprocess.TimeoutExpired) as exc:return False,type(exc).__name__+': '+str(exc)
   if result.returncode:return False,result.stderr[-1200:]
 return True,''
def installed_sdks():
 roots=[Path('/Library/Developer/CommandLineTools/SDKs'),Path('/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs')];paths={p.resolve() for root in roots if root.is_dir() for p in root.glob('MacOSX*.sdk') if p.is_dir()}
 return sorted(paths,key=lambda p:tuple(map(int,re.findall(r'\d+',p.name))),reverse=True)
def build_environment(environment=None,system=None):
 env=dict(os.environ if environment is None else environment);env.setdefault('CMAKE_BUILD_PARALLEL_LEVEL','2');chosen=None
 # An explicitly chosen CUDA/Metal build remains the caller's choice. CPU is
 # the documented default; inference itself uses zero GPU layers.
 args=env.get('CMAKE_ARGS','')
 if 'GGML_METAL' not in args:args+=' -DGGML_METAL=OFF'
 if 'GGML_CUDA' not in args:args+=' -DGGML_CUDA=OFF'
 if (system or platform.system())=='Darwin':
  explicit=next((v.split('=',1)[1] for v in shlex.split(args) if v.startswith('-DCMAKE_OSX_SYSROOT=')),env.get('SDKROOT'))
  ok,error=probe(Path(explicit) if explicit else None,env)
  if not ok:
   if explicit:raise RuntimeError('The explicit SDKROOT cannot compile/link. Select a compatible installed SDK.\n'+error)
   for sdk in installed_sdks():
    if probe(sdk,env)[0]:chosen=sdk;break
   if chosen is None:raise RuntimeError('A working C/C++ toolchain is required. Install or repair official Xcode Command Line Tools.\n'+error)
   env['SDKROOT']=str(chosen)
   if 'CMAKE_OSX_SYSROOT' not in args:args+=' -DCMAKE_OSX_SYSROOT='+shlex.quote(str(chosen))
 env['CMAKE_ARGS']=args.strip();return env,chosen
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--dry-run',action='store_true');options=parser.parse_args()
 if sys.version_info[:2]!=(3,12):raise SystemExit('Use Python3.12 in a dedicated virtual environment.')
 env,sdk=build_environment();command=[sys.executable,'-m','pip','--isolated','install','--index-url','https://pypi.org/simple','--disable-pip-version-check','--no-input','-r',str(ROOT/'requirements.txt')]
 print('CPU runtime installation. SDK:',str(sdk) if sdk else 'active toolchain','; no system setting or paid service is changed.',flush=True)
 if not options.dry_run:subprocess.run(command,env=env,check=True)
if __name__=='__main__':main()
