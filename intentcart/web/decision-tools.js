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
 const options=w.configurations.map(o=>{check(o.checks&&Object.keys(o.checks).length&&Object.values(o.checks).every(v=>v===true),'Only supported options are admitted.');check(Array.isArray(o.items)&&o.items.length<=8&&o.items.length>0,'Invalid component list.');const items=o.items.map(i=>({product_id:String(i.product_id),quantity:int(i.quantity,1,8)}));check(new Set(items.map(i=>i.product_id)).size===items.length,'Duplicate basket item.');for(const i of items)check(products.some(p=>p.id===i.product_id&&kinds.includes(p.kind)),'Unknown component.');const contributions=Object.fromEntries(['lower_cost',...dims].map(k=>[k,num(o.contributions?.[k],0,1)]));const total=int(o.total_cents);check(total>=sum(items.map(i=>products.find(p=>p.id===i.product_id).price_cents*i.quantity)),'Invalid all-in price.');return {id:String(o.id),items,total_cents:total,changed_slots:copy(o.changed_slots||[]),check_names:Object.keys(o.checks),contributions};});
 check(new Set(options.map(o=>o.id)).size===options.length,'Duplicate setup identity.');
 const evidence=(task.evidence||[]);check(Array.isArray(evidence)&&evidence.length<=256,'Too many source fields.');
 const sources=evidence.map(e=>({id:String(e.source_id),product_id:String(e.product_id),field:String(e.field),value:copy(e.value??null),unit:String(e.unit||''),kind:String(e.kind||'fictional'),url:typeof e.url==='string'?e.url:null,observed_on:e.observed_at||e.observed_on||null,checks:copy(w.sources?.find(x=>x.source_id===e.source_id)?.checks||[]),freshness:copy(w.sources?.find(x=>x.source_id===e.source_id)?.freshness||{status:'not reported',age_days:null})}));
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

const r=readDocument(i.document);check(r&&r.replayable===true&&r.revision===s.revision&&r.catalog_sha256===s.catalog_sha256&&r.source_sha256===s.source_sha256,'A replayable receipt matching the loaded revision and source identities is required.');const t=tools.find(t=>t.id===r.tool);check(t&&!t.inputs.some(x=>x.type==='textarea')&&r.analysis_inputs&&typeof r.analysis_inputs==='object'&&!Array.isArray(r.analysis_inputs),'This analysis cannot be replayed.');const expected=t.run(copy(s),copy(r.analysis_inputs));const rows=[];for(const key of new Set(['columns','rows','notes',...Object.keys(expected)])){const a=JSON.stringify(r[key]),b=JSON.stringify(expected[key]);rows.push([key,a===b?'Matches':'Different']);}rows.push(['Receipt metadata',r.title===t.title&&r.checkout_supported===false?'Matches':'Different']);return output(['Receipt section','Recomputed comparison'],rows,['Same-input arithmetic reproduction only; matching data is not authenticity, source truth or a signature.']);
});

add("minimum-portfolio","Minimum contingency portfolio","Contingency portfolios","Exhaustively find the smallest set of returned options covering every representable single-product outage, breaking ties by shared-inventory cost.",[],function(s,i){

const a=portfolioSearch(s),coverable=a.pool.filter(id=>a.rows.some(r=>r.covered.includes(id))),best=a.rows.filter(r=>r.covered.length===coverable.length).sort((a,b)=>a.options.length-b.options.length||a.cost-b.cost)[0];return output(['Portfolio setup','Shared hardware inventory','Covered outages','Representable outages'],best.options.map(o=>[o.id,usd(best.cost),best.covered.length,coverable.length]),['Uncoverable product outages: '+(a.pool.filter(id=>!coverable.includes(id)).join(', ')||'None')+'. Inventory uses maximum required quantity, not simultaneous operation; extras are excluded.']);
});

add("budget-portfolio","Budgeted maximum outage coverage","Contingency portfolios","Search all returned-option subsets for the most single-product outages covered within a hypothetical shared-hardware budget.",[moneyInput('budget','Hardware inventory budget, USD',500)],function(s,i){

const budget=cents(i.budget),a=portfolioSearch(s),best=a.rows.filter(r=>r.cost<=budget).sort((a,b)=>b.covered.length-a.covered.length||a.cost-b.cost||a.options.length-b.options.length)[0];return output(['Setup','Shared inventory cost','Covered single outages','Outage cases'],best?best.options.map(o=>[o.id,usd(best.cost),best.covered.length,a.pool.length]):[],['No purchase or budget certification. Shared inventory covers alternative operation, not simultaneous use; tax/shipping are excluded.']);
});

