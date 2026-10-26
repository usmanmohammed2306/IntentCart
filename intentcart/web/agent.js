import {createSpatialWorkspace,presentation,animateJourney} from './spatial.js';
import {initLibrary} from './library.js';
const $=id=>document.getElementById(id),money=n=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(n/100);
const node=(tag,text,cls='')=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const spatial=createSpatialWorkspace(document.getElementById('agent-preview'));
let progressStream=null,interpreting=false;
let trainedReady=false,layoutRevision=0,layoutTimer=null,layoutSaving=false,layoutPending=false,layoutConflict=false;
const layoutStatus=node('span','', 'layout-status');spatial.host.append(layoutStatus);
async function saveLayout(){if(!csrf||layoutConflict)return;layoutPending=true;if(layoutSaving)return;layoutSaving=true;try{while(layoutPending){layoutPending=false;const snapshot=spatial.getLayout();layoutStatus.textContent='Saving…';const saved=await api('/api/studio/layout',{revision:layoutRevision,layout:snapshot});layoutRevision=saved.revision;layoutStatus.textContent='Saved';}}catch(e){layoutConflict=true;layoutStatus.textContent='Not saved · reload to review';layoutStatus.classList.add('layout-save-error');message(e.message);}finally{layoutSaving=false;}}
spatial.onChange(()=>{layoutStatus.textContent=csrf?'Unsaved':'Not saved';clearTimeout(layoutTimer);if(csrf)layoutTimer=setTimeout(saveLayout,500);});
let accountStatus={enabled:true,user:null};
let csrf='',task=null,catalog=null,research=null,enabled=false,busy=false,dirty=false,view='start',researching=false,stopRequested=false,lastError='',allowanceUsed=false;
const examples={two:'I want two Full HD screens for my MacBook Air M1, while keeping my current HDMI monitor. My budget is $350.',simple:'I want one Full HD screen for my MacBook Air M1 and a simple desk setup. My budget is $350.'};
const stages={plan:'Make a plan',investigate:'Look closer',verify:'Check the fit',stress:'Explore backups',report:'Your choice'};
const fieldNames={protocol:'Display connection',displays:'Screen support',max_height:'Resolution support',height:'Resolution support',max_hz:'Screen refresh',hz:'Screen refresh',pd_watts:'Dock charging',watts:'Power supply',count:'Cable connections',connector:'Connector',direction:'Cable direction',adapter_for:'Matching power adapter',output_connector:'Display connector',hdcp:'Protected video support',gaming:'Gaming support',minimum_os:'Minimum system version'};
function currentResearch(){return research&&task&&research.task_revision===task.revision;}
function activeRun(){return currentResearch()?research:null;}
function goal(){return {laptop_id:$('laptop').value,budget_cents:Math.round(Number($('budget').value)*100),displays:Number($('displays').value),height:Number($('height').value),hz:Number($('hz').value),reuse_monitor:$('reuse').checked,allow_driver:$('driver').checked};}
function label(id){return catalog?.products.find(p=>p.id===id)?.name||id;}
function message(text){$('message').textContent=text;$('message').hidden=false;}
function readableError(detail,status){
 lastError=typeof detail==='string'?detail:'One or more request fields were not accepted.';
 if(status===429)return /wait|minute/i.test(lastError)?'Give it a moment, then try again.':"Your AI allowance has been used. Your saved progress is still here.";
 if(/changed|stale|source|review date/i.test(lastError))return 'Your saved request has changed. Please review the details again.';
 if(/disabled|inference|gateway|connection/i.test(lastError))return 'The AI connection isn’t available right now. Your progress is saved.';
 if(status===502)return 'The assistant couldn’t finish that step. Nothing was applied. Try again when you’re ready.';
 return status===422?'Please check the request fields before continuing.':lastError;
}
async function api(path,body){
 const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});
 let result;try{result=await response.json();}catch{throw Error('The connection was interrupted. Your last saved step is still here.');}
 if(!response.ok)throw Error(readableError(result.detail,response.status));return result;
}
async function act(fn){if(busy)return;busy=true;$('message').hidden=true;render();try{await fn();}catch(error){message(error.message);}finally{busy=false;render();}}
function setView(next,focus=false){view=next;render();if(focus){const target=next==='start'?$('query'):next==='review'?$('laptop'):next==='result'?$('result-title'):$('status');target.focus({preventScroll:true});$('workspace').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}}
function fillGoal(g){$('laptop').value=g.laptop_id;$('budget').value=g.budget_cents/100;$('displays').value=g.displays;$('height').value=g.height;$('hz').value=g.hz;$('reuse').checked=g.reuse_monitor;$('driver').checked=g.allow_driver;}
async function collection(){
 catalog=await api('/api/agent/catalog?kind='+$('collection').value);
 $('laptop').replaceChildren(...catalog.laptops.map(p=>new Option(p.name.replace(' (M1, 2020)',' M1'),p.id)));
 $('catalog-notice').textContent=catalog.notice;
 $('warnings').replaceChildren(...(catalog.warnings||['All products in this collection are fictional.']).map(t=>node('li',t)));
 const curated=$('collection').value==='curated';$('assumptions-label').hidden=!curated;$('assumptions').required=curated;
 for(const option of $('displays').options)option.disabled=!curated&&Number(option.value)>2;
 if(!curated&&Number($('displays').value)>2)$('displays').value='2';
 $('collection-caption').textContent=curated?'MacBook Air example':'Fictional workstation demo';
 $('scene-caption').textContent=curated?'The MacBook Air example':'An illustrative workstation demo';
}
function revision(run,extra={}){return {run_id:run.id,revision:run.revision,...extra};}
async function investigate(){
 stopRequested=false;researching=true;view='working';
 try{
  const r=activeRun();
  if(!r||['COMPLETE','CANCELLED'].includes(r.status)||r.options.engine!==$('research-mode').value||r.options.policy!==$('research-policy').value)
   research=await api('/api/agent/research',{task_revision:task.revision,options:{engine:$('research-mode').value,policy:$('research-policy').value,counterfactuals:true}});
  if(research.status==='PAUSED')research=await api('/api/agent/research/resume',revision(research));
  watchProgress(research);
  for(let chunk=0;chunk<32&&research.status==='READY'&&!stopRequested;chunk++){
   render();research=await api('/api/agent/research/advance',revision(research,{steps:4}));task=research.task;render();
  }
  if(!stopRequested&&research.status==='COMPLETE'&&research.options.engine==='gateway'&&research.audit?.passed&&!research.brief_selection){research=await api('/api/agent/research/model-brief',revision(research));task=research.task;}
  if(stopRequested&&!['COMPLETE','CANCELLED'].includes(research.status)){research=await api('/api/agent/research/cancel',revision(research));task=research.task;}
  if(research.status==='COMPLETE')setView('result',true);
  if(research.status==='WAITING_FOR_USER'){$('question-text').tabIndex=-1;render();$('question-text').focus({preventScroll:true});}
 }finally{if(progressStream)progressStream.close();progressStream=null;researching=false;stopRequested=false;}
}
function watchProgress(run){
 if(progressStream)progressStream.close();if(!globalThis.EventSource||!run)return;
 const stream=new EventSource('/api/agent/research/events?run_id='+encodeURIComponent(run.id));progressStream=stream;
 stream.onmessage=event=>{try{const value=JSON.parse(event.data);if(value.id===research?.id&&researching&&value.inflight){$('activity-card').replaceChildren(node('span','●'),node('span','Your assistant is reading the checked details…'));}}catch{stream.close();}};
 stream.onerror=()=>stream.close();stream.addEventListener('end',()=>stream.close());
}
initLibrary(()=>csrf);
async function applyRequest(query){
 if(accountStatus.enabled&&!accountStatus.user){location.assign('/login');return;}
 if(!query.trim())throw Error('Describe a setup or a workspace change.');
 const beforeKind=$('collection').value,beforeDraft=JSON.stringify({goal:goal(),query:$('query').value,command:$('studio-command-query').value});
 let result;interpreting=true;render();try{result=await api('/api/studio/request',{query,catalog_kind:beforeKind});}finally{interpreting=false;}
 if(beforeKind!==$('collection').value)throw Error('The example collection changed. Nothing was applied.');
 if(result.kind==='scene'){spatial.perform(result.action);message('Workspace updated. Undo is available.');return true;}
 if(['requirements','plan'].includes(result.kind)&&beforeDraft!==JSON.stringify({goal:goal(),query:$('query').value,command:$('studio-command-query').value}))throw Error('You changed the draft while the agent was responding. Your edits are kept; nothing was applied.');
 if(result.kind==='requirements'){$('displays').value=String(result.displays);if(task)dirty=true;$('intake-note').textContent='Review your updated details before investigating.';setView('review',true);return true;}
 if(result.kind==='plan'){fillGoal(result.suggestions);$('driver').checked=false;$('assumptions').checked=false;$('intake-note').textContent='Your assistant drafted these details. Review before continuing.';if(task)dirty=true;setView('review',true);return true;}
 throw Error(result.message);
}
async function intake(){await applyRequest($('query').value);}

