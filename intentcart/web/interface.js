// Presentation only: navigation, summaries and progressive disclosure. No API calls or storage.
import {tools} from './decision-tools.js';
const $=id=>document.getElementById(id),node=(tag,text='',cls='')=>{const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n;};
const money=n=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(n/100);
export function componentCards(items,products){const gallery=node('div','','component-gallery');gallery.replaceChildren(...items.map(item=>{const p=products.find(p=>p.id===item.product_id),card=node('article','','visual-component'),img=node('img');img.src='/static/assets/studio-'+(p?.kind==='monitor'?'display':p?.kind||'dock')+'.svg';img.alt='';const content=node('div');content.append(node('small',p?.kind||'Component'),node('h4',p?.name||item.product_id),node('span',`${item.quantity} × ${money(p?.price_cents||0)}`));card.append(img,content);return card;}));return gallery;}
const panelIds=['overview','requirements','compare','sources','tools'];
let activePanel='overview',editingAgent=false,lastAgentTask=null;
function openPanel(id,focus=false){
 if(!panelIds.includes(id))return;
 activePanel=id;
 for(const panel of document.querySelectorAll('[data-workspace-panel]'))panel.hidden=panel.dataset.workspacePanel!==id;
 for(const tab of document.querySelectorAll('.workspace-nav [role=tab]')){const current=tab.dataset.workspaceTarget===id;tab.setAttribute('aria-selected',String(current));tab.tabIndex=current?0:-1;}
 if(focus){const tab=$('workspace-tab-'+id);tab?.focus({preventScroll:true});}
}
function metric(value,label,caption){const box=node('article','','metric');box.append(node('strong',value),node('span',label),node('small',caption));return box;}
export function updateWorkbench(task){
 if(!$('overview-metrics'))return;
 if(!task){$('overview-caption').textContent='Start an evidence task to see your options.';return;}
 const w=task.workbench,options=w.configurations,first=options[0];
 $('notice').textContent=`Revision ${task.revision} · Planning only`;
 $('overview-caption').textContent=options.length?`${options.length} returned setups to explore. Nothing is selected automatically.`:'No supported setup yet. Review your requirements or source details.';
 $('overview-metrics').replaceChildren(metric(String(options.length),'Returned setups','From this loaded revision'),metric(money(task.goal.budget_cents),'Your budget','Declared planning limit'),metric(String(task.evidence.length),'Observed fields','Not independent verification'));
 $('overview-price').textContent=first?money(first.total_cents):'No setup yet';
 $('overview-components').replaceChildren(...(first?.items||[]).map(item=>{const p=w.products.find(p=>p.id===item.product_id),card=node('article','','visual-component'),img=node('img');img.src='/static/assets/studio-'+(p?.kind==='monitor'?'display':p?.kind||'dock')+'.svg';img.alt='';const content=node('div');content.append(node('small',p?.kind||'Component'),node('h4',p?.name||item.product_id),node('span',`${item.quantity} × ${money(p?.price_cents||0)}`));card.append(img,content);return card;}));
 if(!first)$('overview-components').append(node('p','Adjust settings or resolve missing evidence to see components.','fine'));
 for(const button of document.querySelectorAll('[data-workspace-target=compare]:not([role=tab])'))button.disabled=!options.length;
 openPanel(activePanel);
}
export function updateAgent(task,{dirty=false,busy=false}={}){
 if(!$('agent-preview'))return;
 if(!task){editingAgent=false;lastAgentTask=null;}else if(!dirty&&lastAgentTask!==task){editingAgent=false;lastAgentTask=task;}
 const editing=!task||editingAgent||dirty;
 $('agent-input-panel').hidden=!editing;
 $('agent-preview').hidden=!!task&&!editing;
 $('agent-results-panel').hidden=!task;
 $('agent-edit').hidden=editing;
 $('agent-edit').disabled=busy;const active=task?.status==='ACTIVE';$('next').hidden=!active;const tech=document.querySelector('.technical-controls');if(tech)tech.hidden=!active;
 const layout=$('agent-input-panel').parentElement;layout.classList.toggle('agent-has-result',!!task&&!editing);
 if(!task)return;
 const stages=[['Request','Reviewed settings'],['Evidence','Local inspection'],['Options','Supported setups']],index=task.status==='RECOMMENDED'?2:1;
 $('agent-progress').replaceChildren(...stages.map(([label,caption],n)=>{const step=node('div','','progress-stage');step.dataset.state=n<index?'done':n===index?'current':'waiting';if(n===index)step.setAttribute('aria-current','step');step.append(node('b',n<index?'✓':String(n+1).padStart(2,'0')),node('span',label),node('small',caption));return step;}));
 $('agent-result-summary').replaceChildren(metric(money(task.goal.budget_cents),'Budget','Declared limit'),metric(String(task.evidence.length),'Observed fields','Local records'),metric(String(task.workbench?.configurations?.length||0),'Returned setups','Represented checks'));

}
function icon(kind){const paths={budget:'M4 7h16v12H4z M4 7V5h13v2 M15 11h5v4h-5z',backup:'M5 8a8 8 0 1 1-1 8 M5 8V3 M5 8h5 M12 8v5l3 2',preferences:'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6',sources:'M6 3h9l4 4v14H6z M14 3v5h5 M9 12h7 M9 16h7',snapshot:'M4 5h16v14H4z M8 9h8 M8 13h5 M8 22h8',all:'M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h6v6h-6z'};const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),p=document.createElementNS(svg.namespaceURI,'path');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');p.setAttribute('d',paths[kind]);svg.append(p);return svg;}
if($('workspace-overview')){
 for(const b of document.querySelectorAll('[data-workspace-target]'))b.addEventListener('click',()=>openPanel(b.dataset.workspaceTarget,true));
 const tabs=[...document.querySelectorAll('.workspace-nav [role=tab]')];tabs.forEach((tab,n)=>tab.addEventListener('keydown',event=>{let next;if(['ArrowRight','ArrowDown'].includes(event.key))next=(n+1)%tabs.length;else if(['ArrowLeft','ArrowUp'].includes(event.key))next=(n+tabs.length-1)%tabs.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=tabs.length-1;else return;event.preventDefault();openPanel(tabs[next].dataset.workspaceTarget,true);}));
 const topics=[['budget','Budget & cost','Understand the numbers','cost'],['backup','Backup plans','Explore changes and outages','outage'],['preferences','Your priorities','Compare the trade-offs','preference'],['sources','Source review','Trace the supporting details','source'],['snapshot','Snapshots & receipts','Review changes over time','snapshot'],['all','All analysis tools',`${tools.length} local analyses`,'']];
 $('workspace-topics').replaceChildren(...topics.map(([kind,title,desc,search])=>{const b=node('button','','topic-card');b.type='button';b.append(icon(kind),node('strong',title),node('span',desc),node('i','↗'));b.addEventListener('click',()=>{const disclosure=document.querySelector('.decision-disclosure');disclosure.open=true;const field=$('decision-tool-search');field.value=search;field.dispatchEvent(new Event('input',{bubbles:true}));field.focus();});return b;}));
 $('draft-restore')?.addEventListener('click',()=>openPanel('requirements'));
 openPanel('overview');
}
if($('agent-edit')&&!document.body.classList.contains('guided-agent'))$('agent-edit').addEventListener('click',()=>{editingAgent=true;$('agent-input-panel').hidden=false;$('agent-preview').hidden=false;$('agent-edit').hidden=true;$('agent-input-panel').parentElement.classList.remove('agent-has-result');$('query').focus();});

