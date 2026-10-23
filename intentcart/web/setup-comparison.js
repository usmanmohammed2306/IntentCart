// Pure comparison of two supported configurations from one server snapshot.
// This module never changes a task, infers missing facts or grants approval.
const kinds=['dock','monitor','cable','power'];
const features=['lower_cost','no_driver','charging_capacity','dock_refresh_capacity'];
function requireValue(condition,message){if(!condition)throw Error(message);}
function amount(value){requireValue(Number.isSafeInteger(value)&&value>=0,'A current all-in price is required.');return value;}
function name(value){return String(value??'Not declared').slice(0,2000);}
function clone(value){return JSON.parse(JSON.stringify(value));}
export function compareSetups(task,aId,bId){
 requireValue(task&&Number.isSafeInteger(task.revision)&&task.revision>0&&task.workbench,'Refresh the task before comparing.');
 const data=task.workbench;
 requireValue(data.revision===task.revision&&Array.isArray(data.configurations)&&data.configurations.length<=12,'The comparison snapshot is stale or invalid.');
 requireValue(typeof aId==='string'&&typeof bId==='string'&&aId!==bId,'Choose two different supported configurations.');
 requireValue(Array.isArray(data.products)&&data.products.length<=24,'The product collection is invalid.');
 requireValue(new Set(data.products.map(p=>p.id)).size===data.products.length,'Product identities must be unique.');
 requireValue(new Set(data.configurations.map(p=>p.id)).size===data.configurations.length,'Configuration identities must be unique.');
 const products=new Map(data.products.map(p=>[p.id,p]));
 function side(id){
  const row=data.configurations.find(c=>c.id===id);
  requireValue(row&&row.checks&&Object.keys(row.checks).length>0&&Object.values(row.checks).every(v=>v===true),'Only currently supported configurations can be compared.');
  requireValue(Array.isArray(row.items)&&row.items.length>0&&row.items.length<=8,'Configuration items are invalid.');
  requireValue(new Set(row.items.map(i=>i.product_id)).size===row.items.length,'Basket product identities must be unique.');
  const items=row.items.map(i=>{
   const p=products.get(i.product_id);
   requireValue(p&&kinds.includes(p.kind)&&Number.isSafeInteger(i.quantity)&&i.quantity>0&&i.quantity<=8,'The exact component identity or quantity is invalid.');
   const unit=amount(p.price_cents);requireValue(Number.isSafeInteger(unit*i.quantity),'Component price exceeds supported limits.');
   return {product_id:p.id,name:name(p.name),variant:name(p.variant??p.id),kind:p.kind,quantity:i.quantity,unit_cents:unit,line_cents:unit*i.quantity};
  });
  const subtotal=items.reduce((sum,i)=>sum+i.line_cents,0),total=amount(row.total_cents);
  requireValue(Number.isSafeInteger(subtotal)&&total>=subtotal,'The all-in price is inconsistent with its components.');
  const contributions=Object.fromEntries(features.map(f=>{const value=row.contributions?.[f];requireValue(Number.isFinite(value),'Preference contributions are unavailable.');return [f,value];}));
  const selected=new Set(items.map(i=>i.product_id));
  const sources=(task.evidence||[]).filter(s=>selected.has(s.product_id)).map(s=>({source_id:name(s.source_id),product_id:s.product_id,field:name(s.field),value:clone(s.value??null),unit:name(s.unit),kind:name(s.kind),url:typeof s.url==='string'?s.url:null,observed_on:s.observed_on??null,freshness:clone(data.sources?.find(d=>d.source_id===s.source_id)?.freshness??{status:'not reported',age_days:null})}));
  return {id,items,subtotal_cents:subtotal,extra_cents:total-subtotal,total_cents:total,checks:clone(row.checks),contributions,sources};
 }
 const a=side(aId),b=side(bId);
 requireValue(a.extra_cents===b.extra_cents,'Shared all-in costs differ. Refresh before comparing.');
 const slots=kinds.map(kind=>{
  const left=a.items.filter(i=>i.kind===kind),right=b.items.filter(i=>i.kind===kind);
  const key=list=>JSON.stringify(list.map(i=>[i.product_id,i.quantity]).sort((x,y)=>x[0].localeCompare(y[0])));
  return {kind,a:left,b:right,changed:key(left)!==key(right),delta_cents:right.reduce((sum,i)=>sum+i.line_cents,0)-left.reduce((sum,i)=>sum+i.line_cents,0)};
 });
 return {schema:'intentcart-setup-comparison/1',revision:task.revision,catalog_sha256:name(data.catalog_sha256),source_sha256:name(task.source_sha256),a,b,delta_cents:b.total_cents-a.total_cents,slots,contribution_deltas:Object.fromEntries(features.map(f=>[f,b.contributions[f]-a.contributions[f]])),checkout_supported:false,notice:'Same-revision comparison of represented supported plans. Prices are planning declarations; preference contributions are model estimates, not measured satisfaction. Inspected source fields are not independent hardware verification. Comparison does not select a basket, record a preference or approve payment.'};
}
export function comparisonReport(comparison){
 requireValue(comparison?.schema==='intentcart-setup-comparison/1','Build a current comparison before exporting.');
 const usd=n=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(n/100);
 const lines=['IntentCart setup comparison',`Revision: ${comparison.revision}`,`Catalog identity: ${comparison.catalog_sha256}`,`Compiler identity: ${comparison.source_sha256}`,'',`A: ${comparison.a.id} — ${usd(comparison.a.total_cents)}`,`B: ${comparison.b.id} — ${usd(comparison.b.total_cents)}`,`B minus A: ${comparison.delta_cents<0?'-':'+'}${usd(Math.abs(comparison.delta_cents))}`,''];
 for(const slot of comparison.slots){lines.push(`${slot.kind}: ${slot.changed?'changed':'same'}`);for(const label of ['a','b'])lines.push(`  ${label.toUpperCase()}: ${slot[label].map(i=>`${i.quantity} × ${i.name} [${i.variant}] (${i.product_id})`).join(' / ')||'No purchase in this slot'}`);}
 lines.push('','Estimated contribution differences (B minus A):',...Object.entries(comparison.contribution_deltas).map(([k,v])=>`  ${k}: ${v.toFixed(6)}`));
 for(const label of ['a','b']){const side=comparison[label];lines.push('',`${label.toUpperCase()} supported checks:`,...Object.keys(side.checks).map(k=>`  ${k}: supported under represented rules`),`${label.toUpperCase()} inspected source fields:`);for(const s of side.sources)lines.push(`  ${s.product_id} / ${s.field}: ${JSON.stringify(s.value)} ${s.unit} | ${s.kind} | reviewed ${s.observed_on??'not dated'} | ${s.freshness.status} | ${s.url??'no external URL'}`);}
 lines.push('','Checkout authority: none',comparison.notice,'This export contains selected product/source records. Review before sharing. No query, session, credentials or feedback is included.');
 return lines.join('\n')+'\n';
}
