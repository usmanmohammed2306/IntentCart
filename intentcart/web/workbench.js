const $=id=>document.getElementById(id);
let csrf='',task=null,data=null,busy=false,requirementsBase=null,recovery=null;
const requirementFields=[['charging','Charging target','number'],['os','OS version','text'],['connector','Display connector','text'],['evidence-age','Evidence review interval','number'],['price-age','Price review interval','number'],['tax','Tax, USD','number'],['shipping','Shipping, USD','number'],['hdcp','HDCP required','checkbox'],['gaming','Gaming suitability required','checkbox']];
const money=n=>n===null?'Unknown':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(n/100);
const text=(tag,value,className='')=>{const el=document.createElement(tag);el.textContent=value;el.className=className;return el;};
async function api(path,body){const response=await fetch(path,{credentials:'same-origin',headers:{'Content-Type':'application/json','x-csrf-token':csrf},...(body?{method:'POST',body:JSON.stringify(body)}:{})});const value=await response.json();if(!response.ok){const error=Error(typeof value.detail==='string'?value.detail:'Review the entered values and current task.');error.status=response.status;throw error;}return value;}
async function run(fn){if(busy)return;busy=true;document.querySelectorAll('button').forEach(b=>b.disabled=true);syncRequirementsControls();try{await fn();$('message').hidden=true;}catch(error){$('message').textContent=error.message;$('message').hidden=false;}finally{busy=false;document.querySelectorAll('button').forEach(b=>b.disabled=false);syncRequirementsControls();}}
function readRequirements(){return Object.fromEntries(requirementFields.map(([id,,type])=>[id,type==='checkbox'?$(id).checked:$(id).value]));}
function sameValue(id,a,b){const type=requirementFields.find(f=>f[0]===id)[2];return type==='number'&&a!==''&&b!==''?Number(a)===Number(b):a===b;}
function pendingRequirements(){
 if(recovery)return recovery;
 if(!requirementsBase||!task)return null;
 const mine=readRequirements();
 return requirementFields.some(([id])=>!sameValue(id,mine[id],requirementsBase[id]))?{base:{...requirementsBase},mine,revision:task.revision}:null;
}
function syncRequirementsControls(){
 $('requirements').querySelectorAll('input,select,button').forEach(el=>el.disabled=busy||!!recovery);
 $('draft-restore').disabled=busy||!recovery||!requirementFields.some(([id])=>!sameValue(id,recovery.mine[id],recovery.base[id])&&!sameValue(id,recovery.mine[id],requirementsBase[id]));
 $('draft-discard').disabled=busy;
}
function showRecovery(){
 $('draft-review').hidden=!recovery;
 if(recovery){
  $('draft-summary').textContent=`Your unsaved edits from revision ${recovery.revision} are safe in this tab. Compare them with revision ${task.revision}. Nothing has been resubmitted.`;
  const rows=requirementFields.filter(([id])=>!sameValue(id,recovery.mine[id],recovery.base[id])).map(([id,label,type])=>{
   const row=text('article','','draft-field');
   const display=value=>type==='checkbox'?(value?'Yes':'No'):value===''?'Unknown / empty':String(value);
   const state=sameValue(id,recovery.mine[id],requirementsBase[id])?'Already matches':sameValue(id,recovery.base[id],requirementsBase[id])?'Your edit':'Changed in both';
   const heading=text('div','','draft-field-heading');heading.append(text('strong',label),text('span',state,'fine'));
   const values=document.createElement('dl');
   for(const [name,value] of [['Before',recovery.base[id]],['Your edit',recovery.mine[id]],['Latest',requirementsBase[id]]]){const cell=document.createElement('div');cell.append(text('dt',name),text('dd',display(value)));values.append(cell);}
   row.append(heading,values);return row;
  });
  $('draft-diff').replaceChildren(...rows);
 }
 syncRequirementsControls();
}
async function edit(operation,payload={},submittedRequirements=false){
 const draft=pendingRequirements();
 try{
  const updated=await api('/api/agent/workbench',{revision:task.revision,operation,payload});
  task=updated;data=task.workbench;recovery=submittedRequirements?null:draft;render();
  if(submittedRequirements)$('draft-status').textContent='Reviewed requirements saved.';
 }catch(error){
  if(error.status===409&&draft){
   try{await load({draft,onlyIfChanged:true});}catch{/* Keep the original form and error if refreshing fails. */}
  }
  throw error;
 }
}