export function updateResearch(budget,pref){
 if(!$('budget-visual'))return;
 const label=node('label','Scenario condition'),select=node('select');select.setAttribute('aria-label','Research scenario condition');for(const value of [...new Set(budget.summaries.map(row=>row.shift))]){const option=node('option',({original:'Original conditions',prior:'Changed prior',cost:'Changed costs'})[value]||value);option.value=value;select.append(option);}label.append(select);const bars=node('div','','policy-bars');
 const names={finite_exact:'Budget-aware exact reference',unrestricted_exact:'Unrestricted exact reference',finite_student_2:'Learned policy · 2 structures',finite_student_4:'Learned policy · 4 structures',finite_student_8:'Learned policy · 8 structures',finite_student_12:'Learned policy · 12 structures',unrestricted_student:'Unrestricted learned policy',no_budget_feature:'Without budget feature',no_budget_teacher:'Without budget-aware teacher',no_information_features:'Without information features'};
 const render=()=>bars.replaceChildren(...budget.summaries.filter(row=>row.shift===select.value).map(row=>{const line=node('div','','policy-row'),track=node('div','','policy-track'),bar=node('i');bar.style.width=(100*row.mean_supported_probability).toFixed(3)+'%';track.setAttribute('aria-hidden','true');track.append(bar);line.append(node('span',names[row.policy]||row.policy),track,node('b',(100*row.mean_supported_probability).toFixed(1)+'%'));return line;}));select.addEventListener('change',render);render();$('budget-visual').replaceChildren(node('p','Mean supported probability under the declared finite prior. Synthetic tasks, not customer outcomes.','fine'),label,bars);
 const cards=node('div','','preference-metrics');for(const row of pref.summaries){const box=node('article','','metric');box.append(node('small','Tie threshold '+row.tie_threshold),node('strong',row.mean_learned_regret.toFixed(6)),node('span','Learned mean regret'),node('small','Initial: '+row.mean_baseline_regret.toFixed(6)));cards.append(box);}$('preference-visual').replaceChildren(node('p','Synthetic preference diagnostics. Lower regret is better; this is not measured human satisfaction.','fine'),cards);
}
