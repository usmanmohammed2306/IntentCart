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

add("correlated-outage","Correlated stock-out stress","Availability","Remove up to four products together and inspect surviving complete baskets.",[{name:'products',label:'Unavailable product IDs, comma separated',type:'text',value:''}],function(s,i){
 const banned=ids(i.products);check(banned.length>0&&banned.length<=4,'Choose one to four exact product IDs.');banned.forEach(id=>selected(s,id));const a=sortCost(s.options.filter(o=>!o.items.some(p=>banned.includes(p.product_id))));return output(['Surviving setup','All-in total','Unavailable products'],a.map(o=>[o.id,usd(o.total_cents),banned.join(', ')]),['Correlated what-if over returned options, not live stock monitoring.']);
});

add("dock-resilience","Dock dependency resilience matrix","Availability","Stress every represented dock independently and see the fallback cost for your starting setup.",[optionInput],function(s,i){
 const base=pick(s,i.setup),docks=s.products.filter(p=>p.kind==='dock'&&s.options.some(o=>o.items.some(x=>x.product_id===p.id)));return output(['Unavailable dock','Survivors','Least-change fallback','Cost difference'],docks.map(p=>{const a=s.options.filter(o=>!o.items.some(x=>x.product_id===p.id)).sort((a,b)=>distance(s,base,a)-distance(s,base,b)||a.total_cents-b.total_cents);return [p.name,a.length,a[0]?.id||'None',a[0]?signed(a[0].total_cents-base.total_cents):'No represented fallback'];}));
});

add("diverse-shortlist","Diversified three-setup shortlist","Availability","Choose three returned options that maximize their minimum component-slot distance, then minimize combined price.",[],function(s,i){
 check(s.options.length>=3,'At least three supported options are needed.');let best=null;for(let a=0;a<s.options.length;a++)for(let b=a+1;b<s.options.length;b++)for(let c=b+1;c<s.options.length;c++){const set=[s.options[a],s.options[b],s.options[c]],spread=Math.min(distance(s,set[0],set[1]),distance(s,set[0],set[2]),distance(s,set[1],set[2])),cost=sum(set.map(o=>o.total_cents));if(!best||spread>best.spread||spread===best.spread&&cost<best.cost)best={set,spread,cost};}return output(['Setup','All-in total','Minimum pairwise distance'],best.set.map(o=>[o.id,usd(o.total_cents),best.spread]),['Component diversity is not a statistical independence or supply-chain guarantee.']);
});

add("replacement-graph","Least-change replacement graph","Availability","Map the closest supported alternatives by changed component slots, with exact transition cost.",[optionInput],function(s,i){
 const base=pick(s,i.setup);return output(['Alternative','Slot distance','Changed categories','Cost difference'],s.options.filter(o=>o.id!==base.id).map(o=>[o.id,distance(s,base,o),kinds.filter(k=>{const f=x=>JSON.stringify(parts(s,x).filter(p=>p.kind===k).map(p=>[p.id,p.quantity]).sort());return f(base)!==f(o);}).join(', '),signed(o.total_cents-base.total_cents)]).sort((a,b)=>a[1]-b[1]));
});

add("upgrade-ladder","Least-disruption budget ladder","Cost planning","For each affordable price breakpoint, find the option with the fewest changed slots relative to your current choice.",[optionInput,moneyInput('budget','Maximum hypothetical budget, USD',350)],function(s,i){
 const base=pick(s,i.setup),limit=cents(i.budget),levels=[...new Set(s.options.filter(o=>o.total_cents<=limit).map(o=>o.total_cents))].sort((a,b)=>a-b);return output(['Budget breakpoint','Least-change option','Changed slots','Option cost'],levels.map(b=>{const a=s.options.filter(o=>o.total_cents<=b).sort((a,b)=>distance(s,base,a)-distance(s,base,b)||a.total_cents-b.total_cents);return [usd(b),a[0].id,distance(s,base,a[0]),usd(a[0].total_cents)];}));
});

