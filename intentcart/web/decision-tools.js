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
export function runTool(id,task,input={}){const tool=tools.find(t=>t.id===id);check(tool,'Unknown decision tool.');const s=snapshot(task);check(s.options.length>0,'No supported options in this snapshot. Resolve requirements or evidence first.');const before=JSON.stringify(s);const result=tool.run(s,input);check(JSON.stringify(s)===before,'A decision tool must not mutate the snapshot.');check(Array.isArray(result.columns)&&Array.isArray(result.rows)&&result.rows.length<=600,'Invalid analysis output.');const replayable=!tool.inputs.some(x=>x.type==='textarea');const parameters=replayable?Object.fromEntries(tool.inputs.filter(x=>Object.hasOwn(input,x.name)&&input[x.name]!==undefined).map(x=>[x.name,copy(input[x.name])])):null;return {tool:id,title:tool.title,revision:s.revision,catalog_sha256:s.catalog_sha256,source_sha256:s.source_sha256,replayable,analysis_inputs:parameters,scope:`Only the ${s.options.length} returned supported options in this loaded revision; hypothetical inputs do not change support, prices, preference answers or approval.`,...result,checkout_supported:false};}
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

add("reweighting","Preference-contribution reweighting sandbox","Shortlisting","Explore user-supplied multipliers over the current model contribution estimates; no learned preference is changed.",[{name:'cost',label:'Cost multiplier',type:'number',min:0,max:10,step:.1,value:1},{name:'driver',label:'Driver simplicity multiplier',type:'number',min:0,max:10,step:.1,value:1},{name:'charging',label:'Charging multiplier',type:'number',min:0,max:10,step:.1,value:1},{name:'refresh',label:'Refresh multiplier',type:'number',min:0,max:10,step:.1,value:1}],function(s,i){
 const w=[i.cost,i.driver,i.charging,i.refresh].map(v=>num(v,0,10));check(sum(w)>0,'At least one multiplier must be positive.');const keys=['lower_cost',...dims];return output(['Setup','Reweighted estimate','All-in cost'],s.options.map(o=>[o.id,sum(keys.map((k,n)=>o.contributions[k]*w[n]))/sum(w),usd(o.total_cents)]).sort((a,b)=>b[1]-a[1]).map(([id,v,c])=>[id,v.toFixed(6),c]),['Multipliers rescale existing estimated contributions; they are not newly learned personal weights.']);
});

add("weight-sweep","Preference sensitivity sweep","Shortlisting","Count which options lead on a fixed 35-profile multiplier grid, retaining exact ties rather than inventing probabilities.",[],function(s,i){
 const keys=['lower_cost',...dims],wins=new Map(s.options.map(o=>[o.id,0]));let profiles=0;for(let a=0;a<=4;a++)for(let b=0;b<=4-a;b++)for(let c=0;c<=4-a-b;c++){const w=[a,b,c,4-a-b-c],scores=s.options.map(o=>sum(keys.map((k,n)=>o.contributions[k]*w[n]))),best=Math.max(...scores);profiles++;s.options.forEach((o,n)=>{if(Math.abs(scores[n]-best)<1e-12)wins.set(o.id,wins.get(o.id)+1);});}return output(['Setup','Leading/tied profiles','Grid profiles'],[...wins].sort((a,b)=>b[1]-a[1]).map(([id,v])=>[id,v,profiles]),['Grid frequencies are sensitivity diagnostics, not posterior confidence or win probabilities.']);
});

add("preference-cycles","Preference cycle audit","Shortlisting","Detect directed cycles in the last 48 retained explicit A/B answers, with ties and skips kept separate.",[],function(s,i){
 const edges=s.history.filter(h=>h.choice==='a'||h.choice==='b').map(h=>h.choice==='a'?[h.a,h.b]:[h.b,h.a]),nodes=[...new Set(edges.flat())],reach=new Map(nodes.map(n=>[n,new Set()]));for(const [a,b] of edges)reach.get(a).add(b);for(const k of nodes)for(const a of nodes)if(reach.get(a).has(k))for(const b of reach.get(k))reach.get(a).add(b);return output(['Preferred','Over','Part of directed cycle'],edges.map(([a,b])=>[a,b,reach.get(b)?.has(a)?'Yes':'No']),['Cycles can reflect evolving or contextual choices; they are not user mistakes. Ties/skips do not become directed preferences.']);
});

