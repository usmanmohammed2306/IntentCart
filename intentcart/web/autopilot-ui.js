// One explicit, local AI action. Results are proposals, never approval or payment.
// Combine only identical display checks. The full passport/export is unchanged.
export function compactPassportChecks(checks,workspace,planning={}){
 const rows=[],seen=new Map();
 for(const check of checks){
  let goal=(planning.goals||[]).find(g=>g.id===check.id);
  if(check.id==='passport_budget')goal={kind:'budget',value:workspace.budget_cents};
  else if(check.id==='passport_native_displays')goal={kind:'native_displays',value:workspace.items.filter(i=>i.kind==='monitor').length};
  else if(['passport_identity','passport_connections','passport_surface_fit','passport_availability'].includes(check.id))goal={kind:check.kind,value:true};
  const key=goal?JSON.stringify([check.kind,goal.value??null,goal.value2??null,goal.item_id||'',goal.category||'',goal.state_id||'',check.status,check.reason,!!check.required]):'id:'+check.id;
  const prior=seen.get(key);
  if(prior){prior.ids.push(check.id);prior.names.push(check.text);}
  else{const row={check,ids:[check.id],names:[check.text]};seen.set(key,row);rows.push(row);}
 }
 return rows;
}

export function attachAutopilot({current,api,notice,apply,measure,desk,changeScreens,planning,signedIn,research,manualChecks}){
 const $=id=>document.getElementById(id),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 let pending=null,result=null,source='',passport=null,passportInput='',reviewOnly=false,costTimer=null;
 function wire(){const c=current(),w=structuredClone(c.workspace);w.items=w.items.map(i=>Object.fromEntries(['id','kind','name','model','owned','price_cents','dimensions','pose','ports','ports_confirmed','locked','color'].map(k=>[k,i[k]])));if(c.team_id)w.connections=[];return {workspace:w,team_id:c.team_id||'',request_id:c.request_id||'',revision:c.revision||0,fingerprint:c.fingerprint||''};}
 const fullSnapshot=()=>JSON.stringify({design:wire(),planning:wire().team_id?null:planning()});
 function button(text,fn){const b=el('button',text);b.type='button';b.onclick=()=>Promise.resolve().then(fn).catch(e=>{notice(e.message);const error=el('p',e.message,'helper');error.setAttribute('role','alert');$('autopilot-result').append(error);});return b;}
 function render(){
  clearTimeout(costTimer);
  const host=$('autopilot-result');host.replaceChildren();$('autopilot-motion').hidden=!pending;
  $('autopilot-title').textContent=pending?(reviewOnly?'Checking your setup…':'Finding a better setup…'):reviewOnly?'What works. What’s missing.':result?.status==='READY_FOR_REVIEW'?'Room for everything.':'Let’s close the gaps.';
  if(pending){host.append(el('p','Your setup stays unchanged.','helper'));return;}
  if(!result)return;
  if(passport){
   if(!reviewOnly&&result.candidate&&passport.blockers.length)$('autopilot-title').textContent=passport.blockers.length===1&&passport.blockers[0].check==='connections'?'Layout ready. Connection needed.':'Layout ready. Review the checks.';
   host.append(el('h3','Setup Passport','passport-heading'));
   const usedOffers=planning().offers.filter(o=>passport.cost.rows.some(r=>r.offer_id===o.id)),expiries=usedOffers.map(o=>o.expires_at).filter(n=>Number.isFinite(n));if(expiries.length){const earliest=Math.min(...expiries),checked=passport;costTimer=setTimeout(()=>{if(passport!==checked)return;host.replaceChildren(el('p','These prices expired. Research current prices before deciding.','helper'));passport=null;result=null;},Math.max(1,(earliest-Date.now()/1000)*1000));}

   if(passport.cost.total_minor!==null&&passport.cost.total_minor!==undefined){const w=wire().workspace,total=passport.cost.total_minor,budget=w.budget_cents,money=n=>new Intl.NumberFormat('en-US',{style:'currency',currency:w.currency}).format(n/100),box=el('section',undefined,'passport-budget');box.append(el('small','Complete estimate'),el('strong',money(total)));if(budget!==null&&budget!==undefined){const bar=el('progress');bar.max=Math.max(1,budget);bar.value=Math.min(total,bar.max);bar.setAttribute('aria-label','Budget used');box.dataset.over=String(total>budget);box.append(bar,el('small',money(budget)+' budget · '+money(Math.abs(budget-total))+(total>budget?' over':' remaining')));}if(planning().offers.some(o=>o.return_note?.includes('user-reviewed')))box.append(el('small','Includes reviewed store charges'));host.append(box);}

   const grid=el('div',undefined,'passport-grid');
   for(const row of compactPassportChecks(passport.checks,wire().workspace,planning())){const check=row.check,tile=el('div',undefined,'passport-tile');tile.dataset.state=check.status;tile.dataset.checks=row.ids.join(' ');tile.title=row.names.join(' · ')+' — '+check.reason;tile.append(el('b',['met','qualified'].includes(check.status)?'✓':check.status==='unmet'?'!':'?'),el('small',check.text));grid.append(tile);}host.append(grid);
   for(const item of passport.nodes.filter(i=>i.identity!=='linked'||i.needs_measurement).slice(0,8)){const row=el('div',undefined,'passport-item');row.append(el('span',item.name),button(item.identity!=='linked'?'Find model':'Measure',()=>{$('autopilot-dialog').close();if(item.identity!=='linked')research(item.id);else measure(item.id);}));host.append(row);}
   if(passport.questions.length){const routes=el('details');routes.append(el('summary','Connection gaps'));for(const q of passport.questions)routes.append(el('p',q));host.append(routes);}
   if(passport.routes.length){const routes=el('details');routes.append(el('summary',passport.routes.length+' supported routes'));for(const route of passport.routes)routes.append(el('p',route.basis));host.append(routes);}
   for(const option of passport.alternatives){const tile=el('p',undefined,'passport-scope');tile.textContent=option.label+' · connections '+option.connections+' · fit '+option.physical;host.append(tile);}
   const evidence=el('details');evidence.append(el('summary','Evidence & scope'),el('p',passport.scope));for(const issue of passport.source_issues||[])evidence.append(el('p',issue.message));for(const item of passport.nodes){evidence.append(el('strong',item.name));for(const s of item.sources){if(!s.url?.startsWith('https://'))continue;const a=el('a','Manufacturer ↗');a.href=s.url;a.target='_blank';a.rel='noopener noreferrer';evidence.append(a);}}host.append(evidence);
   host.append(button('Export setup passport',()=>{if(fullSnapshot()!==source)throw Error('The setup changed. Check it again before exporting.');if(usedOffers.some(o=>o.expires_at!==null&&o.expires_at!==undefined&&Date.now()/1000>o.expires_at))throw Error('These prices expired. Check current prices before exporting.');const blob=new Blob([JSON.stringify(passport,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download='intentcart-setup-passport.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}));
  }
  if(reviewOnly){host.append(button('Requirements & manual connections',()=>{$('autopilot-dialog').close();manualChecks();}));return;}
  const stages=el('div',undefined,'agent-stages');for(const [icon,text]of [['◈','Inspect'],['✧','Plan'],['⌗','Check']]){const n=el('span');n.append(el('b',icon),el('small',text));stages.append(n);}host.append(stages);
  if(result.candidate){const preview=button('Preview layout',()=>{if(fullSnapshot()!==source)throw Error('The setup changed. Ask again before applying.');apply(result.candidate);$('autopilot-dialog').close();});preview.className='primary';host.append(preview);}
  else{
   const names=new Map(wire().workspace.items.map(i=>[i.id,i.name]));
   if(!wire().workspace.surface.width||!wire().workspace.surface.depth)host.append(button('Set desk size',()=>{$('autopilot-dialog').close();desk();}));
   for(const id of result.missing_items){host.append(button('Measure '+(names.get(id)||'item'),()=>{$('autopilot-dialog').close();measure(id);}));}
   if(!result.missing_items.length)host.append(el('p',result.placement.status==='search_limit'?'This layout needs a broader search.':result.placement.status==='no_layout_in_search'?'Try fewer items, a larger desk or a different arrangement.':'The agent paused. Review the setup before trying again.','helper'));
  }
  if(result.alternatives.length){const grid=el('div',undefined,'autopilot-options');for(const option of result.alternatives){const card=button('',()=>{if(fullSnapshot()!==source)throw Error('The setup changed. Ask again.');$('autopilot-dialog').close();return changeScreens(option.screens);});card.className='autopilot-option';card.append(el('strong',option.screens+' '+(option.screens===1?'screen':'screens')),el('b',option.total_cents===null?'Quote needed':'$'+(option.total_cents/100).toFixed(2)),el('small',option.reuse_count+' reused · '+option.purchase_units+' to buy'));card.title=option.ready?'Review this alternative as a new draft':'This alternative still needs the indicated checks';grid.append(card);}host.append(el('h3','What if?'),grid);}
  const why=el('details');why.append(el('summary','Why this plan'),el('p',result.scope));for(const e of result.events)why.append(el('p',({read_setup:'Read equipment',recommend:'Model chose layout planning',inspect:'Model chose inspection',search:'Model chose research',defer:'Model deferred',clarify:'Model requested clarification',arrange_footprints:'Searched measured layouts',inspect_measurements:'Checked missing measurements',verify_footprints:'Rechecked footprint constraints'}[e.tool]||e.tool)));
  host.append(why);
 }
 async function open(){
  reviewOnly=false;
  if(!$('autopilot-dialog').open)$('autopilot-dialog').showModal();
  if(pending){render();return;}
  if(!signedIn()){notice('Sign in to use the agent. Your manual setup stays here.');$('autopilot-dialog').close();return;}
  const body=wire(),snapshot=fullSnapshot();if(!body.workspace.items.length){notice('Add your equipment first.');$('autopilot-dialog').close();return;}
  if(result&&result.status!=='CHECKED'&&source===snapshot){render();return;}
  result=null;passport=null;source=snapshot;pending=(async()=>{if(!body.team_id){passport=await api('/api/equipment/check',{workspace:body.workspace,planning:planning()});}return api('/api/setup/autopilot',{...body,client_id:crypto.randomUUID().replaceAll('-','')});})();render();
  try{result=await pending;}catch(e){notice(e.message);$('autopilot-title').textContent='Your setup is safe.';$('autopilot-result').replaceChildren(el('p',e.message,'helper'));}
  finally{pending=null;$('autopilot-motion').hidden=true;if(result)render();}
 }
 async function check(){if(pending){if(!$('autopilot-dialog').open)$('autopilot-dialog').showModal();return;}if(!signedIn()){notice('Sign in to check exact sources. Manual editing stays available.');return;}if(wire().team_id){manualChecks();return;}reviewOnly=true;source=fullSnapshot();result={status:'CHECKED'};passport=null;$('autopilot-dialog').showModal();pending=api('/api/equipment/check',{workspace:wire().workspace,planning:planning()});render();try{passport=await pending;}catch(e){notice(e.message);$('autopilot-result').replaceChildren(el('p',e.message));result=null;}finally{pending=null;$('autopilot-motion').hidden=true;if(result)render();}}
 async function suggest(allowed=()=>true){
  if(!signedIn())throw Error('Sign in to use Autopilot.');
  if(pending)throw Error('A check is already running.');
  const body=wire(),snapshot=fullSnapshot();
  if(!body.workspace.items.length)throw Error('Add equipment or describe what you need.');
  const next=await api('/api/setup/autopilot',{...body,client_id:crypto.randomUUID().replaceAll('-','')});
  if(fullSnapshot()!==snapshot)throw Error('Setup changed; the earlier layout was discarded.');
  if(!allowed())throw Error('Autopilot stopped or the setup changed.');
  if(next.candidate){apply(next.candidate);return {applied:true,result:next};}
  return {applied:false,result:next};
 }
 $('autopilot-close').onclick=()=>$('autopilot-dialog').close();return {open,check,suggest};
}