function products(id,values){$(id).replaceChildren(...values.map(p=>new Option(`${p.name} · ${p.variant||p.id}`,p.id)));}
function render(){
 $('content').hidden=!task;if(!task)return;
 const r=data.requirements;
 $('notice').textContent=`Revision ${task.revision} · ${data.supported_count} supported configurations / ${data.candidate_count} candidates. ${data.notice}`;
 for(const [id,value] of [['charging',r.charging_watts],['os',r.os_version],['connector',r.connector],['evidence-age',r.evidence_max_age_days],['price-age',r.price_max_age_days],['tax',r.tax_cents===null?'':r.tax_cents/100],['shipping',r.shipping_cents===null?'':r.shipping_cents/100]])$(id).value=value;
 $('hdcp').checked=r.hdcp;$('gaming').checked=r.gaming;$('monitors').value=JSON.stringify(r.owned_monitors,null,2);
 products('laptop-source',data.laptop_sources);$('laptop-source').value=task.goal.laptop_id;$('laptop-provenance').textContent=data.laptop_sources.map(p=>`${p.name} · ${p.variant} · source ${p.source_sha256.slice(0,12)} · reviewed ${p.observed_on||'fictional fixture'}`).join(' / ');
 products('variant-product',data.products);products('offer-product',data.products);products('restore-product',data.products.filter(p=>data.excluded.includes(p.id)));
 $('cf-budget').value=task.goal.budget_cents/100;$('cf-displays').value=task.goal.displays;
 $('configurations').replaceChildren(...data.configurations.slice(0,6).map(c=>{const box=text('div','','basket');box.append(text('h3',money(c.total_cents)),text('p',c.items.map(i=>`${i.quantity} × ${data.products.find(p=>p.id===i.product_id)?.name||i.product_id}`).join(' / ')),text('p',`Changed slots: ${c.changed_slots.join(', ')||'None / initial plan'}`,'fine'));const list=document.createElement('ul');for(const [name,value] of Object.entries(c.contributions))list.append(text('li',`${name.replaceAll('_',' ')}: ${value.toFixed(4)} estimated utility contribution`));box.append(list);return box;}));
 if(!data.configurations.length)$('configurations').append(text('p',`No supported plan. Review: ${data.conflicts.join(', ')||'unresolved evidence'}.`));
 $('dependencies').replaceChildren(...data.sources.map(s=>{const box=text('div','','source');box.append(text('strong',`${s.product_id} → ${s.field}`),text('p',s.checks.length?`Supports checks: ${s.checks.join(' → ')}`:'Not used by a currently supported basket','fine'),text('p',`${s.freshness.status}${s.freshness.age_days===null?'':` · ${s.freshness.age_days} days since review`}`,'fine'));return box;}));
 $('history').replaceChildren(...data.history.map((h,index)=>{const row=text('div','','source');row.append(text('p',`${index+1}. ${h.a} versus ${h.b}`));const select=document.createElement('select');select.setAttribute('aria-label',`Comparison ${index+1} answer`);select.replaceChildren(...['a','b','tie','skip'].map(c=>new Option(c,c)));select.value=h.choice;const save=text('button','Save answer');save.addEventListener('click',()=>run(()=>edit('edit_preference',{index,choice:select.value})));const remove=text('button','Remove');remove.addEventListener('click',()=>run(()=>edit('delete_preference',{index})));row.append(select,save,remove);return row;}));
 $('uncertainty').replaceChildren(...Object.entries(data.uncertainty).map(([name,v])=>text('p',`${name.replaceAll('_',' ')}: mean ${(100*v.mean).toFixed(1)}%; 5–95% particle interval ${(100*v.q05).toFixed(1)}–${(100*v.q95).toFixed(1)}%`,'fine')));$('uncertainty').append(text('p',data.uncertainty_notice,'fine'));
 $('burden').textContent=`${data.question_burden.permission_questions} permission questions in retained timeline; ${data.question_burden.retained_pairwise_answers} retained comparisons, including ${data.question_burden.skips} skips. Counts describe retained records, not unique people.`;
 $('source-id').replaceChildren(...task.evidence.map(s=>new Option(`${s.product_id} · ${s.field}`,s.source_id)));
 loadSource();$('pending').textContent=data.pending_source?JSON.stringify(data.pending_source,null,2):'No pending replacement.';$('accept-source').hidden=!data.pending_source;
 requirementsBase=readRequirements();showRecovery();
 $('changes').replaceChildren(...task.events.filter(e=>e.response?.diff).slice(-8).map(e=>{const node=document.createElement('details');node.append(text('summary',`Revision ${e.revision}: ${e.action.action}`),text('pre',JSON.stringify(e.response.diff,null,2)));return node;}));
}
function loadSource(){const source=task?.evidence.find(s=>s.source_id===$('source-id').value);$('source-record').value=source?JSON.stringify(source,null,2):'';}
async function load({draft=pendingRequirements(),onlyIfChanged=false}={}){
 const status=await api('/api/agent');
 if(onlyIfChanged&&status.task?.revision===task?.revision)return;
 // A failed/stale task read must not erase the form or an unsaved draft.
 if(!status.task&&task){throw Error(status.notice||'The task is unavailable. Your edits remain in this tab; start or restore a reviewed task before continuing.');}
 task=status.task;data=task?.workbench;recovery=draft;
 if(!task)$('notice').textContent=status.notice||'Start a reviewed task in the Evidence agent, then return here.';
 render();
 if(recovery){$('draft-status').textContent='Review your saved edits before applying requirements.';$('draft-title').focus();}
}
$('draft-restore').addEventListener('click',()=>{
 if(busy||!recovery)return;
 const draft=recovery;
 for(const [id,,type] of requirementFields){if(sameValue(id,draft.mine[id],draft.base[id]))continue;if(type==='checkbox')$(id).checked=draft.mine[id];else $(id).value=draft.mine[id];}
 recovery=null;showRecovery();$('draft-status').textContent='Your edits are back in the form. Review all requirements, then choose Apply reviewed requirements.';$('charging').focus();
});
$('draft-discard').addEventListener('click',()=>{if(busy)return;recovery=null;showRecovery();$('draft-status').textContent='Using the latest saved requirements. Your unsaved edits were discarded.';$('charging').focus();});
window.addEventListener('beforeunload',event=>{if(pendingRequirements()){event.preventDefault();event.returnValue='';}});