add("price-ceiling","Per-product price-rise tolerance","Cost planning","Calculate how much each product unit price can rise before every containing returned basket exceeds your budget.",[moneyInput('budget','Hypothetical budget, USD',350)],function(s,i){
 const budget=cents(i.budget);return output(['Product','Containing options','Best unit-price tolerance'],s.products.filter(p=>s.options.some(o=>o.items.some(x=>x.product_id===p.id))).map(p=>{const rows=s.options.filter(o=>o.items.some(x=>x.product_id===p.id)),tolerance=Math.max(...rows.map(o=>Math.floor((budget-o.total_cents)/o.items.find(x=>x.product_id===p.id).quantity)));return [p.name,rows.length,tolerance>=0?usd(tolerance):'Already above budget'];}));
});

add("inflation-stress","Uniform hardware inflation stress","Cost planning","Apply a user-declared percentage price increase to component subtotals while keeping saved tax/shipping fixed.",[percentInput('percent','Hardware price increase, percent',10,0,100),moneyInput('budget','Hypothetical budget, USD',350)],function(s,i){
 const rate=basisPoints(i.percent),budget=cents(i.budget);return output(['Setup','Original total','Stressed total','Within hypothetical budget'],s.options.map(o=>{const total=o.total_cents+Math.ceil(sub(s,o)*rate/10000);return [o.id,usd(o.total_cents),usd(total),total<=budget?'Yes':'No'];}),['A declared arithmetic scenario; no live price prediction or changed checkout quote.']);
});

add("price-shock","Exact-product price shock","Cost planning","Change one component unit price hypothetically, respecting the quantity in each supported basket.",[productInput,moneyInput('price','Hypothetical unit price, USD',150),moneyInput('budget','Hypothetical budget, USD',350)],function(s,i){
 const p=selected(s,i.product),price=cents(i.price),budget=cents(i.budget);return output(['Setup','Product quantity','Stressed all-in total','Within hypothetical budget'],s.options.map(o=>{const q=o.items.find(x=>x.product_id===p.id)?.quantity||0,total=o.total_cents+q*(price-p.price_cents);return [o.id,q,usd(total),total<=budget?'Yes':'No'];}));
});

add("tax-scenario","Tax and shipping scenario estimator","Cost planning","Replace saved extras with a declared tax rate on hardware and a fixed shipping amount.",[percentInput('tax','Illustrative tax rate, percent',8,0,100),moneyInput('shipping','Illustrative shipping, USD',10),moneyInput('budget','Hypothetical budget, USD',350)],function(s,i){
 const rate=basisPoints(i.tax),ship=cents(i.shipping),budget=cents(i.budget);return output(['Setup','Hardware','Illustrative tax','Shipping','Scenario total','Fits'],s.options.map(o=>{const hardware=sub(s,o),tax=Math.ceil(hardware*rate/10000),total=hardware+tax+ship;return [o.id,usd(hardware),usd(tax),usd(ship),usd(total),total<=budget?'Yes':'No'];}),['Illustrative tax arithmetic only; taxability and jurisdiction are not determined.']);
});

add("ownership-cost","Declared operating-cost horizon","Cost planning","Compare purchase plus explicitly assumed electricity and maintenance costs over a chosen horizon; no device consumption is inferred.",[countInput('watts','Assumed average system draw, watts',100,0,2000),countInput('hours','Hours per day',8,0,24),countInput('years','Years',3,1,10),{name:'rate',label:'Electricity USD per kWh',type:'number',min:0,max:10,step:.01,value:.15},moneyInput('maintenance','Annual maintenance assumption, USD',0)],function(s,i){
 const watts=num(i.watts,0,2000),hours=num(i.hours,0,24),years=int(i.years,1,10),rate=num(i.rate,0,10),energy=Math.round(watts/1000*hours*365*years*rate*100),maintenance=cents(i.maintenance)*years;return output(['Setup','Purchase','Assumed energy','Assumed maintenance','Horizon total'],s.options.map(o=>[o.id,usd(o.total_cents),usd(energy),usd(maintenance),usd(o.total_cents+energy+maintenance)]),['Consumption and tariffs are user assumptions, not measured device efficiency.']);
});