add("critical-cut-sets","Minimum component cut sets","Contingency portfolios","Enumerate the smallest sets of up to three product failures that eliminate every returned supported option.",[countInput('limit','Maximum cut size',3,1,3)],function(s,i){

const pool=productPool(s),limit=int(i.limit,1,3);let cuts=[];for(let k=1;k<=limit;k++){combinations(pool,k,set=>{if(s.options.every(o=>o.items.some(x=>set.includes(x.product_id))))cuts.push(set);});if(cuts.length)break;}return output(['Failed exact products','Cut size','Eliminated options'],cuts.slice(0,100).map(c=>[c.join(', '),c.length,s.options.length]),[cuts.length?`${cuts.length} minimum cuts found; first 100 shown.`:'No cut found within the declared size; larger cuts remain unsearched.','Finite returned options only; this is not a full-catalog impossibility proof.']);
});

add("spare-bom","Shared spare-kit bill of materials","Contingency portfolios","Combine chosen returned setups using maximum component quantities, avoiding double-counting shared parts.",[portfolioInput],function(s,i){

const options=portfolioOptions(s,i.setups),kit=inventory(s,options);return output(['Exact product','Required shared quantity','Unit cost','Line cost','Containing setups'],[...kit].map(([id,q])=>{const p=selected(s,id);return [id,q,usd(p.price_cents),usd(q*p.price_cents),options.filter(o=>o.items.some(x=>x.product_id===id)).length];}),['One alternative setup at a time, not simultaneous workstations. Shared hardware total: '+usd(inventoryCost(s,kit))+'. Tax, shipping, ownership and live stock are not inferred.']);
});

add("inventory-reuse","Declared spare inventory reuse","Contingency portfolios","Calculate additional exact-product quantities for each returned setup from a declared inventory without assuming ownership.",[documentInput('inventory','Declared product quantities JSON','{}')],function(s,i){

const owned=quantityMap(s,readDocument(i.inventory));return output(['Setup','Additional hardware','Reusable units','Saved extras','Incremental planning total'],s.options.map(o=>{let cost=0,reused=0;for(const x of o.items){const keep=Math.min(owned.get(x.product_id)||0,x.quantity);reused+=keep;cost+=(x.quantity-keep)*selected(s,x.product_id).price_cents;}const extras=o.total_cents-sub(s,o);return [o.id,usd(cost),reused,usd(extras),usd(cost+extras)];}),['Declared inventory is hypothetical. Exact variants only; saved extras may differ from a future partial purchase.']);
});

add("backup-pair-matrix","Backup-pair shared-failure matrix","Contingency portfolios","Compare every returned pair by common failure points and shared inventory cost rather than assuming independent backups.",[],function(s,i){

const rows=[];for(let a=0;a<s.options.length;a++)for(let b=a+1;b<s.options.length;b++){const x=s.options[a],y=s.options[b],common=x.items.filter(p=>y.items.some(q=>q.product_id===p.product_id)).map(p=>p.product_id);rows.push([x.id,y.id,common.length,common.join(', ')||'None',usd(inventoryCost(s,inventory(s,[x,y])))]);}return output(['Setup A','Setup B','Shared failure products','Exact shared IDs','Shared hardware cost'],rows.sort((a,b)=>a[2]-b[2]),['A shared product outage disables both setups. Different products may still share an unmodeled supplier or failure cause.']);
});

add("marginal-spares","Marginal spare-product unlocks","Contingency portfolios","Find how many returned alternatives one additional unit of each product unlocks from a starting setup.",[optionInput],function(s,i){

const base=pick(s,i.setup),owned=inventory(s,[base]);return output(['One extra product','Additional hardware cost','Newly constructible setups','Unlocked setup IDs'],s.products.filter(p=>kinds.includes(p.kind)).map(p=>{const extra=new Map(owned);extra.set(p.id,(extra.get(p.id)||0)+1);const fits=(o,kit)=>o.items.every(x=>(kit.get(x.product_id)||0)>=x.quantity),unlocks=s.options.filter(o=>fits(o,extra)&&!fits(o,owned));return [p.id,usd(p.price_cents),unlocks.length,unlocks.map(o=>o.id).join(', ')||'None'];}).sort((a,b)=>b[2]-a[2]),['Inventory construction only; no new compatibility, ownership, availability or checkout authority.']);
});

