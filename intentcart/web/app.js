import {tradeOffs, budgetEnvelope, preferenceShape} from './insights.js';
const $ = id => document.getElementById(id);
const money = cents => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(cents/100);
const escape = value => String(value).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state, settings, csrf, activeQuote, orders=[], busy=false, paypalPromise;
let labQuote, decisionData;
let selectedAlternative;
function constellation() {
  const weights=state?.weights?.length?state.weights:[];
  const labels=['Lightness','Weather','Organization','Capacity','Comfort','Style','Price'];
  const shape=preferenceShape(weights);
  const point=(i,r)=>{const angle=-Math.PI/2+i*2*Math.PI/7;return [220+Math.cos(angle)*r,151+Math.sin(angle)*r];};
  const polygon=r=>labels.map((_,i)=>point(i,r).join(',')).join(' ');
  const points=weights.map((_,i)=>point(i,shape.radii[i]*94));
  $('preference-orbit').innerHTML=`<svg viewBox="0 0 440 300" role="img" aria-label="${weights.length?'Estimated preference profile; outer ring is '+Math.round(shape.scale*100)+' percent.':'Preference profile awaiting a mission.'}"><circle class="orbit-ring" cx="220" cy="151" r="118"/><circle class="orbit-ring outer" cx="220" cy="151" r="111"/>${[.25,.5,.75,1].map(r=>`<polygon class="radar-grid" points="${polygon(94*r)}"/>`).join('')}${labels.map((label,i)=>{const p=point(i,94),t=point(i,134);return `<line class="radar-axis" x1="220" y1="151" x2="${p[0]}" y2="${p[1]}"/><text x="${t[0]}" y="${t[1]}" text-anchor="middle">${label.toUpperCase()}</text>`;}).join('')}${weights.length?`<polygon class="radar-fill" points="${points.map(p=>p.join(',')).join(' ')}"/>${points.map(p=>`<circle class="radar-node" cx="${p[0]}" cy="${p[1]}" r="3.5"/>`).join('')}`:'<text class="radar-empty" x="220" y="155" text-anchor="middle">YOUR SIGNAL STARTS HERE</text>'}</svg>`;
  $('profile-state').textContent=weights.length?`${state.answered} CHOICES LEARNED`:'AWAITING INPUT';
  $('profile-caption').textContent=weights.length?`Estimated importance · outer ring ${Math.round(shape.scale*100)}%`:'Seven trade-offs. A model shaped by your choices.';
  $('system-context').textContent=state?.mission?`Mission v${state.version} · ${state.feasible_count} feasible · ${state.answered}/${state.question_limit} comparisons`:'CPU learning · no model API';
}
function renderTradeoff() {
  const candidates=state.ranked.slice(1),leader=state.ranked[0];
  $('tradeoff-workbench').hidden=!candidates.length;
  if(!candidates.length)return;
  if(!candidates.some(p=>p.id===selectedAlternative))selectedAlternative=candidates[0].id;
  $('compare-alternative').innerHTML=candidates.map(p=>`<option value="${escape(p.id)}" ${p.id===selectedAlternative?'selected':''}>${escape(p.name)} · ${money(p.total_cents)}</option>`).join('');
  const other=candidates.find(p=>p.id===selectedAlternative),lens=tradeOffs(leader,other,state.weights);
  const maximum=Math.max(.001,...lens.contributions.map(c=>Math.abs(c.difference)));
  $('tradeoff-content').innerHTML=`<div class="lens-legend"><span><i></i> Favors ${escape(other.name)}</span><span><i></i> Favors ${escape(leader.name)}</span></div><div class="contribution-chart" role="group" aria-label="Estimated weighted utility differences, ${escape(leader.name)} minus ${escape(other.name)}">${lens.contributions.map(c=>`<div class="contribution-row"><span>${escape(c.name)}</span><div class="difference-track"><div class="difference-half left">${c.difference<0?`<i style="width:${Math.abs(c.difference)/maximum*100}%"></i>`:''}</div><div class="difference-half right">${c.difference>0?`<i style="width:${c.difference/maximum*100}%"></i>`:''}</div></div><b>${c.difference>0?'+':''}${c.difference.toFixed(3)}</b></div>`).join('')}</div><div class="lens-summary"><div><span>ESTIMATED MODEL MARGIN</span><strong>${lens.margin>0?'+':''}${lens.margin.toFixed(3)}</strong><small>Sum before display rounding</small></div><div><span>ALL-IN PRICE DIFFERENCE</span><strong>${lens.priceDifference===0?'Same total':(lens.priceDifference>0?'+':'−')+money(Math.abs(lens.priceDifference))}</strong><small>${escape(leader.name)} vs. ${escape(other.name)}</small></div></div><p class="fine-print">An explanation of this linear model, computed from rounded preference estimates and illustrative catalog attributes. Not a satisfaction score or a causal prediction. Bar lengths share a scale within this comparison; they rescale when you switch alternatives. Shipping affects the budget, while the affordability attribute uses item price.</p>`;
}
$('compare-alternative').onchange=()=>{selectedAlternative=$('compare-alternative').value;renderTradeoff();};
function art(p, suffix='') {
  const color = /^#[0-9a-f]{6}$/i.test(p.color) ? p.color : '#386457';
  const id = escape(p.id + suffix);
  return `<svg viewBox="0 0 240 240" role="img" aria-label="Illustration of ${escape(p.name)}"><defs><linearGradient id="${id}" x1="0" x2="1" y2="1"><stop stop-color="${color}"/><stop offset="1" stop-color="#29382d"/></linearGradient></defs><path d="M78 58C65 67 62 106 61 150l10 58h19l-5-83 2-59M160 58c16 20 17 57 18 93l-11 58h-18l8-83-1-59" fill="none" stroke="${color}" stroke-width="13"/><path d="M105 43v-9c0-19 30-19 30 0v9" fill="none" stroke="#313e32" stroke-width="6"/><path d="M72 65c0-18 18-28 48-28s48 10 48 28l9 117c2 25-9 36-57 36s-59-11-57-36Z" fill="url(#${id})"/><path d="M73 89q47-18 94 0M71 185q49 9 99 0" fill="none" stroke="#ffffff35" stroke-width="1.5"/><path d="M87 55q33-13 66 0" fill="none" stroke="#ffffff40" stroke-width="2"/><path d="M81 117q39-8 78 0l4 57q-43 11-86 0Z" fill="${color}" stroke="#15271b55" stroke-width="1"/><path d="M84 122q36-7 72 0" fill="none" stroke="#e6dbc199" stroke-width="1.5"/><path d="M147 119v13" stroke="#d5c4a1" stroke-width="3" stroke-linecap="round"/><rect x="105" y="71" width="30" height="13" rx="3" fill="#d8caa5"/><path d="m115 75 5 5 5-5" stroke="#465744" fill="none" stroke-width="1.3"/><path d="M66 150h11v34H64M163 150h11l2 34h-13" fill="${color}" stroke="#26382e55"/><path d="M82 195q38 8 76 0" stroke="#ffffff20" fill="none"/></svg>`;
}
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>{$('toast').hidden=true;},8000); }
async function api(path,body) {
  const response=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();
  if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'Please check the form values and try again.');
  return data;
}
async function task(fn) {
  if(busy) return;
  busy=true; $('loading').hidden=false;
  document.querySelectorAll('button').forEach(b=>{b.dataset.wasDisabled=String(b.disabled);b.disabled=true;});
  try { await fn(); } catch(error){toast(error.message || 'The connection was interrupted. Please retry.');}
  finally {busy=false;$('loading').hidden=true; document.querySelectorAll('button').forEach(b=>{if(b.dataset.wasDisabled!==undefined){b.disabled=b.dataset.wasDisabled==='true';delete b.dataset.wasDisabled;}});if(state?.mission){$('shock-button').disabled=state.feasible_count<2;for(const id of ['lab-checkout','run-challenges','lab-receipt','check-proposal'])$(id).disabled=!state.ranked.length;}}
}
function specs(p) {
  return `<div class="specs"><span><b>${p.capacity_l}L</b> capacity</span><span><b>${p.weight_g}g</b> weight</span><span><b>${p.laptop_inches}″</b> laptop fit</span><span><b>${p.rain>=.85?'High':p.rain>=.65?'Moderate':'Light'}</b> rain protection</span><span><b>${p.organization>=.8?'High':'Moderate'}</b> organization</span><span><b>${p.comfort>=.85?'High':'Moderate'}</b> comfort</span></div>`;
}
function render() {
  constellation();
  if(!state?.mission) return;
  $('welcome').hidden=true; $('experience').hidden=false; $('preferences').hidden=false;
  const decision=state.decision;
  $('decision-status').hidden=!decision;
  if(decision){
    const labels={ASK:'One more trade-off is worth exploring.',RECOMMEND:'Ready for your review.',DEFER:'Your judgment comes first.'};
    $('decision-status').dataset.action=decision.action;
    $('decision-status').innerHTML=`<span class="section-label">${escape(decision.action)} / EXPERIMENTAL DECISION CONTROL</span><h2>${escape(labels[decision.action])}</h2><p>${escape(decision.reason)}</p><details><summary>Inspect the model estimate</summary><p>Expected regret: ${decision.expected_regret?.toFixed(4)??'unavailable'} in normalized model utility. This is not dollars or calibrated confidence. The controller uses a four-answer / eight-attempt ceiling. Deferral pauses its recommendation; you can still review and choose any feasible pack. Every payment requires your exact approval.</p></details>`;
  }
  $('weight-bars').innerHTML=state.weights.map(w=>`<div class="weight-row"><span>${escape(w.name)}</span><div class="bar"><i style="width:${Math.round(w.value*100)}%"></i></div><b>${Math.round(w.value*100)}%</b></div>`).join('');
  $('progress').textContent=`${state.answered} / ${state.question_limit} comparisons`;
  $('question-panel').hidden=!state.question; $('done-panel').hidden=!!state.question;
  $('comparison-label').textContent=state.question?'02 / A BETTER QUESTION':'02 / YOUR PREFERENCES, HEARD';
  $('done-panel').querySelector('h2').textContent=state.ranked.length?'A shortlist that listens.':'No purchase fits this world.';
  $('done-panel').querySelector('p').textContent=state.ranked.length?'Your comparisons shaped these picks. Explore the trade-offs, then choose for yourself.':'Your preferences are retained. Start a new mission or relax the limits; the agent cannot quote an infeasible purchase.';
  if(decision?.action==='DEFER'&&state.ranked.length){$('done-panel').querySelector('h2').textContent='Compare these options yourself.';$('done-panel').querySelector('p').textContent='The model has deferred its recommendation. These are estimated rankings for your manual review.';}
  if(state.question) $('comparison').innerHTML=['a','b'].map(side=>{
    const p=state.question[side];
    return `<article class="compare-card"><div class="product-art"><span class="art-index">OPTION ${side.toUpperCase()}</span>${art(p,'compare')}</div><div class="card-body"><div class="product-head"><h3>${escape(p.name)}</h3><span class="price">${money(p.price_cents)}</span></div><p class="tag">${escape(p.tag)} · ${money(p.price_cents+(p.price_cents>=8800?0:400)+(state.shipping_surcharge_cents||0))} total</p>${specs(p)}<button class="primary" data-answer="${side}">I'd carry this one <span>↗</span></button></div></article>`;
  }).join('');
  $('feasible-count').textContent=`${state.feasible_count} within your limits`;
  $('ranking').innerHTML=state.ranked.map((p,i)=>`<article class="rank-card"><div class="product-art"><span class="rank-number">${i===0?'YOUR CURRENT FRONT-RUNNER':`0${i+1} / ALTERNATIVE`}</span>${art(p,'rank')}</div><div class="card-body"><div class="product-head"><h3>${escape(p.name)}</h3><span class="price">${money(p.total_cents)}</span></div><p class="tag">Total incl. shipping · ${p.capacity_l}L · ${p.weight_g}g</p><p class="reason">Fits your ${p.reasons.map(escape).join(', ')} trade-offs.</p><div class="support">Model support: ${Math.round(p.model_win_share*100)}% · ${state.answered} comparisons</div><button class="secondary" data-quote="${p.id}">Review exact quote ↗</button></div></article>`).join('');
  $('feedback-product').innerHTML=state.ranked.map(p=>`<option value="${p.id}">${escape(p.name)}</option>`).join('');
  $('shock-button').disabled=state.feasible_count<2;
  if(labQuote?.version!==state.version)labQuote=null;
  document.querySelectorAll('[data-answer]').forEach(b=>b.onclick=()=>answer(b.dataset.answer));
  document.querySelectorAll('[data-quote]').forEach(b=>b.onclick=()=>task(()=>openQuote(b.dataset.quote)));
  renderTradeoff();
}
async function answer(choice) {await task(async()=>{state=await api('answer',{question_id:state.question.id,choice});render();});}
$('budget').oninput=()=>{$('budget-value').textContent=money(Number($('budget').value)*100).replace('.00','');};
$('mission-form').onsubmit=e=>{e.preventDefault();task(async()=>{
  state=await api('mission',{text:$('mission-text').value.trim(),budget_cents:Number($('budget').value)*100,laptop_inches:Number($('laptop').value),min_capacity_l:Number($('capacity').value),adaptive:$('adaptive-mode').checked});
  activeQuote=null;render();if(innerWidth<760)$('experience').scrollIntoView({behavior:'smooth',block:'start'});
});};
$('tie').onclick=()=>answer('tie'); $('skip').onclick=()=>answer('skip');
$('shock-button').onclick=()=>task(async()=>{const old=state.ranked[0].name;state=await api('unavailable',{product_id:state.ranked[0].id,version:state.version});render();toast(`${old} is unavailable in this simulated scenario. Your previous preferences were retained.`);});
document.querySelectorAll('dialog .close').forEach(b=>b.onclick=()=>b.closest('dialog').close());
async function openQuote(id) {
  activeQuote=await api('quotes',{product_id:id,version:state.version});
  const p=activeQuote.product;
  $('quote-content').innerHTML=`<div class="product-art">${art(p,'quote')}</div><div class="product-head"><h3>${escape(p.name)}</h3><span class="tiny">FICTIONAL SANDBOX STORE</span></div><div class="quote-line"><span>Backpack</span><span>${money(activeQuote.item_cents)}</span></div><div class="quote-line"><span>Shipping</span><span>${money(activeQuote.shipping_cents)}</span></div><div class="quote-line"><span>Sandbox tax</span><span>${money(activeQuote.tax_cents)}</span></div><div class="quote-line total"><span>Exact total (USD)</span><span>${money(activeQuote.total_cents)}</span></div><p class="fine-print">Quote valid until ${new Date(activeQuote.expires_at*1000).toLocaleTimeString()}. Changing your mission, choices, or availability invalidates it. Payment uses your PayPal sandbox buyer account.</p>`;
  $('approve').checked=false;$('approve').disabled=false;$('paypal-buttons').replaceChildren();$('check-status').hidden=true;
  $('checkout-message').textContent=settings.paypal_connected?'Approve the total to load PayPal sandbox checkout.':'PayPal sandbox is not connected yet. Shopping and preference learning are available; no simulated payment will be presented as real checkout.';
  $('quote-dialog').showModal();
}
async function loadPaypal() {
  if(window.paypal) return window.paypal;
  if(!paypalPromise) paypalPromise=new Promise((resolve,reject)=>{
    const script=document.createElement('script');
    const nonce=document.querySelector('meta[name="csp-nonce"]')?.content;if(!nonce)throw Error('Reload this page before opening PayPal.');script.nonce=nonce;script.setAttribute('data-csp-nonce',nonce);
    script.src='https://www.paypal.com/sdk/js?'+new URLSearchParams({'client-id':settings.paypal_client_id,currency:'USD',intent:'capture',components:'buttons','disable-funding':'card,credit,venmo'});
    script.onload=()=>resolve(window.paypal);script.onerror=()=>{paypalPromise=null;script.remove();reject(new Error('PayPal SDK could not load. Check your connection and sandbox app configuration.'));};document.head.append(script);
  });
  return paypalPromise;
}
$('approve').onchange=async()=>{
  $('paypal-buttons').replaceChildren();
  if(!$('approve').checked || !settings.paypal_connected) return;
  const quote=activeQuote; $('checkout-message').textContent='Loading PayPal sandbox…';
  try{
    const sdk=await loadPaypal();
    if(activeQuote!==quote||!$('approve').checked) return;
    await sdk.Buttons({style:{layout:'vertical',label:'pay',shape:'rect',height:45},
      createOrder:async()=>{
        if(!$('approve').checked||activeQuote!==quote)throw new Error('This quote needs your approval.');
        const order=await api('paypal/create',{quote_id:quote.id,approved:true});$('check-status').hidden=false;return order.id;
      },
      onApprove:async()=>{
        $('approve').disabled=true;
        try{const receipt=await api('paypal/capture',{quote_id:quote.id});$('quote-dialog').close();await showReceipts();toast(receipt.status==='COMPLETED'?'Sandbox payment verified against your approved quote.':'Payment is pending. Check your saved order status.');}
        catch(error){$('checkout-message').textContent=error.message;$('check-status').hidden=false;toast(error.message);}
      },
      onCancel:()=>{$('checkout-message').textContent='Checkout cancelled. No capture request was sent by IntentCart.';$('check-status').hidden=false;},
      onError:error=>{$('checkout-message').textContent='PayPal checkout could not finish. Check your saved order status before retrying.';$('check-status').hidden=false;toast('PayPal checkout needs a status check.');}
    }).render('#paypal-buttons');
    $('checkout-message').textContent='PayPal sandbox only. You approve inside PayPal before we request capture.';
  }catch(error){toast(error.message);$('checkout-message').textContent=error.message;}
};
$('check-status').onclick=()=>task(async()=>{const result=await api('paypal/status',{quote_id:activeQuote.id});$('checkout-message').textContent=`Saved PayPal status: ${result.status}.`;if(result.status==='COMPLETED'){$('quote-dialog').close();await showReceipts();}});
async function showReceipts() {
  orders=await api('orders');$('order-count').textContent=String(orders.length);
  $('receipt-content').innerHTML=orders.length?orders.map(o=>`<article class="receipt"><h3>${escape(o.quote.product.name)} · ${money(o.quote.total_cents)}</h3><span class="receipt-status">${escape(o.status)} · SANDBOX ONLY</span><p class="fine-print">Quote <code>${escape(o.quote_id)}</code><br>Order <code>${escape(o.order_id||'creation pending')}</code>${o.capture_id?`<br>Capture <code>${escape(o.capture_id)}</code>`:''}${o.refund_id?`<br>Refund <code>${escape(o.refund_id)}</code>`:''}</p>${o.order_id?`<button class="secondary" data-status="${escape(o.quote_id)}">Reconcile status ↻</button>`:''}${['COMPLETED','REFUND_PENDING'].includes(o.status)?`<button class="secondary" data-refund="${escape(o.quote_id)}">${o.status==='REFUND_PENDING'?'Check / retry saved refund':'Refund sandbox capture'}</button>`:''}</article>`).join(''):'<p class="muted">No PayPal orders yet. Review a quote, approve it, and complete sandbox checkout to create a receipt.</p>';
  document.querySelectorAll('[data-status]').forEach(b=>b.onclick=()=>task(async()=>{const result=await api('paypal/status',{quote_id:b.dataset.status});toast(`PayPal status: ${result.status}`);await showReceipts();}));
  document.querySelectorAll('.receipt').forEach((card,i)=>{
    const order=orders[i];
    if(order.status!=='APPROVED'||order.quote.version!==state.version||order.quote.expires_at*1000<=Date.now())return;
    const retry=document.createElement('button');retry.className='secondary';retry.textContent='Finish approved sandbox payment';
    retry.onclick=()=>task(async()=>{const result=await api('paypal/capture',{quote_id:order.quote_id});toast(`Saved payment: ${result.status}`);await showReceipts();});card.append(retry);
  });
  document.querySelectorAll('[data-refund]').forEach(b=>b.onclick=()=>task(async()=>{const result=await api('paypal/refund',{quote_id:b.dataset.refund});toast(`Sandbox refund: ${result.status}`);await showReceipts();}));
  if(!$('receipt-dialog').open)$('receipt-dialog').showModal();
}
$('orders-nav').onclick=()=>task(showReceipts);
function activateView(name){
  for(const view of ['shop','lab','evidence']){
    $(view+'-view').hidden=view!==name;
    $(view+'-nav').classList.toggle('active',view===name);
    if(view===name)$(view+'-nav').setAttribute('aria-current','page');else $(view+'-nav').removeAttribute('aria-current');
  }
  window.scrollTo({top:0,behavior:'instant'});
}
async function showLab(){
  activateView('lab');
  $('lab-empty').hidden=!!state?.mission;$('lab-active').hidden=!state?.mission;
  if(state?.mission)await refreshWorlds();
  window.scrollTo({top:0,behavior:'instant'});
}
function renderCockpit(data){
  const pick=data.baseline,budget=state.mission.budget_cents;
  const envelope=budgetEnvelope(pick?.total_cents??null,budget);
  const bestWeight=[...state.weights].sort((a,b)=>b.value-a.value)[0];
  $('mission-cockpit').innerHTML=`<section class="cockpit-pick"><div class="cockpit-art">${pick?art(pick,'cockpit'):'<span class="hold-symbol">⊘</span>'}<span class="stage-crosshair">+</span></div><div><span class="section-label">${pick?'CURRENT FRONT-RUNNER':'NO FEASIBLE PURCHASE'}</span><h2>${pick?escape(pick.name):'Hold position.'}</h2><p>${pick?'A recommendation. You keep the decision.':'Your learned preferences remain. Start a new mission to reset.'}</p><div class="cockpit-total">${pick?money(pick.total_cents):'—'} <span>${pick?'all-in sandbox total':'No spending authorized'}</span></div></div></section><section class="authority-panel" aria-label="Current budget boundary"><div class="instrument-heading"><span>SPENDING ENVELOPE</span><span class="authority-status">APPROVAL REQUIRED</span></div><div class="envelope-values"><strong>${pick?money(pick.total_cents):'No purchase'}</strong><span>/ ${money(budget)} limit</span></div><div class="budget-track"><i style="width:${envelope.used}%"></i></div><div class="envelope-caption"><span>${pick?money(envelope.remaining)+' within your limit':'No feasible option inside this boundary'}</span><span>USD · sandbox</span></div><div class="cockpit-facts"><div><span>TOP ESTIMATED PRIORITY</span><b>${bestWeight?escape(bestWeight.name):'Awaiting input'}</b></div><div><span>RETAINED EVIDENCE</span><b>${state.history.length} comparisons · v${state.version}</b></div></div></section>`;
  $('log-count').textContent=`${state.history.length} comparisons / ${(state.scenario_events||[]).length} saved interventions`;
  $('mission-log').innerHTML=`<div><h3>Comparison history</h3>${state.history.length?state.history.map((h,i)=>`<p><b>${String(i+1).padStart(2,'0')}</b><span>${escape(h.a)} / ${escape(h.b)}</span><strong>${escape({a:'Option A',b:'Option B',tie:'Tie',skip:'Skipped'}[h.choice])}</strong></p>`).join(''):'<p>No comparisons yet.</p>'}</div><div><h3>Applied worlds</h3>${(state.scenario_events||[]).length?state.scenario_events.map((event,i)=>`<p><b>${String(i+1).padStart(2,'0')}</b><span>${escape(event)}</span></p>`).join(''):'<p>Original mission. No interventions applied.</p>'}<small>The latest eight interventions are retained. These lanes are separate records, not a merged event timeline.</small></div>`;
}
async function refreshWorlds(){
  const data=await api('rehearsal');
  const baseline=data.baseline;
  renderCockpit(data);
  $('lab-status').innerHTML=`<div><span class="section-label">CURRENT DECISION</span><strong>${baseline?escape(baseline.name)+' · '+money(baseline.total_cents):'No feasible purchase'}</strong></div><div><span class="section-label">LEARNED FROM YOU</span><strong>${state.answered} comparisons · 2,048 hypotheses</strong></div><div><span class="section-label">CURRENT LIMITS</span><strong>${money(state.mission.budget_cents)} total · version ${state.version}</strong></div>`;
  $('world-grid').innerHTML=data.worlds.map((world,i)=>{const envelope=budgetEnvelope(world.pick?.total_cents??null,world.budget_cents);return `<article class="world-card ${world.pick?'':'no-purchase'}"><div class="world-index"><span>SCENARIO / 0${i+1}</span><span>${{stock:'◈',shipping:'↗',budget:'⌁',no_purchase:'⊘'}[world.kind]}</span></div><div class="world-tag">${world.pick?(world.changed_pick?'DIFFERENT PICK':'SAME PICK, REVIEW REQUIRED'):'NO PURCHASE'}</div><h3>${escape(world.label)}</h3><div class="world-pick">${world.pick?escape(world.pick.name):'Hold. Do not purchase.'}</div><div class="world-total">${world.pick?money(world.pick.total_cents):'—'}<small>${world.pick?'incl. shipping':'No feasible option'}</small></div><div class="budget-track"><i style="width:${envelope.used}%"></i></div><p>${world.feasible_count} feasible · ${money(world.budget_cents)} limit</p><span class="world-retained">✓ Comparison history retained</span><button class="secondary" data-world="${world.kind}" ${world.kind==='stock'&&!baseline?'disabled':''}>Apply this world ↗</button></article>`;}).join('');
  for(const button of document.querySelectorAll('[data-world]'))button.onclick=()=>task(async()=>{
    state=await api('scenario',{kind:button.dataset.world,version:data.source_version});
    labQuote=null;activeQuote=null;render();
    $('budget').value=state.mission.budget_cents/100;$('budget').oninput();
    $('challenge-results').replaceChildren();$('proposal-json').value='';$('proposal-result').replaceChildren();
    await refreshWorlds();toast('World applied. Your comparisons stay; earlier quotes now require fresh approval.');
  });
  $('lab-checkout').disabled=!baseline;$('run-challenges').disabled=!baseline;$('lab-receipt').disabled=!baseline;$('check-proposal').disabled=!baseline;
}
async function ensureLabQuote(){
  if(!state.ranked.length)throw new Error('There is no feasible purchase. Start a new mission to reset the simulated world.');
  if(!labQuote||labQuote.version!==state.version||labQuote.expires_at*1000<=Date.now()){
    labQuote=await api('quotes',{product_id:state.ranked[0].id,version:state.version});
  }
  return labQuote;
}
function proposalFor(quote){return {quote_id:quote.id,product_id:quote.product.id,total_cents:quote.total_cents,currency:quote.currency,version:quote.version,approved:true};}
$('lab-nav').onclick=()=>task(showLab);$('open-lab').onclick=()=>task(showLab);
$('lab-start').onclick=()=>{activateView('shop');window.scrollTo({top:0,behavior:'instant'});};
$('refresh-worlds').onclick=()=>task(refreshWorlds);
$('run-challenges').onclick=()=>task(async()=>{
  const quote=await ensureLabQuote();
  const data=await api('challenges',{quote_id:quote.id});
  $('proposal-json').value=JSON.stringify(proposalFor(quote),null,2);
  $('challenge-results').innerHTML=`<div class="challenge-banner"><strong>${data.matched} / ${data.total} scripted outcomes match expectations</strong><span>0 provider calls · 0 orders · no approval recorded</span></div><div class="challenge-grid">${data.cases.map(c=>`<div class="challenge-row"><span class="verdict ${c.eligible?'eligible':'blocked'}">${c.eligible?'ELIGIBLE CONTROL':'BLOCKED'}</span><div><b>${escape(c.label)}</b><small>${c.failed.length?escape(c.failed.join(' · ')):'Eligible only in this synthetic proposal; checkout still needs your approval.'}</small></div></div>`).join('')}</div>`;
});
$('check-proposal').onclick=()=>task(async()=>{
  const quote=await ensureLabQuote();
  if(!$('proposal-json').value.trim())$('proposal-json').value=JSON.stringify(proposalFor(quote),null,2);
  let proposal;try{proposal=JSON.parse($('proposal-json').value);}catch{throw new Error('The proposal must be valid JSON.');}
  const result=await api('proposals/check',proposal);
  $('proposal-result').textContent=result.eligible?'Eligible dry run. No approval or order was created.':'Blocked: '+result.failed.join(', ')+'. No external action taken.';
});
async function showDecision(quote){
  decisionData=await api('decision-receipt/'+quote.id);
  $('download-decision').href='/api/decision-receipt/'+encodeURIComponent(quote.id)+'?download=true';
  const snapshot=decisionData.quote.decision_snapshot;
  $('decision-content').innerHTML=`<div class="decision-summary"><strong>${escape(quote.product.name)} · ${money(quote.total_cents)}</strong><p>Frozen quote version ${quote.version} · ${snapshot?.comparisons?.length??'historical'} comparisons · ${escape(decisionData.order_status)}</p></div><p class="muted">${escape(decisionData.approval_note)}</p><div class="receipt-checks">${decisionData.current_checks.checks.map(c=>`<div><span class="${c.passed?'check-pass':'check-fail'}">${c.passed?'✓':'×'}</span> ${escape(c.label)}</div>`).join('')}</div><details><summary>Inspect frozen evidence and fingerprint</summary><pre class="json-view">${escape(JSON.stringify(decisionData,null,2))}</pre></details>`;
  $('decision-dialog').showModal();
}
$('lab-receipt').onclick=()=>task(async()=>showDecision(await ensureLabQuote()));
$('quote-receipt').onclick=()=>task(()=>showDecision(activeQuote));
$('lab-checkout').onclick=()=>task(()=>openQuote(state.ranked[0].id));
$('replay-recovery').onclick=()=>task(async()=>{
  const data=await api('lab-evidence');
  $('recovery-results').innerHTML=`<div class="challenge-banner"><strong>${data.recovery.capture_calls} fake-provider capture · ${data.recovery.final_status}</strong><span>Saved scripted run · ${escape(data.created_utc.slice(0,10))} · no live PayPal request</span></div><ol class="recovery-trace">${data.recovery.trace.map(item=>`<li><b>${escape(item.action)}</b><span>${escape(item.result)}</span></li>`).join('')}</ol><p class="fine-print">Reproduce with <code>python scripts/evaluate_lab.py</code>. This saved trace checks the application's real create/capture/status endpoints against a fake provider; it does not measure production outage recovery.</p>`;
});
async function showEvidence(){
  const data=await api('evidence');
  activateView('evidence');
  $('robustness-content').textContent='Loading the held-out stress study…';
  try{
    const stress=await api('robustness'),summary=stress.summaries,primary=stress.primary;
    $('robustness-content').innerHTML=`<section class="robustness-study"><div class="section-label">NEW / ASK, RECOMMEND OR DEFER</div><h2>What happens when the model is wrong?</h2><p>${escape(stress.conclusion)}</p><div class="evidence-grid"><div class="evidence-card"><b>${stress.personas}</b><p>Independent held-out synthetic personas, across seven declared stress families.</p></div><div class="evidence-card"><b>${stress.policy_sessions.toLocaleString()}</b><p>Policy sessions. Shared personas across policies; these are not independent people.</p></div><div class="evidence-card"><b>0</b><p>Human participants. The local pilot is implemented separately and has not been conducted.</p></div></div><div class="table-wrap"><table><thead><tr><th>Policy</th><th>All-persona candidate regret ↓</th><th>Questions</th><th>Recommendation coverage</th></tr></thead><tbody>${Object.entries(summary).map(([p,r])=>`<tr class="${p==='adaptive'?'highlight':''}"><td>${escape(p.replaceAll('_',' '))}</td><td>${r.candidate_regret.toFixed(4)}</td><td>${r.mean_questions.toFixed(2)}</td><td>${(100*r.coverage).toFixed(1)}%</td></tr>`).join('')}</tbody></table></div><p class="fine-print">Primary comparison: fixed-four recency versus fixed-four original. Paired regret reduction ${primary.reduction.toFixed(5)}, 95% persona-bootstrap interval [${primary.ci95.map(x=>x.toFixed(5)).join(', ')}]. A positive interval is required for a pooled improvement claim. Adaptive conditional quality must be read alongside coverage. Thresholds are illustrative model utility; no confidence or payment guarantee.</p><details><summary>Inspect family results, ablations and threshold sensitivity</summary><pre class="json-view">${escape(JSON.stringify({by_family:stress.by_family,sensitivity:stress.sensitivity,source_sha256:stress.source_sha256},null,2))}</pre></details><p class="fine-print">Frozen development selection precedes held-out evaluation. Reproduce with <code>python scripts/evaluate_robustness.py --stage development</code>, then <code>--stage heldout</code>. <a href="/study">Open the local consented pilot instrument ↗</a>. No recruitment or study outcome is claimed.</p></section>`;
  }catch(error){$('robustness-content').textContent='Stress evidence unavailable: '+error.message;}
  const rows=data.results||[];
  const best=rows.find(r=>r.policy==='decision');
  $('evidence-content').innerHTML=`<div class="evidence-grid"><div class="evidence-card"><b>${data.personas||0}</b><p>Simulated preference profiles per condition. Synthetic evidence, not user-study results.</p></div><div class="evidence-card"><b>4</b><p>Comparisons per mission. The question is chosen for its potential effect on the decision.</p></div><div class="evidence-card"><b>0</b><p>Participants in a validated human study so far. Real-world preference fidelity remains unproven.</p></div></div><h2>Does a better question improve the choice?</h2><p class="muted">Lower regret is better. Utility regret = best feasible utility − selected utility under the simulated user's hidden weights. Results below are measured, not promised.</p><div class="table-wrap"><table><thead><tr><th>Question policy</th><th>Mean regret</th><th>Top-pick agreement</th><th>Comparisons</th></tr></thead><tbody>${rows.map(r=>`<tr class="${r.policy==='decision'?'highlight':''}"><td>${escape({decision:'Decision-aware (IntentCart)',uncertainty:'Maximum answer uncertainty',random:'Random comparisons',static:'Intake only'}[r.policy]||r.policy)}</td><td>${r.mean_regret.toFixed(4)}<br><small>95% bootstrap CI ${r.regret_ci.map(n=>n.toFixed(4)).join(' – ')}</small></td><td>${(r.top1_agreement*100).toFixed(1)}%</td><td>${r.questions}</td></tr>`).join('')}</tbody></table></div><p class="fine-print">${escape(data.description||'Run the evaluation script to generate evidence.')} Seed ${data.seed||'—'}. Query time on the evaluated machine: median ${data.query_ms?.median?.toFixed(1)||'—'} ms, p95 ${data.query_ms?.p95?.toFixed(1)||'—'} ms. The same linear/logistic assumptions generate and learn these synthetic choices; this favors the model and does not establish real-world performance. ${escape(data.conclusion||'')}</p><div class="method"><section><h3>The method, without the magic.</h3><ol><li>Represent 24 fictional packs with seven explicitly specified attributes. Filter by total budget, laptop fit, and capacity.</li><li>Maintain 2,048 hypotheses about nonnegative user preference weights. Weak keyword-based intake adjusts the prior.</li><li>Update hypothesis weights from each choice using a noisy pairwise likelihood.</li><li>Choose the comparison with the largest expected increase in the best posterior-mean feasible utility.</li><li>Rank feasible products, explain their weighted contributions, and require an exact quote plus approval before PayPal capture.</li></ol></section><section><h3>What this does and doesn't establish.</h3><p>The learning core runs locally on CPU with no model API bill. It uses an existing Bayesian active preference-learning approach. Intake is deterministic keyword matching, not an LLM. One-step query selection is approximate under finite particles and a linear utility model.</p><p>Ties use a heuristic likelihood; skips add no evidence. Color taste, nonlinear needs, changing preferences, and missing attributes remain limitations. Feedback storage is optional; it is not silently counted as a validated study.</p><p>PayPal is sandbox-only. Channel3, if connected, searches real products but does not put arbitrary retailers' items through this store's checkout. No paid subscription is required for the core.</p><p>Reproduce: <code>python scripts/evaluate.py --personas 120 --seed 2026</code>. See repository documentation for assumptions, negative payment tests, and deployment limits.</p></section></div>`;
  window.scrollTo({top:0,behavior:'smooth'});
}
$('evidence-nav').onclick=()=>task(showEvidence);$('method-link').onclick=()=>task(showEvidence);
$('shop-nav').onclick=()=>activateView('shop');
$('discover-open').onclick=()=>{
  $('discover-dialog').showModal();
  const enabled=settings.channel3_connected&&settings.channel3_calls_remaining>0;
  $('discover-search').disabled=!enabled;
  if(!settings.channel3_connected)$('discover-results').textContent='Channel3 has not been connected. No external searches are sent until a sponsor API key is configured.';
  else if(!enabled)$('discover-results').textContent='External searches are paused: the local request ceiling is reached. No sponsor credits will be used. Preference learning and PayPal sandbox checkout remain available.';
};
$('discover-form').onsubmit=e=>{e.preventDefault();task(async()=>{const result=await api('discover',{query:$('discover-query').value.trim()});settings.channel3_calls_remaining=result.calls_remaining;$('discover-search').dataset.wasDisabled=String(result.calls_remaining<=0);$('discover-results').innerHTML=result.products.length?result.products.map(p=>`<article class="receipt"><h3>${escape(p.title)}</h3>${p.price?`<p><b>${money(p.price.amount*100)}</b> <span class="fine-print">Offer at retrieval · excludes shipping/tax · verify at retailer</span></p>`:''}<p class="muted">${escape(p.description)}</p>${p.url?`<a href="${escape(p.url)}" target="_blank" rel="noopener noreferrer">View at retailer ↗</a>`:''}<p class="fine-print">${escape(p.notice)}</p></article>`).join(''):'No matching products returned.';});};
$('feedback-form').onsubmit=e=>{e.preventDefault();task(async()=>{await api('feedback',{consent:$('feedback-consent').checked,product_id:$('feedback-product').value,rating:Number($('feedback-rating').value),comment:$('feedback-comment').value});toast('Thank you. Your consented feedback was saved locally.');$('feedback-form').reset();});};
$('command-open').onclick=()=>$('command-dialog').showModal();
document.querySelectorAll('[data-command]').forEach(button=>button.onclick=()=>{
  $('command-dialog').close();
  const action=button.dataset.command;
  if(action==='shop'){activateView('shop');window.scrollTo({top:0,behavior:'instant'});}
  else if(action==='lab')task(showLab);
  else if(action==='evidence')task(showEvidence);
  else if(action==='receipts')task(showReceipts);
});
document.addEventListener('keydown',event=>{
  if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){
    // Never put a navigation modal above an active approval or receipt dialog.
    if(document.querySelector('dialog[open]'))return;
    event.preventDefault();$('command-dialog').showModal();return;
  }
  if(event.metaKey||event.ctrlKey||event.altKey||event.repeat||busy||!$('choice-shortcuts').checked||$('shop-view').hidden||!state?.question||document.querySelector('dialog[open]'))return;
  if(event.target.closest('input,textarea,select,[contenteditable]'))return;
  const choice={'1':'a','2':'b',t:'tie',s:'skip'}[event.key.toLowerCase()];
  if(choice){event.preventDefault();answer(choice);}
});
async function boot(){
  const session=await api('session');csrf=session.csrf_token;settings=session.config;state=session.state;
  constellation();
  $('welcome-art').innerHTML=art({id:'welcome-a',name:'Metro Pack',color:'#386457'},'hero')+art({id:'welcome-b',name:'Drift Pack',color:'#d3946b'},'hero');
  if(state.mission){$('mission-text').value=state.mission.text;$('adaptive-mode').checked=!!state.mission.adaptive;$('budget').value=state.mission.budget_cents/100;$('budget').oninput();$('laptop').value=state.mission.laptop_inches;$('capacity').value=state.mission.min_capacity_l;render();}
  orders=await api('orders');$('order-count').textContent=String(orders.length);
  if(location.pathname==='/evidence')await showEvidence();
  if(location.pathname==='/lab')await showLab();
}
boot().catch(e=>toast('Could not load your session: '+e.message));
