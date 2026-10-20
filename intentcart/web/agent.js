const $ = id => document.getElementById(id);
let csrf = '', task = null, catalog = null, enabled = false, busy = false, dirty = false;
const money = n => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(n/100);
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Check the reviewed task fields.');
  return result;
}
function message(text) { $('message').textContent=text; $('message').hidden=false; }
async function act(fn) {
  if (busy) return;
  busy=true; render(); $('message').hidden=true;
  try { await fn(); } catch(error) { message(error.message); }
  finally { busy=false; render(); }
}
async function collection() {
  catalog = await api('/api/agent/catalog?kind='+$('collection').value);
  $('laptop').replaceChildren(...catalog.laptops.map(p => new Option(p.name,p.id)));
  $('catalog-notice').textContent=catalog.notice;
  $('warnings').replaceChildren(...(catalog.warnings || ['All products in this collection are fictional.']).map(text => { const li=document.createElement('li');li.textContent=text;return li; }));
  $('assumptions-label').hidden=$('collection').value!=='curated';
}
function goal() {
  return {laptop_id:$('laptop').value,budget_cents:Math.round(Number($('budget').value)*100),displays:Number($('displays').value),height:Number($('height').value),hz:Number($('hz').value),reuse_monitor:$('reuse').checked,allow_driver:$('driver').checked};
}
function label(id) { return catalog?.products.find(p=>p.id===id)?.name || id; }
function render() {
  const active=task?.status==='ACTIVE'&&!dirty;
  $('next').disabled=busy||!active;
  $('model').disabled=busy||!active||!enabled;
  $('task-form').querySelectorAll('button').forEach(b=>b.disabled=busy);
  $('permit').disabled=$('decline').disabled=busy||dirty;
  $('export').hidden=!task;
  $('engine').textContent=task?.mode || 'Local policy · no external calls';
  if (!task) return;
  $('status').textContent={ACTIVE:'Investigate the decision.',WAITING_FOR_USER:'One decision is yours.',RECOMMENDED:'A supported configuration.',DEFERRED:'The agent has deferred.',BUDGET_STOP:'Inspection budget reached.',STEP_STOP:'Action limit reached.'}[task.status] || task.status;
  $('remaining').textContent=`${task.inspection_remaining} inspections · ${task.steps_remaining} steps left`;
  $('guidance').textContent=dirty?'Requirements have been edited. Start a reviewed task to apply them; the evidence below belongs to the previous task.':task.status==='RECOMMENDED'?'Recommendation is bound to this task and observed evidence. Planning allowances still need a current merchant quote.':task.notice;
  $('question').hidden=!task.pending_question;
  $('question-text').textContent=task.pending_question?.prompt || '';
  $('plan').replaceChildren();
  const plan=task.result.plan;
  if (plan) {
    const box=document.createElement('div');box.className='basket';
    const title=document.createElement('h3');title.textContent=(task.status==='RECOMMENDED'?'Accepted recommendation':'Supported candidate')+' · '+money(plan.total_cents);
    const list=document.createElement('ul');
    for(const item of plan.items){const li=document.createElement('li');li.textContent=`${item.quantity} × ${label(item.product_id)}`;list.append(li);}
    const note=document.createElement('p');note.className='fine';note.textContent=task.result.objective;
    const change=document.createElement('button');change.textContent='Simulate this dock becoming unavailable';change.disabled=busy;
    change.addEventListener('click',()=>act(async()=>{ const dock=plan.items.find(i=>catalog.products.find(p=>p.id===i.product_id)?.kind==='dock');task=await api('/api/agent/revise',{revision:task.revision,exclude:dock.product_id}); }));
    box.append(title,list,note,change);$('plan').append(box);
  } else {
    const p=document.createElement('p');p.className='fine';p.textContent=task.result.status==='NEEDS_EVIDENCE'?'Specifications remain unresolved. Take a step to inspect a relevant source.':'No supported configuration currently fits. Review requirements or allow the agent to explain deferral.';$('plan').append(p);
  }
  $('evidence-count').textContent=` · ${task.evidence.length}`;
  $('sources').replaceChildren(...task.evidence.map(source=>{
    const box=document.createElement('div');box.className='source';
    const name=document.createElement('strong');name.textContent=`${label(source.product_id)} · ${source.field}: ${source.value} ${source.unit || ''}`;
    const text=document.createElement('p');text.textContent=source.summary || source.excerpt;
    const meta=document.createElement('p');meta.className='fine';meta.textContent=`${source.kind || 'fictional fixture'} · ${source.observed_on || source.observed_at || 'fixture date'} · ${source.variant}`;
    box.append(name,text,meta);
    if(source.url?.startsWith('https://')){ const link=document.createElement('a');link.textContent='Open cited source ↗';link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';box.append(link); }
    return box;
  }));
  $('events').replaceChildren(...task.events.map(event=>{const li=document.createElement('li');li.textContent=`${event.index}. ${event.action.action} ${event.action.target || ''}`;const note=document.createElement('small');note.textContent=`${event.origin} · ${event.action.reason || 'Explicit human response'}`;li.append(note);return li;}));
  const choices=task.comparisons;
  $('preference').hidden=choices.length<2;
  for(const id of ['choice-a','choice-b']) $(id).replaceChildren(...choices.map(p=>new Option(`${money(p.total_cents)} · ${p.items.map(i=>label(i.product_id)).join(' / ')}`,p.id)));
  if(choices.length>1) $('choice-b').selectedIndex=1;
  $('weights').textContent='Estimated preference weights: '+Object.entries(task.preference_weights).map(([k,v])=>`${k.replaceAll('_',' ')} ${(v*100).toFixed(0)}%`).join(' · ')+'. Uncalibrated finite model.';
}
$('collection').addEventListener('change',()=>act(async()=>{task=null;dirty=false;await collection();$('plan').replaceChildren();$('sources').replaceChildren();$('events').replaceChildren();$('question').hidden=true;$('preference').hidden=true;$('status').textContent='Start with a reviewed task.';}));
$('task-form').addEventListener('input',()=>{if(task){dirty=true;render();}});
$('task-form').addEventListener('submit',event=>{event.preventDefault();act(async()=>{task=await api('/api/agent',{query:$('query').value,goal:goal(),catalog_kind:$('collection').value,inspection_budget:Number($('inspection-budget').value),scenario_confirmed:$('assumptions').checked});dirty=false;});});
$('next').addEventListener('click',()=>act(async()=>{task=await api('/api/agent/step',{revision:task.revision,policy:$('policy').value});}));
$('model').addEventListener('click',()=>act(async()=>{task=await api('/api/agent/model-step',{revision:task.revision});}));
for(const [id,allow] of [['permit',true],['decline',false]]) $(id).addEventListener('click',()=>act(async()=>{task=await api('/api/agent/answer',{revision:task.revision,allow_driver:allow});$('driver').checked=allow;}));
document.querySelectorAll('[data-choice]').forEach(button=>button.addEventListener('click',()=>{const a=$('choice-a').value,b=$('choice-b').value;act(async()=>{task=await api('/api/agent/preference',{revision:task.revision,a,b,choice:button.dataset.choice});});}));
await act(async()=>{const session=await api('/api/session');csrf=session.csrf_token;const status=await api('/api/agent');task=status.task;enabled=status.model_enabled;if(task)$('collection').value=task.catalog_kind;await collection();if(task){$('laptop').value=task.goal.laptop_id;$('budget').value=task.goal.budget_cents/100;$('displays').value=task.goal.displays;$('height').value=task.goal.height;$('hz').value=task.goal.hz;$('reuse').checked=task.goal.reuse_monitor;$('driver').checked=task.goal.allow_driver;$('assumptions').checked=task.scenario_confirmed;}});