add("comparison-pairs","Distinctive comparison pair finder","Shortlisting","Surface supported pairs absent from the last 48 retained comparisons with large differences in model-contribution vectors.",[],function(s,i){
 const asked=new Set(s.history.map(h=>[h.a,h.b].sort().join('|'))),keys=['lower_cost',...dims],pairs=[];for(let a=0;a<s.options.length;a++)for(let b=a+1;b<s.options.length;b++){const x=s.options[a],y=s.options[b];if(asked.has([x.id,y.id].sort().join('|')))continue;const separation=Math.sqrt(sum(keys.map(k=>(x.contributions[k]-y.contributions[k])**2)));pairs.push([x.id,y.id,separation,Math.abs(x.total_cents-y.total_cents)]);}return output(['Setup A','Setup B','Model-vector distance','Cost difference'],pairs.sort((a,b)=>b[2]-a[2]).slice(0,12).map(([a,b,d,c])=>[a,b,d.toFixed(6),usd(c)]),['Difference heuristic only, not expected information gain or an automatic question.']);
});

add("expiry-forecast","Source review expiry forecast","Evidence review","Forecast review deadlines from observed dates and the declared review interval, separating undated/fictional fields.",[countInput('days','Forecast horizon, days',30,0,365)],function(s,i){
 const horizon=int(i.days,0,365);return output(['Source','Product / field','Days until review boundary','Within horizon'],s.sources.map(e=>{const age=e.freshness.age_days,remaining=Number.isInteger(age)?s.evidence_max_age_days-age:null;return [e.id,e.product_id+' / '+e.field,remaining===null?'Undated / fictional':remaining,remaining===null?'Unresolved':remaining<=horizon?'Yes':'No'];}),['Boundary uses the loaded server age; expiry occurs after the allowed age, not at it. Refresh for a new clock reading.']);
});

add("source-blast-radius","Observed-source dependency blast radius","Evidence review","Map each inspected product field to returned baskets containing that exact product.",[],function(s,i){
 return output(['Source','Field','Containing options','Containing setup IDs'],s.sources.map(e=>{const a=s.options.filter(o=>o.items.some(x=>x.product_id===e.product_id));return [e.id,e.field,a.length,a.map(o=>o.id).join(', ')||'None'];}),['Product-level exposure is conservative: it does not prove every containing basket depends on this exact field.']);
});

add("source-concentration","Source origin concentration audit","Evidence review","Group observed fields by cited URL origin and evidence kind; do not confuse repeated fields with independent sources.",[],function(s,i){
 const groups=new Map();for(const e of s.sources){let origin='No external origin';if(e.url){try{origin=new URL(e.url).origin;}catch{origin='Invalid URL';}}const key=e.kind+' / '+origin;const g=groups.get(key)||{fields:0,products:new Set()};g.fields++;g.products.add(e.product_id);groups.set(key,g);}return output(['Evidence kind / origin','Observed fields','Distinct products'],[...groups].map(([k,v])=>[k,v.fields,v.products.size]),['Concentration describes citations, not credibility, truth, independent corroboration or supply-chain independence.']);
});

add("source-conflicts","Observed-value contradiction audit","Evidence review","Find distinct values observed for the same exact product and field without resolving the contradiction automatically.",[],function(s,i){
 const groups=new Map();for(const e of s.sources){const k=e.product_id+' / '+e.field,g=groups.get(k)||[];g.push(e);groups.set(k,g);}return output(['Product / field','Distinct values','Source IDs'],[...groups].filter(([,v])=>new Set(v.map(e=>JSON.stringify([e.value,e.unit]))).size>1).map(([k,v])=>[k,[...new Set(v.map(e=>JSON.stringify(e.value)+' '+e.unit))].join(' | '),v.map(e=>e.id).join(', ')]),['Only already observed fields are compared; a clean table does not certify the whole catalog.']);
});

add("review-priority","Evidence review priority queue","Evidence review","Order inspected fields by overdue/unknown age and number of exposed returned setups.",[],function(s,i){
 const rows=s.sources.map(e=>{const age=e.freshness.age_days,remaining=Number.isInteger(age)?s.evidence_max_age_days-age:null,exposed=s.options.filter(o=>o.items.some(x=>x.product_id===e.product_id)).length;return {e,remaining,exposed};}).sort((a,b)=>(a.remaining??-100000)-(b.remaining??-100000)||b.exposed-a.exposed);return output(['Source','Review status','Days to boundary','Exposed options'],rows.map(({e,remaining,exposed})=>[e.id,e.freshness.status,remaining??'Unknown',exposed]),['A declared triage rule, not a confidence estimate. Unknown dates require human review; no source is fetched.']);
});

add("portable-snapshot","Portable private-data-minimized decision snapshot","Review and handoff","Export supported plans, product declarations and observed fields without query text, sessions or raw event history.",[],function(s,i){
 const portable={...copy(s),history:[]};return {...output(['Snapshot','Revision','Supported options','Observed fields'],[['intentcart-decision-snapshot/1',s.revision,s.options.length,s.sources.length]],['The downloaded JSON includes snapshot_data for later comparison. Review selected product/source content before sharing; hashes identify content sources, not authenticity.']),snapshot_data:portable};
});