add("coverage-cost-frontier","Contingency coverage cost frontier","Contingency portfolios","Compute exact shared-inventory cost breakpoints where the maximum number of covered single-product outages increases.",[],function(s,i){

const a=portfolioSearch(s),sorted=a.rows.sort((a,b)=>a.cost-b.cost||b.covered.length-a.covered.length),rows=[];let best=-1;for(const r of sorted)if(r.covered.length>best){best=r.covered.length;rows.push([usd(r.cost),best,a.pool.length,r.options.map(o=>o.id).join(', ')]);}return output(['Hardware cost breakpoint','Covered outages','Single-product cases','Witness portfolio'],rows,['Exact over at most 4,095 nonempty subsets of the twelve returned options. Shared quantities are maximums, extras excluded.']);
});

add("outage-probability","Shared-component availability model","Declared outage models","Use exact inclusion-exclusion to calculate alternative-setup availability under a declared independent per-product outage probability.",[portfolioInput,percentInput('failure','Assumed per-product failure probability, percent',5)],function(s,i){

const options=portfolioOptions(s,i.setups,8),q=basisPoints(i.failure)/10000,rows=options.map(o=>[o.id,(100*(1-q)**o.items.length).toFixed(6)+'%']);rows.push(['At least one chosen setup',(100*availability(options,q)).toFixed(6)+'%']);return output(['Declared event','Model probability'],rows,['Independent product-level failures and one common probability are explicit hypothetical assumptions. Shared parts are modeled; real failure rates, correlations and availability are unknown.']);
});

add("failure-importance","Component outage importance","Declared outage models","Compare portfolio availability conditional on each exact component working or failing, retaining shared-part dependence.",[portfolioInput,percentInput('failure','Assumed other-product failure probability, percent',5)],function(s,i){

const options=portfolioOptions(s,i.setups,8),q=basisPoints(i.failure)/10000,pool=[...new Set(options.flatMap(o=>o.items.map(x=>x.product_id)))];return output(['Exact product','Availability if working','Availability if failed','Conditional difference'],pool.map(id=>{const up=availability(options,q,id,1),down=availability(options,q,id,0);return [id,(100*up).toFixed(6)+'%',(100*down).toFixed(6)+'%',(100*(up-down)).toFixed(6)+' percentage points'];}).sort((a,b)=>parseFloat(b[3])-parseFloat(a[3])),['A sensitivity derivative under the declared independence model; no measured causal impact or reliability guarantee.']);
});

add("outage-sensitivity","Outage-assumption sensitivity curve","Declared outage models","Evaluate a chosen portfolio at five points between declared common product-failure probabilities.",[portfolioInput,percentInput('low','Low assumed failure probability, percent',0),percentInput('high','High assumed failure probability, percent',20)],function(s,i){

const options=portfolioOptions(s,i.setups,8),low=basisPoints(i.low),high=basisPoints(i.high);check(low<=high,'Low probability must not exceed high probability.');return output(['Assumed product failure probability','At least one setup available'],Array.from({length:5},(_,n)=>{const q=(low+(high-low)*n/4)/10000;return [(100*q).toFixed(4)+'%',(100*availability(options,q)).toFixed(6)+'%'];}),['Hypothetical independent-product model, not a calibrated forecast or confidence interval.']);
});

add("tradeoff-exchange","Incremental trade-off exchange rates","Preference diagnostics","Relate an exact price change between two returned options to each estimated non-price contribution change.",[optionInput,{name:'other',label:'Alternative setup',type:'setup'}],function(s,i){

const a=choice(s,i.setup),b=choice(s,i.other);check(a.id!==b.id,'Choose different setups.');return output(['Model contribution','Contribution change','Cost change','USD per +0.01 contribution'],dims.map(k=>{const d=b.contributions[k]-a.contributions[k];return [k,d.toFixed(6),signed(b.total_cents-a.total_cents),Math.abs(d)>1e-12?((b.total_cents-a.total_cents)/100/d*.01).toFixed(4):'No contribution change'];}),['Model units only, not hardware performance, willingness to pay or a recommended exchange rate.']);
});

