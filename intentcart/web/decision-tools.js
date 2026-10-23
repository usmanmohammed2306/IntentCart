// Read-only finite-option decision tools. No external requests or payment authority.
export const tools=[];
const kinds=['dock','monitor','cable','power'];
const dims=['no_driver','charging_capacity','dock_refresh_capacity'];
const copy=v=>JSON.parse(JSON.stringify(v));
function check(ok,message){if(!ok)throw Error(message);}
function int(v,min=0,max=300000){check(Number.isSafeInteger(v)&&v>=min&&v<=max,'Enter a bounded whole number.');return v;}
function num(v,min=0,max=100000){check(Number.isFinite(v)&&v>=min&&v<=max,'Enter a bounded finite number.');return v;}
const sum=a=>a.reduce((s,v)=>s+v,0);
const usd=n=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(n/100);
const cents=v=>Math.round(num(Number(v),0,3000)*100);
const basisPoints=v=>{num(v,0,100);const n=Math.round(v*100);check(Math.abs(v*100-n)<1e-8,'Use at most two decimal places for percentages.');return n;};
const signed=n=>(n<0?'-':'+')+usd(Math.abs(n));
const cell=v=>typeof v==='string'?v:JSON.stringify(v);
const output=(columns,rows,notes=[])=>({columns,rows,notes});
function choice(s,id){const row=s.options.find(o=>o.id===id);check(row,'Choose a supported setup from this snapshot.');return row;}
function ids(v){check(typeof v==='string'&&v.length<=500,'Product list is too long.');return [...new Set(v.split(',').map(x=>x.trim()).filter(Boolean))];}
function selected(s,id){const p=s.products.find(p=>p.id===id);check(p,'Choose an exact product in this snapshot.');return p;}
function parts(s,o){return o.items.map(i=>({...selected(s,i.product_id),quantity:i.quantity,line_cents:selected(s,i.product_id).price_cents*i.quantity}));}
const sub=(s,o)=>sum(parts(s,o).map(p=>p.line_cents));
const distance=(s,a,b)=>kinds.filter(k=>JSON.stringify(parts(s,a).filter(p=>p.kind===k).map(p=>[p.id,p.quantity]).sort())!==JSON.stringify(parts(s,b).filter(p=>p.kind===k).map(p=>[p.id,p.quantity]).sort())).length;
const sortCost=a=>[...a].sort((x,y)=>x.total_cents-y.total_cents||x.id.localeCompare(y.id));
const pick=(s,id)=>choice(s,id||s.options[0]?.id);
function add(id,title,group,description,inputs,run){tools.push({id,title,group,description,inputs,run});}
export function snapshot(task){
 check(task&&Number.isSafeInteger(task.revision)&&task.revision>0&&task.workbench?.revision===task.revision,'Refresh the current task.');
 const w=task.workbench;check(Array.isArray(w.products)&&w.products.length<=24&&Array.isArray(w.configurations)&&w.configurations.length<=12,'Snapshot exceeds finite limits.');
 const products=w.products.map(p=>({id:String(p.id),name:String(p.name).slice(0,200),variant:String(p.variant||p.id).slice(0,200),kind:p.kind,price_cents:int(p.price_cents)}));
 check(new Set(products.map(p=>p.id)).size===products.length,'Duplicate product identity.');
 const options=w.configurations.map(o=>{check(o.checks&&Object.keys(o.checks).length&&Object.values(o.checks).every(v=>v===true),'Only supported options are admitted.');check(Array.isArray(o.items)&&o.items.length<=8&&o.items.length>0,'Invalid component list.');const items=o.items.map(i=>({product_id:String(i.product_id),quantity:int(i.quantity,1,8)}));check(new Set(items.map(i=>i.product_id)).size===items.length,'Duplicate basket item.');for(const i of items)check(products.some(p=>p.id===i.product_id&&kinds.includes(p.kind)),'Unknown component.');const contributions=Object.fromEntries(['lower_cost',...dims].map(k=>[k,num(o.contributions?.[k],0,1)]));const total=int(o.total_cents);check(total>=sum(items.map(i=>products.find(p=>p.id===i.product_id).price_cents*i.quantity)),'Invalid all-in price.');return {id:String(o.id),items,total_cents:total,changed_slots:copy(o.changed_slots||[]),contributions};});
 check(new Set(options.map(o=>o.id)).size===options.length,'Duplicate setup identity.');
 const evidence=(task.evidence||[]);check(Array.isArray(evidence)&&evidence.length<=256,'Too many source fields.');
 const sources=evidence.map(e=>({id:String(e.source_id),product_id:String(e.product_id),field:String(e.field),value:copy(e.value??null),unit:String(e.unit||''),kind:String(e.kind||'fictional'),url:typeof e.url==='string'?e.url:null,observed_on:e.observed_at||e.observed_on||null,freshness:copy(w.sources?.find(x=>x.source_id===e.source_id)?.freshness||{status:'not reported',age_days:null})}));
 const history=task.history||[];check(Array.isArray(history)&&history.length<=1000,'History exceeds review limit.');
 const s={schema:'intentcart-decision-snapshot/1',revision:task.revision,catalog_sha256:String(w.catalog_sha256),source_sha256:String(task.source_sha256),budget_cents:int(task.goal.budget_cents),evidence_max_age_days:int(w.requirements.evidence_max_age_days,1,3650),products,options,sources,history:history.slice(-48).map(h=>({a:String(h.a),b:String(h.b),choice:String(h.choice)}))};
 for(const o of options)check(o.total_cents<=s.budget_cents,'An unsupported over-budget setup cannot be analyzed.');
 return s;
}
export function runTool(id,task,input={}){const tool=tools.find(t=>t.id===id);check(tool,'Unknown decision tool.');const s=snapshot(task);check(s.options.length>0,'No supported options in this snapshot. Resolve requirements or evidence first.');const before=JSON.stringify(s);const result=tool.run(s,input);check(JSON.stringify(s)===before,'A decision tool must not mutate the snapshot.');check(Array.isArray(result.columns)&&Array.isArray(result.rows)&&result.rows.length<=600,'Invalid analysis output.');return {tool:id,title:tool.title,revision:s.revision,catalog_sha256:s.catalog_sha256,scope:`Only the ${s.options.length} returned supported options in this loaded revision; hypothetical inputs do not change support, prices, preference answers or approval.`,...result,checkout_supported:false};}
const optionInput={name:'setup',label:'Starting setup',type:'setup'};
const productInput={name:'product',label:'Exact product',type:'product'};
const moneyInput=(name,label,value)=>({name,label,type:'number',min:0,max:3000,step:.01,value});
const countInput=(name,label,value,min=1,max=100)=>({name,label,type:'number',min,max,step:1,value});