add("snapshot-diff","Earlier-versus-current decision snapshot diff","Review and handoff","Paste an exported studio snapshot to compare prices, available setup IDs, observed values and source identities without importing authority.",[{name:'previous',label:'Previously downloaded portable snapshot JSON',type:'textarea',value:''}],function(s,i){
 check(typeof i.previous==='string'&&i.previous.length>0&&i.previous.length<=120000,'Paste a bounded exported portable snapshot.');
let raw;try{raw=JSON.parse(i.previous);}catch{throw Error('The snapshot is not valid JSON.');}
const old=raw?.snapshot_data;
check(raw?.tool==='portable-snapshot'&&old?.schema==='intentcart-decision-snapshot/1'&&Array.isArray(old.options)&&old.options.length<=12&&Array.isArray(old.sources)&&old.sources.length<=256&&Array.isArray(old.products)&&old.products.length<=24,'Only portable decision snapshots are accepted.');
for(const list of [old.options,old.sources,old.products]){check(list.every(x=>x&&typeof x==='object'&&typeof x.id==='string'&&x.id.length>0&&x.id.length<=200)&&new Set(list.map(x=>x.id)).size===list.length,'Snapshot record identities must be bounded and unique.');}
int(old.budget_cents);int(old.evidence_max_age_days,1,3650);
for(const p of old.products){int(p.price_cents);check(kinds.includes(p.kind)&&typeof p.name==='string'&&typeof p.variant==='string','Invalid portable product.');}
for(const o of old.options){int(o.total_cents);check(Array.isArray(o.items)&&o.items.length<=8&&o.items.every(x=>x&&typeof x.product_id==='string'&&Number.isSafeInteger(x.quantity)&&x.quantity>=1&&x.quantity<=8)&&Array.isArray(o.changed_slots)&&o.changed_slots.length<=4&&o.contributions&&['lower_cost',...dims].every(k=>Number.isFinite(o.contributions[k])&&o.contributions[k]>=0&&o.contributions[k]<=1),'Invalid portable setup.');}
const rows=[],compare=(label,a,b)=>{const left=JSON.stringify(a),right=JSON.stringify(b);if(left!==right)rows.push([label,left??'Absent',right??'Absent']);};
compare('Catalog identity',old.catalog_sha256,s.catalog_sha256);compare('Compiler identity',old.source_sha256,s.source_sha256);compare('Budget, cents',old.budget_cents,s.budget_cents);compare('Evidence review interval, days',old.evidence_max_age_days,s.evidence_max_age_days);
const product=p=>p?{name:p.name,variant:p.variant,kind:p.kind,price_cents:p.price_cents}:null;
const setup=o=>o?{total_cents:o.total_cents,items:[...o.items].sort((a,b)=>a.product_id.localeCompare(b.product_id)),changed_slots:[...o.changed_slots].sort(),contributions:Object.fromEntries(['lower_cost',...dims].map(k=>[k,o.contributions[k]]))}:null;
const source=e=>e?{product_id:e.product_id,field:e.field,value:e.value,unit:e.unit,kind:e.kind,url:e.url,observed_on:e.observed_on}:null;
for(const [label,key,project] of [['Product','products',product],['Setup','options',setup],['Observed source','sources',source]])for(const id of new Set([...old[key].map(x=>x.id),...s[key].map(x=>x.id)])){const a=old[key].find(x=>x.id===id),b=s[key].find(x=>x.id===id);if(!a||!b)rows.push([label+' '+id,a?JSON.stringify(project(a)):'Absent',b?JSON.stringify(project(b)):'Absent']);else compare(label+' '+id,project(a),project(b));}
return output(['Changed record','Earlier snapshot','Loaded current snapshot'],rows,['Imported JSON is untrusted comparison material only. It cannot restore state, support a plan, change a fact or approve payment. Dates and field contents are compared; changing server-computed source ages alone is not a fact change.']);
});