add("preference-flip","Minimum preference transfer to tie the leader","Preference diagnostics","Find the smallest normalized weight mass moved from uniform weights that lets each rival tie the current uniform-score leader.",[],function(s,i){

const keys=['lower_cost',...dims],score=o=>sum(keys.map(k=>o.contributions[k]))/4,leader=[...s.options].sort((a,b)=>score(b)-score(a))[0];return output(['Uniform leader','Rival','Transferred weight mass','Tie witness weights'],s.options.filter(o=>o!==leader).map(o=>{const d=keys.map(k=>o.contributions[k]-leader.contributions[k]),weights=[.25,.25,.25,.25];let gap=-sum(d)/4,moved=0;const receiver=d.indexOf(Math.max(...d));for(const donor of [0,1,2,3].sort((a,b)=>d[a]-d[b])){if(gap<=1e-12)break;const gain=d[receiver]-d[donor];if(gain<=0)continue;const amount=Math.min(weights[donor],gap/gain);weights[donor]-=amount;weights[receiver]+=amount;moved+=amount;gap-=amount*gain;}return [leader.id,o.id,gap<=1e-10?moved.toFixed(6):'Cannot tie',gap<=1e-10?weights.map(v=>v.toFixed(6)).join(', '):'No feasible simplex weights'];}),['Four weights sum to one. Transfer mass is half the L1 weight distance, not posterior uncertainty or a prediction of human choices. Displayed weights and transfer mass are rounded to six decimals.']);
});

add("contribution-intervals","Contribution-interval robust shortlist","Preference diagnostics","Screen uniform-score rankings under a declared independent interval around each estimated contribution.",[{name:'epsilon',label:'Declared contribution half-width',type:'number',min:0,max:1,step:.01,value:.05}],function(s,i){

const e=num(i.epsilon,0,1),keys=['lower_cost',...dims],values=s.options.map(o=>({o,low:sum(keys.map(k=>Math.max(0,o.contributions[k]-e)))/4,high:sum(keys.map(k=>Math.min(1,o.contributions[k]+e)))/4})),best=Math.max(...values.map(x=>x.low));return output(['Setup','Worst uniform estimate','Best uniform estimate','Can reach best lower bound'],values.map(x=>[x.o.id,x.low.toFixed(6),x.high.toFixed(6),x.high>=best?'Yes':'No']),['User-declared interval arithmetic, not statistically estimated error bars or calibrated uncertainty.']);
});

add("rank-consensus","Tie-aware rank consensus","Preference diagnostics","Aggregate four single-contribution rankings with average tied ranks and expose the per-dimension ranks.",[],function(s,i){

const keys=['lower_cost',...dims],rows=s.options.map(o=>{const ranks=keys.map(k=>{const better=s.options.filter(x=>x.contributions[k]>o.contributions[k]).length,equal=s.options.filter(x=>x.contributions[k]===o.contributions[k]).length;return 1+better+(equal-1)/2;});return [o.id,sum(ranks),...ranks];});return output(['Setup','Rank sum',...keys],rows.sort((a,b)=>a[1]-b[1]),['Rank aggregation gives each dimension equal importance; it is a declared rule, not learned personal utility.']);
});

add("priority-order","Lexicographic priority ordering","Preference diagnostics","Order returned setups by an explicit sequence of priorities, avoiding arbitrary numerical trade-off weights.",[{name:'priority',label:'Priority order: price, disruption, driver, charging, refresh',type:'text',value:'price,driver,charging,refresh,disruption'}],function(s,i){

const keys=ids(i.priority),functions={price:o=>o.total_cents,disruption:o=>o.changed_slots.length,driver:o=>-o.contributions.no_driver,charging:o=>-o.contributions.charging_capacity,refresh:o=>-o.contributions.dock_refresh_capacity};check(keys.length>0&&keys.length<=5&&keys.every(k=>Object.hasOwn(functions,k)),'Use one to five supported unique priorities.');return output(['Order','Setup','All-in price','Applied priorities'],[...s.options].sort((a,b)=>{for(const k of keys){const d=functions[k](a)-functions[k](b);if(d)return d;}return a.id.localeCompare(b.id);}).map((o,n)=>[n+1,o.id,usd(o.total_cents),keys.join(' → ')]),['An analysis ordering only. Hard support and stored preference answers are unchanged.']);
});