function form(id,fn){$(id).addEventListener('submit',e=>{e.preventDefault();run(fn);});}
form('requirements',()=>edit('requirements',{charging_watts:Number($('charging').value),os_version:$('os').value,connector:$('connector').value,hdcp:$('hdcp').checked,gaming:$('gaming').checked,evidence_max_age_days:Number($('evidence-age').value),price_max_age_days:Number($('price-age').value),tax_cents:$('tax').value===''?null:Math.round(Number($('tax').value)*100),shipping_cents:$('shipping').value===''?null:Math.round(Number($('shipping').value)*100)},true));
form('inventory',()=>edit('requirements',{owned_monitors:JSON.parse($('monitors').value)}));
form('laptop-review',()=>edit('revise_goal',{laptop_id:$('laptop-source').value}));
form('variant',()=>{const p=data.products.find(p=>p.id===$('variant-product').value);return edit('select_variant',{product_id:p.id,variant:p.variant||p.id});});
form('restore',()=>edit('restore_product',{product_id:$('restore-product').value}));
form('offer',()=>{const p=data.products.find(p=>p.id===$('offer-product').value);return edit('offer',{product_id:p.id,variant:p.variant||p.id,merchant:$('merchant').value,offer_id:$('offer-id').value,price_cents:Math.round(Number($('offer-price').value)*100),observed_on:$('offer-date').value,available:$('offer-available').checked});});
form('source-review',()=>edit('propose_source',{source_id:$('source-id').value,replacement:JSON.parse($('source-record').value),reason:$('source-reason').value}));
form('counterfactual',async()=>{$('counterfactual-result').textContent=JSON.stringify(await api('/api/agent/counterfactual',{revision:task.revision,changes:[{budget_cents:Math.round(Number($('cf-budget').value)*100),displays:Number($('cf-displays').value)}]}),null,2);});
form('clarify',async()=>{$('clarification').textContent=JSON.stringify(await api('/api/agent/clarify-query',{text:$('request-text').value}),null,2);});
form('import',()=>{if(!$('catalog-reviewed').checked)throw Error('Review the collection first.');return edit('import_catalog',{catalog:JSON.parse($('catalog-json').value),base_sha256:data.catalog_sha256,reviewed:true});});
$('withdraw').addEventListener('click',()=>run(()=>edit('withdraw_driver')));$('undo').addEventListener('click',()=>run(()=>edit('undo_preference')));$('refresh').addEventListener('click',()=>run(load));$('source-id').addEventListener('change',loadSource);$('accept-source').addEventListener('click',()=>run(()=>edit('accept_source',{proposal_id:data.pending_source.id,reviewed:true})));
await run(async()=>{csrf=(await api('/api/session')).csrf_token;await load();});