const percentInput=(name,label,value)=>({name,label,type:'number',min:0,max:100,step:.01,value});

add("budget-frontier","Budget coverage staircase","Cost planning","See which returned setups remain affordable at each budget step; no plan is recomputed.",[moneyInput('budget','Hypothetical budget, USD',350)],function(s,i){
 const budget=cents(i.budget);const levels=[...new Set([0,...s.options.map(o=>o.total_cents),budget])].sort((a,b)=>a-b);return output(['Budget','Affordable options','Cheapest option','Your threshold'],levels.map(b=>{const a=sortCost(s.options.filter(o=>o.total_cents<=b));return [usd(b),a.length,a[0]?.id||'None',b===budget?'Your input':'Breakpoint'];}));
});

add("extra-cost-cap","Tax and shipping allowance","Cost planning","Find the maximum combined extra costs each supported basket can absorb within your hypothetical budget.",[moneyInput('budget','Hypothetical budget, USD',350)],function(s,i){
 const budget=cents(i.budget);return output(['Setup','Hardware subtotal','Maximum extras','Fits before extras'],s.options.map(o=>{const subtotal=sub(s,o);return [o.id,usd(subtotal),budget>=subtotal?usd(budget-subtotal):'None',budget>=subtotal?'Yes':'No'];}));
});

add("spend-exposure","Component spend exposure","Cost planning","Identify which component categories account for the largest share of one complete basket.",[optionInput],function(s,i){
 const o=pick(s,i.setup),p=parts(s,o),rows=kinds.map(k=>[k,sum(p.filter(x=>x.kind===k).map(x=>x.line_cents))]);rows.push(['Tax and shipping',o.total_cents-sub(s,o)]);return output(['Category','Spend','Share of total'],rows.sort((a,b)=>b[1]-a[1]).map(([k,v])=>[k,usd(v),o.total_cents?(100*v/o.total_cents).toFixed(2)+'%':'0%']));
});

add("product-outage","Single-product outage recovery","Availability","Find the least disruptive returned fallback when one exact product is unavailable.",[optionInput,productInput],function(s,i){
 const base=pick(s,i.setup);selected(s,i.product);const a=s.options.filter(o=>!o.items.some(p=>p.product_id===i.product)).sort((a,b)=>distance(s,base,a)-distance(s,base,b)||a.total_cents-b.total_cents);return output(['Fallback','Changed slots','All-in cost','Difference'],a.map(o=>[o.id,distance(s,base,o),usd(o.total_cents),signed(o.total_cents-base.total_cents)]),['Returned options only; absence of a fallback is not proof that the entire catalog is infeasible.']);
});