function displayValue(claim){
 if(typeof claim.value==='boolean')return claim.value?'Yes':'No';
 if(['height','max_height'].includes(claim.field))return claim.value===2160?'4K':claim.value===1080?'Full HD':String(claim.value);
 const names={displaylink:'DisplayLink software','dp-alt':'USB-C video',hdmi:'HDMI',displayport:'DisplayPort','usb-c':'USB-C','bidirectional':'Either direction','dock-to-display':'Dock to screen'};
 return (names[claim.value]||String(claim.value))+(claim.unit?' '+claim.unit:'');
}
function sourceLink(url,title='Read the source ↗'){
 if(typeof url!=='string'||!url.startsWith('https://'))return null;
 const link=node('a',title);link.href=url;link.target='_blank';link.rel='noopener noreferrer';return link;
}
function renderPlan(r){
 const container=$('plan');container.replaceChildren();
 const plan=r?.report?.outcome==='supported'&&r.audit?.passed?task?.result.plan:null;
 const verified=!!plan;
 $('result-label').textContent=verified?'Your plan':'Needs another look';
 $('result-title').textContent=verified?'This could be your setup.':'Let’s find a better fit.';
 $('result-caption').textContent=verified?'Connections and budget checked. Physical fit is unknown.':'We haven’t confirmed a complete setup yet. Your requirements and progress are saved.';
 if(!plan){
  const box=node('div',undefined,'empty-result'),img=node('img');img.src='/static/assets/studio-workstation.svg';img.alt='An illustrated workstation';
  const content=node('div');content.append(node('h2','There’s still something to resolve.'),node('p',r?.report?.open_questions?.[0]||'Try changing the budget or reviewing your preferences. We won’t fill in missing evidence or permissions for you.'));
  const button=node('button','Adjust my details ↗','primary');button.type='button';button.addEventListener('click',()=>setView('review',true));content.append(button);box.append(img,content);container.append(box);return;
 }
 const board=node('article',undefined,'result-board'),top=node('div',undefined,'result-board-top'),fit=node('div',undefined,'fit-status'),price=node('div',undefined,'result-price');
 fit.append(node('span','✓','fit-icon'),node('span','Connection checks passed'));
 price.append(node('strong',money(plan.total_cents)),node('small',task.catalog_kind==='curated'?'Example parts allowance':'Fictional demo total'));top.append(fit,price);
 const benefits=node('div',undefined,'result-benefits');for(const text of [`${task.goal.displays} screen${task.goal.displays===1?'':'s'}`,task.goal.height===2160?'4K picture':'Full HD picture',task.goal.reuse_monitor?'Keeps your monitor':'Includes new screens'])benefits.append(node('span',text));
 const bottom=node('div',undefined,'result-board-bottom');bottom.append(node('p','Select a part to explore its details. Illustration and example allowances.'));
 const spatialMount=node('div',undefined,'result-spatial-mount');spatialMount.id='result-spatial-mount';board.replaceChildren(top,benefits,spatialMount,bottom);container.append(board);
}
function disclosure(title,container){const d=node('details'),s=node('summary',title);d.append(s);container.append(d);return d;}
function renderBrief(r){
 const box=$('research-brief');box.replaceChildren();box.className='result-explanation';
 $('research-download').hidden=r?.status!=='COMPLETE';
 if(!r?.report)return;
 const report=r.report;
 if(report.claims.length){
  const explanation=disclosure('Why this setup?',box),list=node('ul');
  const ids=r.brief_selection||report.claims.map(c=>c.id);
  for(const id of ids){const claim=report.claims.find(c=>c.id===id);if(!claim)continue;const li=node('li',(fieldNames[claim.field]||claim.field.replaceAll('_',' '))+': '+displayValue(claim));li.append(node('small',label(claim.product_id)));
   for(const sid of claim.source_ids){const source=report.sources[sid];if(source?.kind==='manufacturer'){const link=sourceLink(source.url);if(link)li.append(link);}}
   list.append(li);
  }
  explanation.append(list,node('p','These checks use the product records in this example. They are not a physical hardware test.'));
  const button=node('button','See the full sources','text-button');button.type='button';button.addEventListener('click',()=>openAdvanced('sources'));explanation.append(button);
 }
 if(report.counterfactuals.length){
  const backups=disclosure('What if something changes?',box),grid=node('div',undefined,'fallback-grid');
  for(const row of report.counterfactuals){const card=node('article');card.append(node('strong',row.id==='without_driver'?'Without extra display software':'If the dock isn’t available'),node('p',row.plan?`${money(row.plan.total_cents)} in this hypothetical alternative. Review the parts before changing your plan.`:'No other setup fits with the evidence checked so far. Your current plan has not changed.'));grid.append(card);}
  backups.append(grid);
 }
 const prices=disclosure('About these estimates',box);prices.append(node('p',task.catalog_kind==='curated'?'Prices are declared planning allowances. Reused cables and owned equipment come from the scenario you reviewed. Check current prices and exact product variants before buying.':'All parts and prices in this demo are fictional. The separate checkout flow uses PayPal sandbox funds.'),node('p','This page does not place an order. Any sandbox purchase requires its own exact quote and approval.'));
}
function renderResearch(r){
 const needsConnection=$('research-mode').value==='gateway'&&!enabled;
 $('research-run').disabled=busy||!task||dirty||!!task.pending_question||needsConnection;
 $('research-run').textContent=r?.status==='PAUSED'?'Try this step again ↗':r?.status==='CANCELLED'?'Start looking again ↗':r?'Continue looking ↗':'Find my setup ↗';
 $('research-mode').disabled=$('research-policy').disabled=busy;
 $('research-stop').hidden=!researching&&!r?.inflight;$('research-stop').disabled=stopRequested;
 $('research-engine').textContent=(r?.options.engine||$('research-mode').value)==='gateway'?'Astropods model proposals · guarded tools':(r?.options.engine||$('research-mode').value)==='trained'?'Task-trained local model · validated tools':'Deterministic comparison baseline';
 $('research-heading').textContent=r?.status==='COMPLETE'?'Your research is ready.':r?.status==='WAITING_FOR_USER'?'One decision is yours.':r?.status==='CANCELLED'?'Investigation stopped.':researching?'Investigating your setup…':'Let the agent investigate.';
 $('research-note').textContent=dirty?'You changed some details. Review them before continuing.':research&&!r?'The saved request changed. Start a fresh investigation from the reviewed details.':r?.fault?'That step couldn’t be completed. Your saved progress is still here.':needsConnection?'The AI connection isn’t available. Your saved information is safe.':r?.status==='WAITING_FOR_USER'?'Choose what feels right. We’ll continue from your answer.':researching?'You can pause after the current step.':'Continue whenever you’re ready. Nothing runs in the background.';
 const graph=r?.graph||Object.entries(stages).map(([id])=>({id,status:'pending'}));
 $('research-graph').replaceChildren(...graph.map((step,i)=>{const li=node('li',undefined,step.status);li.append(node('b',step.status==='done'?'✓':String(i+1)),node('span',stages[step.id]||step.label));if(step.status==='current')li.setAttribute('aria-current','step');return li;}));
 $('research-journal').replaceChildren(...(r?.events||[]).map(e=>{const li=node('li');li.append(node('strong',e.role.replaceAll('_',' ')),node('span',' · '+e.kind.replaceAll('_',' ')+' · checkpoint '+e.index));return li;}));
 $('research-model-brief').disabled=busy||!enabled||r?.status!=='COMPLETE'||!r.audit?.passed;
 $('research-search-go').disabled=busy||!r;
 const event=r?.events.filter(e=>e.kind==='tool_result').at(-1),action=event?.data.action,source=action?.target&&catalog?.sources?.[action.target];
 let activity=action?.action==='inspect'?'Checked a product detail':action?.action==='search'?'Looked through the available parts':action?.action==='recommend'?'Found a setup that matches':action?.action==='defer'?'Marked what still needs attention':r?.model_plan?'The investigation plan is ready':'';
 if(source)activity='Checked '+(fieldNames[source.field]||source.field.replaceAll('_',' ')).toLowerCase();
 $('activity-card').replaceChildren();if(activity)$('activity-card').append(node('span','✓'),node('span',activity));
 $('connection-status').textContent=(enabled?'Model connection configured.':'Model connection is not enabled.')+(lastError?' Latest response: '+lastError:'')+(r?.fault?' '+r.fault:'');
}
function renderDetails(){
 $('export').hidden=!task;if(!task){$('sources').replaceChildren();$('events').replaceChildren();$('evidence-count').textContent='';$('remaining').textContent='';$('preference').hidden=true;return;}
 $('remaining').textContent=`${task.inspection_remaining} inspections and ${task.steps_remaining} tool actions remain in this task.`;
 $('evidence-count').textContent=` · ${task.evidence.length}`;
 $('sources').replaceChildren(...task.evidence.map(source=>{const article=node('div',undefined,'source');article.append(node('strong',`${label(source.product_id)} · ${fieldNames[source.field]||source.field}: ${source.value} ${source.unit||''}`),node('p',source.summary||source.excerpt),node('p',`${source.kind||'Fictional fixture'} · ${source.observed_on||source.observed_at||'Fixture date'} · ${source.variant}`,'fine'));const link=sourceLink(source.url);if(link)article.append(link);return article;}));
 $('events').replaceChildren(...task.events.map(event=>{const li=node('li',`${event.index}. ${event.action.action} ${event.action.target||''}`);li.append(node('small',`${event.origin} · ${event.action.reason||'Explicit human answer'}`));return li;}));
 const choices=task.comparisons;$('preference').hidden=choices.length<2;
 for(const id of ['choice-a','choice-b'])$(id).replaceChildren(...choices.map(p=>new Option(`${money(p.total_cents)} · ${p.items.map(i=>label(i.product_id)).join(' / ')}`,p.id)));
 if(choices.length>1)$('choice-b').selectedIndex=1;
 $('weights').textContent='Estimated preference weights: '+Object.entries(task.preference_weights).map(([k,v])=>`${k.replaceAll('_',' ')} ${(v*100).toFixed(0)}%`).join(' · ')+'. Uncalibrated finite model.';
}
function render(){
 const r=activeRun(),working=view==='working',result=view==='result';
 $('agent-input-panel').hidden=working||result;$('agent-results-panel').hidden=!working&&!result;
 for(const panel of document.querySelectorAll('[data-screen]'))panel.hidden=panel.dataset.screen!==view;
 document.body.dataset.view=view;document.body.classList.toggle('is-investigating',researching);
 for(const step of document.querySelectorAll('[data-journey]')){const active=step.dataset.journey===(result?'working':view),order={start:0,review:1,working:2};step.toggleAttribute('aria-current',active);if(active)step.setAttribute('aria-current','step');step.classList.toggle('is-done',order[step.dataset.journey]<order[result?'working':view]);}
 for(const button of $('task-form').querySelectorAll('button'))if(!button.closest('#agent-preview'))button.disabled=busy;
 for(const b of document.querySelectorAll('[data-screen-count]')){b.setAttribute('aria-pressed',String(b.dataset.screenCount===$('displays').value));b.disabled=busy||!![...$('displays').options].find(o=>o.value===b.dataset.screenCount)?.disabled;}
 const visualAccount=accountStatus.enabled&&!accountStatus.user?.ai_access;
 $('research-intake').disabled=busy||!trainedReady||!$('query').value.trim();$('research-intake').textContent=busy&&view==='start'?'Working…':'Create ↗';$('manual-details').hidden=false;
 $('find-setup').disabled=busy||($('research-mode').value==='gateway'&&!enabled);$('find-setup').textContent=busy?'Getting started…':'Find my setup ↗';
 $('agent-edit').disabled=busy;$('start-another').disabled=busy;$('review-back').disabled=busy;
 $('engine').textContent=busy&&view==='start'?(interpreting?'Your agent is thinking…':'Opening your workspace…'):r?.options.engine==='local'?'Comparison mode':trainedReady?'Ready · private AI':'Trained agent unavailable';
 $('result-context').textContent=task?.catalog_kind==='fixture'?'Fictional workstation demo':'MacBook Air example';
 $('review-summary').replaceChildren(...[`${$('displays').value} screen${$('displays').value==='1'?'':'s'}`,money(Math.round(Number($('budget').value||0)*100))+' budget',$('reuse').checked?'Keep your monitor':'New screens'].map(t=>node('span',t)));
 $('next').disabled=busy||!task||task.status!=='ACTIVE'||dirty;$('model').disabled=$('next').disabled||!enabled;
 $('permit').disabled=$('decline').disabled=busy||dirty;
 $('question').hidden=!task?.pending_question;$('question-text').textContent=task?.pending_question?.prompt||'';
 $('work-eyebrow').textContent=r?.status==='WAITING_FOR_USER'?'A quick check':r?.status==='CANCELLED'?'Saved for later':r?.status==='PAUSED'?'Progress saved':researching?'On it':'Your assistant is ready';
 $('status').textContent=r?.status==='WAITING_FOR_USER'?'Let’s check one thing.':r?.status==='CANCELLED'?'Your progress\nis saved.':r?.status==='PAUSED'?'We can pick up\nfrom here.':researching?'Finding the pieces\nthat fit together.':'Ready when\nyou are.';
 $('guidance').textContent=r?.status==='WAITING_FOR_USER'?'Some options need a choice only you can make.':researching?'We’re checking the details and looking at your options.':'Continue the search or refine your request.';
 renderResearch(r);renderDetails();if(result){renderPlan(r);renderBrief(r);}
 const supported=result&&r?.report?.outcome==='supported'&&r.audit?.passed?task?.result.plan:null;
 const mount=view==='working'?$('working-spatial-mount'):view==='review'?$('review-spatial-mount'):supported?$('result-spatial-mount'):$('welcome-spatial-mount');if(mount&&!mount.contains(spatial.host))mount.append(spatial.host);
 spatial.update(presentation(supported?task.goal:goal(),supported,catalog?.products||[],catalog?.laptops||[],[...(task?.evidence||[]),...Object.values(supported?r.report.sources||{}:{})]));
 if(working){const event=r?.events.filter(e=>e.kind==='tool_result').at(-1),source=catalog?.sources?.[event?.data?.action?.target],part=catalog?.products.find(p=>p.id===source?.product_id)?.kind;if(part)spatial.focus(part);}
 animateJourney(view);
}
function openAdvanced(section){const dialog=$('advanced-dialog');if(!dialog.open)dialog.showModal();if(section){const selector={connection:'#connection-details',sources:'#sources'}[section],target=selector&&document.querySelector(selector);const details=target?.closest('details');if(details)details.open=true;target?.scrollIntoView({block:'nearest'});}}
$('advanced-open').addEventListener('click',()=>openAdvanced());$('advanced-close').addEventListener('click',()=>$('advanced-dialog').close());
$('advanced-dialog').addEventListener('click',event=>{if(event.target===$('advanced-dialog')){const rect=event.target.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)event.target.close();}});
for(const button of document.querySelectorAll('[data-open-section]'))button.addEventListener('click',()=>openAdvanced(button.dataset.openSection));
$('research-intake').addEventListener('click',()=>act(intake));
$('manual-details').addEventListener('click',()=>{if(!$('query').value.trim())$('query').value=examples.two;$('intake-note').textContent='Set the details you want the assistant to use.';setView('review',true);});
$('review-back').addEventListener('click',()=>setView('start',true));$('agent-edit').addEventListener('click',()=>setView('review',true));$('start-another').addEventListener('click',()=>{$('query').value='';if(task)dirty=true;setView('start',true);});
for(const button of document.querySelectorAll('[data-screen-count]'))button.addEventListener('click',()=>{$('displays').value=button.dataset.screenCount;if(task)dirty=true;render();});
for(const button of document.querySelectorAll('[data-prompt]'))button.addEventListener('click',()=>{$('query').value=examples[button.dataset.prompt];if(task)dirty=true;$('query').focus();render();});
$('collection').addEventListener('change',()=>act(async()=>{await collection();dirty=!!task;$('assumptions').checked=false;view='start';}));
$('task-form').addEventListener('input',()=>{if(task)dirty=true;render();});
$('task-form').addEventListener('invalid',event=>{if(event.target.id==='query')setView('start');else{setView('review');const details=event.target.closest('details');if(event.target.closest('#advanced-dialog'))openAdvanced();if(details)details.open=true;}},true);
$('task-form').addEventListener('submit',event=>{event.preventDefault();act(async()=>{
 if(!$('query').value.trim()){setView('start',true);throw Error('Tell us what you’d like to set up first.');}
 task=await api('/api/agent',{query:$('query').value,goal:goal(),catalog_kind:$('collection').value,inspection_budget:Number($('inspection-budget').value),scenario_confirmed:$('assumptions').checked});research=null;dirty=false;await investigate();
});});
$('research-run').addEventListener('click',()=>act(investigate));
$('research-stop').addEventListener('click',()=>{if(!researching&&activeRun()?.inflight){act(async()=>{research=await api('/api/agent/research/cancel',revision(activeRun()));task=research.task;view='working';});return;}stopRequested=true;render();});
for(const [id,allow] of [['permit',true],['decline',false]])$(id).addEventListener('click',()=>act(async()=>{const r=activeRun();if(r?.status==='WAITING_FOR_USER'){research=await api('/api/agent/research/answer',revision(r,{allow_driver:allow}));task=research.task;}else task=await api('/api/agent/answer',{revision:task.revision,allow_driver:allow});$('driver').checked=allow;await investigate();}));
$('next').addEventListener('click',()=>act(async()=>{task=await api('/api/agent/step',{revision:task.revision,policy:$('policy').value});view='working';}));
$('model').addEventListener('click',()=>act(async()=>{task=await api('/api/agent/model-step',{revision:task.revision});view='working';}));
$('research-mode').addEventListener('change',render);
$('research-model-brief').addEventListener('click',()=>act(async()=>{research=await api('/api/agent/research/model-brief',revision(research));task=research.task;}));
for(const button of document.querySelectorAll('[data-choice]'))button.addEventListener('click',()=>{const a=$('choice-a').value,b=$('choice-b').value;act(async()=>{task=await api('/api/agent/preference',{revision:task.revision,a,b,choice:button.dataset.choice});view='working';});});
$('research-search-go').addEventListener('click',()=>act(async()=>{const result=await api('/api/agent/research/retrieve?query='+encodeURIComponent($('research-search').value)+'&limit=6');$('research-hits').replaceChildren(...result.hits.map(hit=>{const article=node('article');article.append(node('strong',hit.source.product_id+' · '+hit.source.field),node('p',hit.source.summary||hit.source.excerpt||String(hit.source.value)),node('small',hit.source_id+' · relevance '+hit.score));return article;}));if(!result.hits.length)$('research-hits').append(node('p','No matching checked evidence.','fine'));}));
const scene=$('desk-scene');scene.addEventListener('pointermove',event=>{if(matchMedia('(prefers-reduced-motion: reduce)').matches||event.pointerType==='touch')return;const rect=scene.getBoundingClientRect();scene.style.setProperty('--tilt-x',((.5-(event.clientY-rect.top)/rect.height)*4).toFixed(2)+'deg');scene.style.setProperty('--tilt-y',(((event.clientX-rect.left)/rect.width-.5)*6).toFixed(2)+'deg');});scene.addEventListener('pointerleave',()=>{scene.style.setProperty('--tilt-x','0deg');scene.style.setProperty('--tilt-y','0deg');});
for(const button of document.querySelectorAll('[data-scene-note]'))button.addEventListener('click',()=>{const screen=button.dataset.sceneNote==='screen';$('scene-story-title').textContent=screen?'More room for your work.':'One connection. Everything together.';$('scene-story-note').textContent=screen?'We’ll check which screens this setup supports.':'The dock, cables and power supply all need to fit.';});
document.querySelector('.request-card').append(document.querySelector('.privacy-note'));
try{accountStatus=await api('/api/account');}catch{message('The connection is unavailable. You can still arrange this example.');}
const member=!accountStatus.enabled||!!accountStatus.user;document.body.dataset.auth=member?'member':'guest';$('assistant-entry').hidden=!member;$('advanced-open').hidden=!member;$('studio-command-open').hidden=!member;
if(accountStatus.enabled){$('account-nav').hidden=false;$('customer-nav').hidden=!accountStatus.user;$('account-nav').textContent=accountStatus.user?'Account':'Sign in';$('account-nav').href=accountStatus.user?'/account':'/login';}
if(accountStatus.enabled&&!accountStatus.user){
 document.querySelector('.welcome-heading h1').textContent='Make room.';document.querySelector('.welcome-heading p').textContent='Arrange the example, your way.';spatial.update(presentation());
}else await act(async()=>{const session=await api('/api/session');csrf=session.csrf_token;const saved=await api('/api/agent');task=saved.task;enabled=saved.model_enabled;const workflow=await api('/api/agent/research');if(workflow.model_budget?.profile==='public-preview'){$('release-banner').hidden=false;$('release-banner').textContent='Public preview · AI actions run in the private app.';}allowanceUsed=enabled&&!workflow.model_enabled;enabled=enabled&&workflow.model_enabled;const invited=!accountStatus.enabled||!!accountStatus.user?.ai_access;if(!invited){enabled=false;const cloud=[...$('research-mode').options].find(o=>o.value==='gateway');cloud.disabled=true;}const studio=await api('/api/studio');trainedReady=studio.model.ready;layoutRevision=studio.layout.revision;spatial.setLayout(studio.layout.layout);layoutStatus.textContent=layoutRevision?'Saved':'';$('research-mode').value='trained';if(!trainedReady){$('release-banner').hidden=false;$('release-banner').textContent=studio.model.notice;}research=workflow.run;if(task)$('collection').value=task.catalog_kind;await collection();if(task){fillGoal(task.goal);$('query').value=task.query;$('assumptions').checked=task.scenario_confirmed;view=research?.status==='COMPLETE'?'result':workflow.stale||task.status!=='ACTIVE'?'review':'working';}if(research){$('research-mode').value=research.options.engine;$('research-policy').value=research.options.policy;}});

function openCommand(){if(accountStatus.enabled&&!accountStatus.user){$('account-nav').focus();return;}$('studio-command-dialog').showModal();$('studio-command-query').focus();}
$('studio-command-open').addEventListener('click',openCommand);$('studio-command-close').addEventListener('click',()=>$('studio-command-dialog').close());
$('studio-command-form').addEventListener('submit',e=>{e.preventDefault();act(async()=>{const query=$('studio-command-query').value;$('studio-command-note').textContent='Thinking…';try{await applyRequest(query);$('studio-command-dialog').close();$('studio-command-query').value='';}finally{$('studio-command-note').textContent='One change at a time. Your layout can always be undone.';}});});
addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();openCommand();}});