// Bounded contingency and reproduction helpers; all operate on detached local snapshots.
const documentInput=(name,label,value='')=>({name,label,type:'textarea',value});
const portfolioInput={name:'setups',label:'Returned setup IDs, comma separated (blank = first two)',type:'text',value:''};
function readDocument(v){check(typeof v==='string'&&v.length>0&&v.length<=120000,'Provide JSON text up to 120,000 characters.');try{return JSON.parse(v);}catch{throw Error('The document is not valid JSON.');}}
function portfolioOptions(s,v,max=12){const list=ids(v||'');check(list.length<=max,`Choose at most ${max} setups.`);return (list.length?list:s.options.slice(0,Math.min(2,max)).map(o=>o.id)).map(id=>choice(s,id));}
const productPool=s=>[...new Set(s.options.flatMap(o=>o.items.map(x=>x.product_id)))];
function inventory(s,options){const map=new Map();for(const o of options)for(const p of o.items)map.set(p.product_id,Math.max(map.get(p.product_id)||0,p.quantity));return map;}
const inventoryCost=(s,kit)=>sum([...kit].map(([id,q])=>selected(s,id).price_cents*q));
function quantityMap(s,raw){check(raw&&typeof raw==='object'&&!Array.isArray(raw)&&Object.keys(raw).length<=24,'Use an object of at most 24 exact product quantities.');return new Map(Object.entries(raw).map(([id,q])=>{selected(s,id);return [id,int(q,0,8)];}));}
function combinations(list,k,fn,start=0,chosen=[]){if(chosen.length===k){fn(chosen);return;}for(let i=start;i<=list.length-(k-chosen.length);i++)combinations(list,k,fn,i+1,[...chosen,list[i]]);}
function portfolioSearch(s){const pool=productPool(s),rows=[];for(let mask=1;mask<(1<<s.options.length);mask++){const options=s.options.filter((o,n)=>mask&(1<<n)),kit=inventory(s,options),covered=pool.filter(id=>options.some(o=>!o.items.some(x=>x.product_id===id)));rows.push({options,cost:inventoryCost(s,kit),covered});}return {pool,rows};}
function availability(options,q,fixed=null,value=1){let total=0;for(let mask=1;mask<(1<<options.length);mask++){const group=options.filter((o,n)=>mask&(1<<n)),products=new Set(group.flatMap(o=>o.items.map(x=>x.product_id)));let probability=1;for(const id of products)probability*=id===fixed?value:1-q;total+=(group.length%2?1:-1)*probability;}check(total>=-1e-9&&total<=1+1e-9,'Numerical probability bounds exceeded.');return Math.max(0,Math.min(1,total));}
function portableDocument(text){const raw=readDocument(text),s=raw?.snapshot_data;check(raw?.tool==='portable-snapshot'&&s?.schema==='intentcart-decision-snapshot/1','Use a portable decision snapshot.');for(const [key,max]of [['options',12],['products',24],['sources',256]])check(Array.isArray(s[key])&&s[key].length<=max&&s[key].every(x=>x&&typeof x.id==='string'&&x.id.length<=200)&&new Set(s[key].map(x=>x.id)).size===s[key].length,'Portable record IDs must be bounded and unique.');for(const o of s.options)check(Array.isArray(o.items)&&o.items.length<=8&&o.items.every(x=>x&&typeof x.product_id==='string'&&Number.isSafeInteger(x.quantity)&&x.quantity>=1&&x.quantity<=8)&&new Set(o.items.map(x=>x.product_id)).size===o.items.length,'Invalid portable item quantities.');return s;}

add("receipt-replay","Saved-analysis replay verifier","Reproduction","Recompute a non-import analysis on the same loaded revision and identify edited or incompatible receipts.",[documentInput('document','Downloaded analysis JSON')],function(s,i){

const r=readDocument(i.document);check(r&&r.replayable===true&&r.revision===s.revision&&r.catalog_sha256===s.catalog_sha256&&r.source_sha256===s.source_sha256,'A replayable receipt matching the loaded revision and source identities is required.');const t=tools.find(t=>t.id===r.tool);check(t&&!t.inputs.some(x=>x.type==='textarea')&&r.analysis_inputs&&typeof r.analysis_inputs==='object'&&!Array.isArray(r.analysis_inputs),'This analysis cannot be replayed.');const expected=t.run(copy(s),copy(r.analysis_inputs));const rows=[];for(const key of ['columns','rows','notes']){const a=JSON.stringify(r[key]||[]),b=JSON.stringify(expected[key]||[]);rows.push([key,a===b?'Matches':'Different']);}return output(['Receipt section','Recomputed comparison'],rows,['Same-input arithmetic reproduction only; matching data is not authenticity, source truth or a signature.']);
});

add("minimum-portfolio","Minimum contingency portfolio","Contingency portfolios","Exhaustively find the smallest set of returned options covering every representable single-product outage, breaking ties by shared-inventory cost.",[],function(s,i){

const a=portfolioSearch(s),coverable=a.pool.filter(id=>a.rows.some(r=>r.covered.includes(id))),best=a.rows.filter(r=>r.covered.length===coverable.length).sort((a,b)=>a.options.length-b.options.length||a.cost-b.cost)[0];return output(['Portfolio setup','Shared hardware inventory','Covered outages','Representable outages'],best.options.map(o=>[o.id,usd(best.cost),best.covered.length,coverable.length]),['Uncoverable product outages: '+(a.pool.filter(id=>!coverable.includes(id)).join(', ')||'None')+'. Inventory uses maximum required quantity, not simultaneous operation; extras are excluded.']);
});