add("value-envelope","Price versus model-value envelope","Preference diagnostics","Find the upper concave price/value envelope and its diminishing marginal contribution gains.",[],function(s,i){

const keys=['lower_cost',...dims],byCost=new Map();for(const o of s.options){const y=sum(keys.map(k=>o.contributions[k]))/4;if(!byCost.has(o.total_cents)||byCost.get(o.total_cents).y<y)byCost.set(o.total_cents,{o,y});}const points=[...byCost.values()].sort((a,b)=>a.o.total_cents-b.o.total_cents),front=[];let best=-Infinity;for(const p of points)if(p.y>best){front.push(p);best=p.y;}const hull=[];const slope=(a,b)=>(b.y-a.y)/(b.o.total_cents-a.o.total_cents);for(const p of front){while(hull.length>1&&slope(hull.at(-2),hull.at(-1))<=slope(hull.at(-1),p))hull.pop();hull.push(p);}return output(['Setup','Price','Uniform model estimate','Gain per extra USD'],hull.map((p,n)=>[p.o.id,usd(p.o.total_cents),p.y.toFixed(6),n?(100*slope(hull[n-1],p)).toFixed(8):'Starting point']),['A finite linear price/model-estimate trade-off envelope, not measured productivity, financial return or personal value.']);
});

add("repeat-consistency","Repeated-comparison consistency audit","Preference diagnostics","Group the last 48 explicit pairwise answers, retaining orientation, ties, skips and opposing answers.",[],function(s,i){

const groups=new Map();for(const h of s.history){const pair=[h.a,h.b].sort(),key=JSON.stringify(pair),g=groups.get(key)||{pair,a:0,b:0,tie:0,skip:0};if(h.choice==='a'||h.choice==='b'){const win=h.choice==='a'?h.a:h.b;g[win===pair[0]?'a':'b']++;}else if(h.choice==='tie'||h.choice==='skip')g[h.choice]++;groups.set(key,g);}return output(['Setup A','Setup B','A answers','B answers','Ties','Skips','Opposing answers present'],[...groups.values()].map(g=>[...g.pair,g.a,g.b,g.tie,g.skip,g.a&&g.b?'Yes':'No']),['Retained answers are correlated historical records, not independent people. Changed context can explain opposing choices.']);
});

add("comparison-connectivity","Preference comparison coverage graph","Preference diagnostics","Identify disconnected groups and unanswered setup connections within the last 48 retained comparisons.",[],function(s,i){

const ids=s.options.map(o=>o.id),neighbors=new Map(ids.map(id=>[id,new Set()]));for(const h of s.history)if(h.choice!=='skip'&&neighbors.has(h.a)&&neighbors.has(h.b)&&h.a!==h.b){neighbors.get(h.a).add(h.b);neighbors.get(h.b).add(h.a);}const groups=new Map();let component=0;for(const id of ids)if(!groups.has(id)){component++;const stack=[id];while(stack.length){const a=stack.pop();if(groups.has(a))continue;groups.set(a,component);stack.push(...neighbors.get(a));}}return output(['Setup','Comparison neighbors','Connected group'],ids.map(id=>[id,neighbors.get(id).size,groups.get(id)]),[`${component} connected groups; at least ${Math.max(0,component-1)} cross-group answered comparisons would connect them. This is structural coverage, not expected information gain.`]);
});

add("source-explanation-cover","Minimum observed-field explanation cover","Evidence traceability","Find a smallest set of observed fields covering every represented check label in the loaded source links.",[],function(s,i){

const labels=[...new Set(s.sources.flatMap(e=>e.checks||[]))];check(labels.length<=12,'At most twelve represented check labels can be covered.');let dp=new Map([[0,[]]]);for(const e of s.sources){const mask=(e.checks||[]).reduce((m,k)=>m|(1<<labels.indexOf(k)),0);for(const [state,list]of [...dp]){const next=state|mask;if(!dp.has(next)||dp.get(next).length>list.length+1)dp.set(next,[...list,e]);}}const chosen=dp.get((1<<labels.length)-1)||[];return output(['Observed source','Covered check labels','Total target labels'],chosen.map(e=>[e.id,e.checks.join(', '),labels.length]),['Minimum explanation-label coverage only. Linked citations do not prove checks independently or identify which field must be inspected to discover a plan.']);
});

