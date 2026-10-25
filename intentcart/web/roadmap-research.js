import {updateResearch} from './interface.js';
const $=id=>document.getElementById(id);let csrf='';
const cell=(tag,value)=>{const n=document.createElement(tag);n.textContent=value;return n;};
function table(target,rows,columns){const t=document.createElement('table');t.style.fontSize='.8rem';t.style.width='100%';const head=document.createElement('tr');columns.forEach(c=>head.append(cell('th',c[0])));t.append(head);for(const row of rows){const tr=document.createElement('tr');columns.forEach(c=>tr.append(cell('td',c[1](row))));t.append(tr);}$(target).replaceChildren(t);}
async function report(kind){const response=await fetch('/api/roadmap/evaluation?kind='+kind);const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'The research report could not be loaded. Refresh after checking the saved report.');return data;}
try{const [budget,pref,session]=await Promise.all([report('budget'),report('preferences'),fetch('/api/session').then(r=>r.json())]);csrf=session.csrf_token;
 $('budget-protocol').textContent=`${budget.denominators.train_structures} training structures · ${budget.denominators.test_structures} test structures · ${budget.denominators.correlated_episodes.toLocaleString()} correlated episodes. Nine policies, four budget cuts and three shift conditions.`;
 $('budget-limit').textContent=budget.limitations;
 table('budget-results',budget.summaries,[['Shift',r=>r.shift],['Policy',r=>r.policy],['Supported mass',r=>(100*r.mean_supported_probability).toFixed(1)+'%'],['Mean cost',r=>r.mean_expected_cost.toFixed(3)]]);
 $('preference-protocol').textContent=`${pref.denominators.synthetic_profiles} synthetic profiles · ${pref.denominators.train_baskets} training baskets / ${pref.denominators.heldout_baskets} held-out baskets · ${pref.denominators.correlated_runs} correlated runs.`;
 $('preference-limit').textContent=pref.limitations;
 table('preference-results',pref.summaries,[['Tie threshold',r=>r.tie_threshold],['Initial regret',r=>r.mean_baseline_regret.toFixed(6)],['Learned regret',r=>r.mean_learned_regret.toFixed(6)]]);
 updateResearch(budget,pref);
}catch(error){$('message').textContent=error.message;$('message').hidden=false;}
$('problem').value=JSON.stringify({schema:'intentcart-acquisition/1',id:'example',revision:'1',queries:[{id:'spec',cost:1,version:'1'}],worlds:[{id:'yes',weight:1,answers:{spec:'yes'},decision:'supported-A'},{id:'no',weight:1,answers:{spec:'no'},decision:null}],initial_evidence:[]},null,2);
$('cost-preview').addEventListener('submit',async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;try{const response=await fetch('/api/research/cost-preview',{method:'POST',headers:{'Content-Type':'application/json','x-csrf-token':csrf},body:JSON.stringify({problem:JSON.parse($('problem').value),costs:JSON.parse($('costs').value),budget:Number($('budget').value)})});const value=await response.json();if(!response.ok)throw Error(value.detail);$('cost-result').textContent=JSON.stringify(value,null,2);}catch(error){$('cost-result').textContent=error.message;}finally{button.disabled=false;}});
