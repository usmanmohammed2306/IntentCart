// Visual state only. These units are illustrative and never product dimensions.
export const PARTS=['laptop','monitor','dock','power','cable'];
const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
export function freshLayout(){return {schema:1,finish:'graphite',light:'aurora',accent:'#72e6db',spread:false,parts:Object.fromEntries(PARTS.map(k=>[k,{position:[0,0,0],rotation:0,scale:1,color:null}]))};}
export function validateLayout(x){
 if(!x||x.schema!==1||!['sand','moss','graphite'].includes(x.finish)||!['aurora','studio','warm'].includes(x.light)||!/^#[0-9a-f]{6}$/i.test(x.accent)||typeof x.spread!=='boolean')throw Error('Unsupported layout.');
 const out=freshLayout();Object.assign(out,{finish:x.finish,light:x.light,accent:x.accent,spread:x.spread});
 for(const k of PARTS){const p=x.parts?.[k];if(!p||!Array.isArray(p.position)||p.position.length!==3||!p.position.every(Number.isFinite)||!Number.isFinite(p.rotation)||!Number.isFinite(p.scale)||p.color!==null&&!/^#[0-9a-f]{6}$/i.test(p.color))throw Error('Unsupported component transform.');
  if(p.position.some((n,i)=>n<[-2,0,-1.5][i]||n>[2,1.5,1.5][i])||p.scale<.65||p.scale>1.45||Math.abs(p.rotation)>Math.PI*2)throw Error('Component is outside the workspace.');out.parts[k]={position:[...p.position],rotation:p.rotation,scale:p.scale,color:p.color};}
 return out;
}
export function editLayout(layout,action){
 const out=validateLayout(layout),p=Object.hasOwn(out.parts,action.target)?out.parts[action.target]:null;
 if(action.op==='reset')return freshLayout();
 if(action.op==='finish'&&['sand','moss','graphite'].includes(action.value))out.finish=action.value;
 else if(action.op==='light'&&['aurora','studio','warm'].includes(action.value))out.light=action.value;
 else if(action.op==='spread')out.spread=true;
 else if(action.op==='assemble')out.spread=false;
 else if(action.op==='accent'&&/^#[0-9a-f]{6}$/i.test(action.value))out.accent=action.value;
 else if(p&&action.op==='color'&&(/^#[0-9a-f]{6}$/i.test(action.value)||action.value===null))p.color=action.value;
 else if(p&&action.op==='move'){
  const changes={left:[-.2,0,0],right:[.2,0,0],up:[0,.15,0],down:[0,-.15,0],forward:[0,0,.2],back:[0,0,-.2]}[action.value];if(!changes)throw Error('Choose a direction.');p.position=p.position.map((n,i)=>clamp(Math.round((n+changes[i])*100)/100,[-2,0,-1.5][i],[2,1.5,1.5][i]));
 }else if(p&&action.op==='rotate'&&['left','right'].includes(action.value))p.rotation=clamp(p.rotation+(action.value==='left'?-.2:.2),-Math.PI*2,Math.PI*2);
 else if(p&&action.op==='scale'&&['larger','smaller'].includes(action.value))p.scale=clamp(p.scale+(action.value==='larger'?.1:-.1),.65,1.45);
 else throw Error('This action is not available.');return validateLayout(out);
}
export function createHistory(initial=freshLayout()){
 let value=validateLayout(initial),undo=[],redo=[];
 return {get value(){return structuredClone(value);},get canUndo(){return !!undo.length;},get canRedo(){return !!redo.length;},set(next){next=validateLayout(next);if(JSON.stringify(next)===JSON.stringify(value))return false;undo.push(value);if(undo.length>40)undo.shift();redo=[];value=next;return true;},undo(){if(!undo.length)return false;redo.push(value);value=undo.pop();return true;},redo(){if(!redo.length)return false;undo.push(value);value=redo.pop();return true;},load(next){value=validateLayout(next);undo=[];redo=[];}};
}