add("check-traceability","Observed evidence-to-check matrix","Evidence traceability","Expose check labels with and without product-matched inspected source links for every returned setup.",[],function(s,i){

const rows=[];for(const o of s.options)for(const k of o.check_names||[]){const links=s.sources.filter(e=>o.items.some(x=>x.product_id===e.product_id)&&(e.checks||[]).includes(k));rows.push([o.id,k,links.length,links.map(e=>e.id).join(', ')||'No observed product-field link']);}return output(['Setup','Represented check','Observed field links','Source IDs'],rows,['A missing observed link does not negate the server-supported check: declared requirements, prices and fixture assumptions can supply other inputs. No new source validation is performed.']);
});

add("citation-duplicates","Canonical citation duplicate audit","Evidence traceability","Find citations sharing a URL after removing fragments and sorting query parameters, while retaining distinct source IDs.",[],function(s,i){

const groups=new Map();for(const e of s.sources){if(!e.url)continue;let key;try{const u=new URL(e.url);u.hash='';u.searchParams.sort();key=u.href;}catch{continue;}const a=groups.get(key)||[];a.push(e);groups.set(key,a);}return output(['Canonical URL','Observed fields','Exact source IDs'],[...groups].filter(([,v])=>v.length>1).map(([k,v])=>[k,v.length,v.map(e=>e.id).join(', ')]),['Canonicalization is a citation grouping rule, not proof of equivalent pages, independence or source credibility. URLs are never fetched.']);
});

add("review-knapsack","Time-budgeted evidence review plan","Evidence traceability","Choose observed fields under a declared review-time budget using exact knapsack optimization of summed setup exposures.",[countInput('minutes','Available review minutes',30,0,240),countInput('cost','Assumed minutes per field',5,1,60)],function(s,i){

const budget=int(i.minutes,0,240),cost=int(i.cost,1,60),dp=Array.from({length:budget+1},()=>({value:0,items:[]}));for(const e of s.sources){const value=s.options.filter(o=>o.items.some(x=>x.product_id===e.product_id)).length;for(let b=budget;b>=cost;b--){const prev=dp[b-cost],candidate=prev.value+value;if(candidate>dp[b].value)dp[b]={value:candidate,items:[...prev.items,{e,value}]};}}const best=dp[budget];return output(['Source to review','Declared minutes','Containing setups'],best.items.map(x=>[x.e.id,cost,x.value]),[`Objective: ${best.value} summed source/setup exposures; repeated setups count once per selected field, not as unique verified baskets. Time is a user assumption; no field is fetched or marked reviewed.`]);
});

add("changed-source-impact","Cross-snapshot changed-source impact","Evidence traceability","Compare observed values and cite current returned setups containing products whose prior evidence changed.",[documentInput('previous','Earlier portable snapshot JSON')],function(s,i){

const old=portableDocument(i.previous),rows=[];for(const e of s.sources){const a=old.sources.find(x=>x.id===e.id),changed=!a||JSON.stringify([a.product_id,a.field,a.value,a.unit,a.url,a.observed_on])!==JSON.stringify([e.product_id,e.field,e.value,e.unit,e.url,e.observed_on]);if(changed){const options=s.options.filter(o=>o.items.some(x=>x.product_id===e.product_id));rows.push([e.id,a?'Changed':'New',options.length,options.map(o=>o.id).join(', ')||'None']);}}for(const e of old.sources)if(!s.sources.some(x=>x.id===e.id)){const options=s.options.filter(o=>o.items.some(x=>x.product_id===e.product_id));rows.push([e.id,'Removed',options.length,options.map(o=>o.id).join(', ')||'None']);}return output(['Observed source','Difference','Current product exposure','Current setup IDs'],rows,['Product-level exposure is conservative, not proof that a changed field invalidates every containing setup. Earlier documents are untrusted; no state is imported.']);
});