add("session-cost","Cost per productive session","Cost planning","Translate one-time planning costs into a stated number of work sessions without implying financing or resale value.",[countInput('sessions','Work sessions per year',200,1,366),countInput('years','Years of use',3,1,10)],function(s,i){
 const sessions=int(i.sessions,1,366)*int(i.years,1,10);return output(['Setup','Purchase total','Declared sessions','Cost per session'],s.options.map(o=>[o.id,usd(o.total_cents),sessions,usd(Math.round(o.total_cents/sessions))]),['Simple allocation of purchase cost, not a productivity or investment return claim.']);
});

add("price-interval","Worst-case price interval screen","Cost planning","Screen setups against a declared component-price uncertainty band; saved extras remain fixed.",[percentInput('percent','Symmetric hardware uncertainty, percent',15,0,100),moneyInput('budget','Hypothetical budget, USD',350)],function(s,i){
 const band=basisPoints(i.percent),budget=cents(i.budget);return output(['Setup','Low scenario','High scenario','Worst case fits'],s.options.map(o=>{const hardware=sub(s,o),extras=o.total_cents-hardware,low=Math.max(0,Math.floor(hardware*(10000-band)/10000))+extras,high=Math.ceil(hardware*(10000+band)/10000)+extras;return [o.id,usd(low),usd(high),high<=budget?'Yes':'No'];}),['Declared intervals have no probability or forecast interpretation.']);
});

add("minimax-regret","Price-scenario minimax regret","Cost planning","Find the smallest worst-case excess cost across baseline, hardware-inflation and one-product-shock scenarios among returned options.",[productInput,moneyInput('shock','Product unit increase, USD',20),percentInput('percent','Hardware inflation, percent',10,0,100)],function(s,i){
 const p=selected(s,i.product),shock=cents(i.shock),rate=basisPoints(i.percent),costs=s.options.map(o=>[o.total_cents,o.total_cents+Math.ceil(sub(s,o)*rate/10000),o.total_cents+(o.items.find(x=>x.product_id===p.id)?.quantity||0)*shock]),mins=[0,1,2].map(k=>Math.min(...costs.map(c=>c[k])));return output(['Setup','Worst excess cost','Baseline excess','Inflation excess','Product-shock excess'],s.options.map((o,n)=>{const regrets=costs[n].map((v,k)=>v-mins[k]);return [o.id,Math.max(...regrets),...regrets];}).sort((a,b)=>a[1]-b[1]).map(([id,...v])=>[id,...v.map(usd)]),['Regret is excess scenario cost, not human utility. No new hardware feasibility or budget certification is inferred.']);
});

add("pareto-frontier","Cost and model-trade-off Pareto frontier","Shortlisting","Identify returned setups dominated on total price, changed slots and the three estimated non-price contributions.",[],function(s,i){
 const dominates=(a,b)=>a.total_cents<=b.total_cents&&a.changed_slots.length<=b.changed_slots.length&&dims.every(k=>a.contributions[k]>=b.contributions[k])&&(a.total_cents<b.total_cents||a.changed_slots.length<b.changed_slots.length||dims.some(k=>a.contributions[k]>b.contributions[k]));return output(['Setup','Cost','Changed slots','Dominated by'],s.options.map(o=>{const by=s.options.filter(a=>a.id!==o.id&&dominates(a,o));return [o.id,usd(o.total_cents),o.changed_slots.length,by.length?by.map(a=>a.id).join(', '):'Frontier'];}),['Frontier under these finite model dimensions only, not general hardware superiority.']);
});

add("component-locks","Exact-component shortlist locks","Shortlisting","Filter supported alternatives while keeping up to four explicitly selected components.",[{name:'products',label:'Required product IDs, comma separated',type:'text',value:''}],function(s,i){
 const locked=ids(i.products);check(locked.length>0&&locked.length<=4,'Specify one to four exact product IDs.');locked.forEach(id=>selected(s,id));return output(['Setup retaining every component','All-in total','Locks'],sortCost(s.options.filter(o=>locked.every(id=>o.items.some(x=>x.product_id===id)))).map(o=>[o.id,usd(o.total_cents),locked.join(', ')]),['An analysis filter only; this does not modify requirements or certify unreturned baskets.']);
});