add("snapshot-migration","Cross-snapshot migration parts list","Reproduction","Calculate retained, additional and surplus exact-product units between one earlier setup and a current supported setup.",[documentInput('previous','Earlier portable snapshot JSON'),{name:'earlier',label:'Earlier setup ID',type:'text',value:''},optionInput],function(s,i){

const old=portableDocument(i.previous),a=old.options.find(o=>o.id===i.earlier),b=choice(s,i.setup);check(a,'Choose an exact setup ID from the earlier snapshot.');const rows=[];for(const id of new Set([...a.items.map(x=>x.product_id),...b.items.map(x=>x.product_id)])){const before=a.items.find(x=>x.product_id===id)?.quantity||0,after=b.items.find(x=>x.product_id===id)?.quantity||0,p=old.products.find(x=>x.id===id),now=s.products.find(x=>x.id===id),same=p&&now&&p.variant===now.variant&&p.kind===now.kind,keep=same?Math.min(before,after):0,add=after-keep;rows.push([id,keep,add,before-keep,now?usd(add*now.price_cents):'No current price']);}return output(['Product','Reusable exact units','Additional units','Surplus old units','Added hardware cost'],rows,['Old snapshots do not establish ownership. Reuse requires matching product ID, variant and kind; source changes may still require human review. Extras, resale, physical condition and live procurement are excluded.']);
});

add("analysis-diff","Analysis receipt difference review","Reproduction","Compare assumptions and changed result cells from two downloaded analyses of the same tool without executing imported instructions.",[documentInput('documents','JSON array containing two downloaded analyses')],function(s,i){

const docs=readDocument(i.documents);check(Array.isArray(docs)&&docs.length===2,'Provide exactly two analysis receipts in a JSON array.');const [a,b]=docs;check(a&&b&&typeof a.tool==='string'&&a.tool===b.tool&&Array.isArray(a.columns)&&Array.isArray(b.columns)&&JSON.stringify(a.columns)===JSON.stringify(b.columns)&&a.columns.length<=12&&Array.isArray(a.rows)&&Array.isArray(b.rows)&&a.rows.length<=600&&b.rows.length<=600,'Receipts must use the same tool and bounded table columns.');const rows=[];for(const key of ['revision','catalog_sha256','source_sha256','analysis_inputs'])if(JSON.stringify(a[key])!==JSON.stringify(b[key]))rows.push([key,JSON.stringify(a[key])??'Absent',JSON.stringify(b[key])??'Absent']);for(let n=0;n<Math.max(a.rows.length,b.rows.length);n++){check((!a.rows[n]||Array.isArray(a.rows[n]))&&(!b.rows[n]||Array.isArray(b.rows[n])),'Invalid receipt row.');if(JSON.stringify(a.rows[n])!==JSON.stringify(b.rows[n]))rows.push(['Row '+(n+1),JSON.stringify(a.rows[n])??'Absent',JSON.stringify(b.rows[n])??'Absent']);}return output(['Changed item','Earlier analysis','Later analysis'],rows.slice(0,600),[`${rows.length} differences; first 600 shown. Rows compare by displayed position, not presumed matching setup identity. Imported text is untrusted and grants no authority.`]);
});

export function analysisBrief(r){
 check(r&&typeof r.tool==='string'&&tools.some(t=>t.id===r.tool)&&r.checkout_supported===false&&Array.isArray(r.columns)&&r.columns.length<=12&&Array.isArray(r.rows)&&r.rows.length<=600,'Build a bounded read-only analysis before exporting.');
 const escape=v=>String(typeof v==='string'?v:JSON.stringify(v)).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('\\','\\\\').replace(/[|`*_\[\]#~]/g,'\\$&').replaceAll('\n',' ');
 const lines=['# '+escape(r.title),'',`Loaded revision: ${escape(r.revision)}`,`Catalog: ${escape(r.catalog_sha256)}`,`Compiler: ${escape(r.source_sha256||'Not recorded')}`,'','## Assumptions',r.replayable?'Declared parameters: '+escape(r.analysis_inputs||{}):'Pasted document inputs are omitted. Replaying this receipt is unavailable.','','## Scope',escape(r.scope),'','## Results','| '+r.columns.map(escape).join(' | ')+' |','| '+r.columns.map(()=> '---').join(' | ')+' |'];
 for(const row of r.rows){check(Array.isArray(row)&&row.length===r.columns.length,'Invalid result row.');lines.push('| '+row.map(escape).join(' | ')+' |');}
 if(!r.rows.length)lines.push('','No matching rows in the returned options.');
 lines.push('','## Review notes',...(r.notes||[]).map(n=>'- '+escape(n)),'','Checkout authority: none. This is a local analysis, not a signed verification or purchase authorization. Review product/source contents before sharing.');return lines.join('\n')+'\n';
}
