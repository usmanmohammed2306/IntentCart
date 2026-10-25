import { isDraftDirty, canQuote, getGuideState, getSceneEvidence } from './missions-state.js';
import { validityCards } from './validity-view.js';
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = c => new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'}).format(c / 100);
let csrf, config, catalog, mission, activeQuote, busy = false, paypalPromise, modelAvailable = false;
let timer, selectedPart = 'dock', scenario = false, currentTab = 'setup';
let flowStep = 'brief', reviewedText = $('goal-text').value.trim(), tourIndex = -1, inspecting = false, pendingReviewFocus = false;
const needsReview = () => $('goal-text').value.trim() !== reviewedText;
function toast(text) { $('toast').textContent = text; $('toast').hidden = false; clearTimeout(timer); timer = setTimeout(() => $('toast').hidden = true, 6000); }
async function api(path, body) {
  const r = await fetch('/api/' + path, {method:body === undefined ? 'GET' : 'POST', headers:{'Content-Type':'application/json', 'x-csrf-token':csrf || ''}, body:body === undefined ? undefined : JSON.stringify(body)});
  let data; try { data = await r.json(); } catch { throw Error('The server did not return a usable response. Reload and reconcile any saved order.'); }
  if (!r.ok) throw Error((Array.isArray(data.detail) ? data.detail.map(e => e.msg).join('; ') : data.detail) || 'Request could not complete.');
  return data;
}
const dirty = () => isDraftDirty(mission, goal(), $('goal-text').value);
function syncControls() {
  const changed = dirty();
  $('interpret').disabled=busy||!modelAvailable;
  $('interpret-local').disabled=busy;
  $('draft-banner').hidden = !changed;
  $('apply-draft').textContent = needsReview() ? 'Review request →' : 'Update setup →';
  document.body.classList.toggle('draft-dirty', changed);
  $('quote').disabled = !canQuote(mission, changed, busy);
  $('investigate').disabled = busy || changed || !mission?.result.investigations.some(a => a.could_improve_cost);
  document.querySelectorAll('[data-exclude],[data-inspect],[data-relax]').forEach(b => b.disabled = busy || changed);
  document.querySelectorAll('[data-workspace-choice]').forEach(b => b.disabled = busy || changed);
  $('compile').disabled = busy || !catalog || needsReview();
  $('compile').innerHTML = busy ? 'Building…' : needsReview() ? 'Review your request first' : mission ? 'Update this setup <span>→</span>' : 'Build this setup <span>→</span>';
  $('start-fresh').disabled = busy || !catalog || needsReview();
  $('scenario-toggle').disabled = busy || changed || !mission?.result.plan;
  $('discovery-form').querySelector('[type=submit]').disabled = busy || !config?.channel3_calls_remaining;
  syncSpatialControls();
  syncSpatialState();
  syncGuidance();
}
async function task(fn) {
  if (busy) return;
  busy = true; document.body.classList.add('is-working'); $('workspace').setAttribute('aria-busy','true');
  const controls = [...document.querySelectorAll('button,input,select,textarea')].filter(x => !x.disabled);
  controls.forEach(x => x.disabled = true); syncControls();
  try { await fn(); } catch(e) { toast(e.message); }
  finally { controls.forEach(x => { if (x.isConnected) x.disabled = false; }); busy = false; document.body.classList.remove('is-working'); $('workspace').setAttribute('aria-busy','false'); syncControls(); if(pendingReviewFocus){pendingReviewFocus=false;focusReviewedFields();} }
}
function goal() { return {laptop_id:$('laptop').value, budget_cents:Math.round(Number($('budget').value)*100), displays:Number($('displays').value), height:Number($('height').value), hz:Number($('hz').value), reuse_monitor:$('reuse').checked, allow_driver:$('driver').checked}; }
function fillGoal(g) {
  $('laptop').value = g.laptop_id; $('budget').value = g.budget_cents/100; $('budget-range').value = g.budget_cents/100; $('budget-value').textContent = money(g.budget_cents);
  $('displays').value = g.displays; $('height').value = g.height; $('hz').value = g.hz; $('reuse').checked = g.reuse_monitor; $('driver').checked = g.allow_driver;
}
function focusReviewedFields() { if(flowStep!=='brief')return; $('laptop').focus({preventScroll:true}); $('laptop').scrollIntoView({block:'nearest',behavior:'auto'}); }
function reviewGoalFields() { setFlowStep('brief'); $('brief-settings').open=true; if(busy)pendingReviewFocus=true;else focusReviewedFields(); }
function draftChanged() { if (dirty()) invalidateQuote(); stopTour(); syncControls(); }
const item = id => catalog.products.find(p => p.id === id);
const names = {dock:'Dock', monitor:'Display', cable:'Cable kit', power:'Power supply', laptop:'Existing laptop'};
const asset = kind => '/static/assets/studio-' + (kind === 'monitor' ? 'display' : kind) + '.svg';
function invalidateQuote() { activeQuote = null; $('approve').checked = false; $('paypal-buttons').replaceChildren(); if ($('quote-dialog').open) $('quote-dialog').close(); }
function selectTab(name, focus = false) {
  if(focus) $('plan-details').open=true;
  currentTab = name;
  document.querySelectorAll('[data-tab]').forEach(b => { const selected = b.dataset.tab === name; b.setAttribute('aria-selected', String(selected)); b.tabIndex = selected ? 0 : -1; if (selected && focus) b.focus(); });
  for (const name of ['setup','evidence','activity']) $('view-'+name).hidden = name !== currentTab;
  $('scenario-toggle').hidden = name !== 'setup';
}
function closeInspector(restoreFocus = false) {
  inspecting=false; $('part-inspector').hidden=true;
  if(restoreFocus) {
    const target=[document.querySelector(`.component-strip [data-part="${selectedPart}"]`),$('spatial-stage'),$('plan-title'),$('step-explore')].find(element=>element && !element.disabled && element.getClientRects().length && getComputedStyle(element).visibility!=='hidden' && element.getAttribute('aria-hidden')!=='true');
    target?.focus({preventScroll:true});
  }
}
function selectPart(kind) {
  selectedPart = kind;
  spatial?.selectPart(kind);
  document.querySelectorAll('[data-part]').forEach(b => { const active = b.dataset.part === kind; b.classList.toggle('selected',active); b.setAttribute('aria-pressed',String(active)); });
  document.querySelectorAll('[data-card]').forEach(b => b.classList.toggle('selected',b.dataset.card === kind));
  const p = mission?.result.plan;
  $('part-inspector').hidden=!p || !inspecting;
  if (!p) return;
  const selected = p.items.find(i => item(i.product_id).kind === kind);
  const product = selected && item(selected.product_id);
  let title, detail, price;
  if (kind === 'laptop') { title = catalog.laptops.find(l => l.id === mission.goal.laptop_id).name.split(' (')[0]; detail = 'Your existing device · included in the compatibility check'; price = 'Already owned'; }
  else if (product) { title = product.name; detail = `${selected.quantity} × ${money(product.price_cents)} · ${names[kind]} · fictional specification checked`; price = money(selected.quantity * product.price_cents); }
  else { title = 'Your existing monitor'; detail = 'Full HD · 60 Hz · reused from your brief'; price = 'Already owned'; }
  $('part-inspector').innerHTML = `<img src="${asset(kind)}" alt=""><div><b>${esc(title)}</b><p>${esc(detail)}</p></div><div class="inspector-price"><strong>${esc(price)}</strong><p>${product ? 'Included in total' : 'No new purchase'}</p></div><button id="part-close" aria-label="Close component details">×</button>`;
  $('part-close').onclick=()=>closeInspector(true);
}
function eventDetail(e) {
  if (e.kind === 'requirements' && e.detail && typeof e.detail === 'object') {
    const g = e.detail;
    return `${g.displays} display${g.displays === 1 ? '' : 's'} · ${g.height === 2160 ? '4K' : 'Full HD'} at ${g.hz} Hz · ${money(g.budget_cents)} budget · ${g.reuse_monitor ? 'existing monitor retained' : 'new displays'} · ${g.allow_driver ? 'driver permitted' : 'no driver permission'}`;
  }
  if (e.kind === 'exclude') return `${item(e.detail)?.name || 'Component'} excluded. Compatibility checked again.`;
  if (e.kind === 'inspect') {
    const product = catalog.products.find(p => p.observations?.some(o => o.source_id === e.detail));
    const observation = product?.observations.find(o => o.source_id === e.detail);
    return product ? `${product.name} · ${observation.field.replaceAll('_',' ')} specification checked.` : 'Local specification checked; compatibility and price recomputed.';
  }
  return 'Built from your reviewed requirements.';
}
function render() {
  invalidateQuote(); stopTour(); inspecting=false; $('plan-details').hidden=false; $('empty').hidden = true; $('result').hidden = false; fillGoal(mission.goal); $('goal-text').value = mission.text; reviewedText = mission.text.trim();
  $('revision').textContent = 'REV ' + String(mission.revision).padStart(2,'0');
  const r = mission.result, p = r.plan;
  $('validity-summary').innerHTML = validityCards(r.validity).map(c => `<div><small>${esc(c.title)}</small><b class="${c.tone === 'good' ? 'passed' : ''}">${esc(c.label)}</b></div>`).join('');
  $('plan-title').textContent = p ? 'Your setup.' : r.status === 'NEEDS_EVIDENCE' ? 'One detail to check.' : 'Let’s adjust the plan.';
  $('plan-state').textContent = p ? 'YOUR WORKSPACE' : 'PLAN STATUS';
  $('plan-subtitle').textContent = p ? `${mission.goal.displays} display${mission.goal.displays === 1 ? '' : 's'} · ${mission.goal.height === 2160 ? '4K' : 'Full HD'} · ${mission.goal.hz} Hz · one cable to your laptop` : 'No complete basket is ready. Review the open questions or adjust your brief.';
  $('plan-badge').textContent = p ? 'Supported in demo catalog' : r.status === 'NEEDS_EVIDENCE' ? 'EVIDENCE NEEDED' : 'REVIEW REQUIREMENTS';
  $('plan-price').hidden = !p; $('plan-price').textContent = p ? money(p.total_cents) : '';
  $('candidate-count').textContent = `${r.feasible_count} OF ${r.candidate_count} BASKETS FIT`;
  $('hotspots').hidden = !p; $('part-inspector').hidden = !p; $('graph').hidden = !p;
  $('graph').innerHTML = p ? `<b>Laptop</b><i>→</i><b>Dock</b><i>→</i><b>Cables</b><i>→</i><b>${mission.goal.displays} display${mission.goal.displays > 1 ? 's' : ''}</b><i>·</i><span>Power → dock → laptop</span>` : '';
  $('part-count').textContent = p ? p.items.length : '0'; $('event-count').textContent = mission.events.length;
  $('basket').innerHTML = p ? p.items.map(i => { const a = item(i.product_id); const retained = mission.previous_plan?.some(pr => pr.product_id === i.product_id && pr.quantity === i.quantity); return `<article class="part-card" data-card="${a.kind}"><button class="part-select" data-part="${a.kind}" aria-label="Inspect ${esc(a.name)}"><div class="part-image"><span class="part-label">${names[a.kind].toUpperCase()}</span><img src="${asset(a.kind)}" alt="">${mission.previous_plan ? `<span class="retained ${retained ? '' : 'changed'}">${retained ? '✓ Retained' : '↗ Updated'}</span>` : ''}</div><div class="part-copy"><b>${esc(a.name)}</b><small>${i.quantity} × ${money(a.price_cents)} · fixture catalog</small><div class="part-price">${money(a.price_cents*i.quantity)}<span>↗</span></div></div></button><button class="remove" data-exclude="${esc(a.id)}" ${scenario ? '' : 'hidden'} aria-label="Simulate ${esc(a.name)} unavailable">Make unavailable ↗</button></article>`; }).join('') : '<p class="helper">Resolve a missing specification or revise a requirement to see a complete basket.</p>';
  const oldTotal = mission.previous_plan?.reduce((sum,i) => sum + item(i.product_id).price_cents * i.quantity, 0);
  $('repair-banner').hidden = !(p && mission.objective_mode === 'repair' && mission.previous_plan);
  $('repair-banner').innerHTML = p ? `<span><b>${p.changed_slots} component slot${p.changed_slots === 1 ? '' : 's'} changed.</b> ${p.items.filter(i => mission.previous_plan?.some(pr => pr.product_id === i.product_id && pr.quantity === i.quantity)).length} of ${p.items.length} selected slots retained.</span><span>${money(oldTotal || 0)} → <b>${money(p.total_cents)}</b></span>` : '';
  $('totals').innerHTML = p ? `<div class="total-top"><span>Your complete setup</span><strong>${money(p.total_cents)}</strong></div><div class="budget-track" aria-hidden="true"><span style="width:${Math.min(100,100*p.total_cents/mission.goal.budget_cents)}%"></span></div><div class="total-caption"><b>${money(mission.goal.budget_cents-p.total_cents)} under budget</b><span>of ${money(mission.goal.budget_cents)}</span></div><p class="fine">Shipping &amp; sandbox tax: $0.00</p>` : '<h3>No payable plan yet.</h3><p class="helper">A complete compatible basket comes first.</p>';
  const useful = r.investigations.filter(a => a.could_improve_cost);
  $('next-title').textContent = useful.length ? (p ? 'Could this setup cost less?' : 'Resolve the missing specifications.') : p ? 'The plan is ready for your review.' : 'Your next move: adjust the brief.';
  $('next-description').textContent = useful.length ? `${useful.length} missing specification${useful.length === 1 ? '' : 's'} may unlock another basket. Inspect local evidence to find out. Savings are not guaranteed.` : p ? 'No actionable lower-cost evidence remains in this finite catalog. Explore why the selected parts work together.' : 'Check the conflicting requirements above. Each suggested change stays under your control.';
  $('investigate').textContent = useful.length ? (p ? 'Check potential savings ↗' : 'Check missing evidence ↗') : 'No further checks available';
  $('checks').innerHTML = Object.entries(catalog.constraints).map(([key,label]) => `<div class="check-row"><span class="${p?.checks[key] === true ? 'passed' : ''}" aria-hidden="true">${p?.checks[key] === true ? '✓' : '○'}</span><span>${esc(label)}${p ? '' : ' · not established'}</span></div>`).join('');
  $('investigations').innerHTML = r.investigations.length ? r.investigations.map(a => `<article class="investigation-card"><b>${esc(item(a.product_id).name)}: ${esc(a.field.replaceAll('_',' '))}</b><p>Relevant to ${a.unlocks_candidates} potentially viable baskets, starting at ${money(a.optimistic_total_cents)}. Other unknown facts may block them. This is a hypothetical cost bound.</p><button data-inspect="${esc(a.source_ids[0])}">Inspect specification ↗</button></article>`).join('') : '<p class="helper">No actionable missing facts remain. Contradictory revisions stay excluded.</p>';
  $('conflict').hidden = !!p;
  $('conflict').innerHTML = !p ? `<h3>${r.status === 'NEEDS_EVIDENCE' ? 'Check the evidence before changing your goal.' : 'These requirements don’t fit together.'}</h3>${r.conflict_core.length ? `<p>These requirements conflict within this catalog:</p><ul>${r.conflict_core.map(k => `<li>${esc(catalog.constraints[k] || 'Available parts must fill every required slot')}</li>`).join('')}</ul>` : ''}<p class="helper">Choose a change to apply it. Driver permission always requires your explicit choice.</p>${r.relaxations.map(a => `<button data-relax="${esc(a.field)}" data-value='${esc(JSON.stringify(a.value))}'>${esc(relaxLabel(a))}</button>`).join('')}` : '';
  $('rejected').innerHTML = r.rejected.map(a => `<div class="diagnostic-row"><b>${a.items.map(i => esc(item(i.product_id).name)).join(' + ')} · ${money(a.total_cents)}</b><p>${a.failed.length ? 'Failed: '+a.failed.map(k => esc(catalog.constraints[k])).join('; ') : 'No known contradiction; evidence is incomplete.'}</p>${a.unknown.length ? `<p>Unknown / conflicting: ${a.unknown.map(esc).join(', ')}</p>` : ''}</div>`).join('');
  $('facts').innerHTML = p ? Object.entries(p.facts).map(([key,f]) => `<div class="diagnostic-row"><code>${esc(key)}</code><p>${esc(JSON.stringify(f.value))} ${esc(f.unit || '')} · ${esc(f.status)}</p>${f.sources.map(s => `<button class="source-button" data-source="${esc(s)}">View source ↗</button>`).join('')}</div>`).join('') : '<p class="helper">No approved plan. Inspect missing evidence or examine rejected candidates.</p>';
  const eventNames = {compile:'A new setup was built', inspect:'A specification was checked', exclude:'A component became unavailable', requirements:'Your requirements changed'};
  $('events').innerHTML = mission.events.slice().reverse().map(e => `<div class="activity-row"><span class="activity-dot">${e.revision}</span><div><b>${esc(eventNames[e.kind] || e.kind)}</b><p>${esc(eventDetail(e))}</p><small>REVISION ${String(e.revision).padStart(2,'0')}</small></div></div>`).join('');
  $('objective').textContent = r.objective + ' Evidence establishes consistency with fictional specifications only.';
  const preferenceChoices = r.preference_choices || [];
  $('mission-preferences').hidden = preferenceChoices.length < 2;
  for (const id of ['workspace-a','workspace-b']) $(id).replaceChildren(...preferenceChoices.map(c =>
    new Option(`${money(c.total_cents)} · ${c.items.map(i => item(i.product_id).name).join(' / ')}`, c.id)));
  if (preferenceChoices.length > 1) $('workspace-b').selectedIndex = 1;
  document.querySelectorAll('[data-part]').forEach(b => b.onclick = () => { stopTour(); inspecting=true; selectPart(b.dataset.part); $('scene').scrollIntoView({block:'center',behavior:motionPreference.matches?'auto':'smooth'}); spatial?.setAutoRotate(false); spatial?.focusPart(b.dataset.part); orbiting = false; topView = false; syncSpatialControls(); });
  document.querySelectorAll('[data-exclude]').forEach(b => b.onclick = () => task(async () => { if (dirty()) throw Error('Update your setup before trying availability changes.'); mission = await api('missions/exclude',{revision:mission.revision,product_id:b.dataset.exclude}); scenario = false; render(); toast(mission.result.plan ? 'Plan repaired. Retained components and price changes are shown.' : 'No complete replacement fits. Review the remaining constraints.'); }));
  document.querySelectorAll('[data-inspect]').forEach(b => b.onclick = () => task(async () => { if (dirty()) throw Error('Update your setup before checking evidence.'); mission = await api('missions/inspect',{revision:mission.revision,source_id:b.dataset.inspect}); render(); toast('Specification checked. Compatibility and cost recomputed.'); }));
  document.querySelectorAll('[data-source]').forEach(b => b.onclick = () => task(async () => { const s = await api('missions/sources/'+encodeURIComponent(b.dataset.source)); $('source-title').textContent = item(s.product_id).name; $('source-excerpt').textContent = s.excerpt; $('source-meta').textContent = `${s.kind} · variant ${s.variant} · observed ${s.observed_at} · ${s.url}`; $('source-dialog').showModal(); }));
  document.querySelectorAll('[data-relax]').forEach(b => b.onclick = () => task(async () => { if (dirty()) throw Error('Update your setup before applying a suggested change.'); mission = await api('missions/revise',{revision:mission.revision,goal:{...mission.goal,[b.dataset.relax]:JSON.parse(b.dataset.value)}}); render(); toast('Requirement updated. Review the new basket.'); }));
  $('scenario-note').hidden = !scenario; $('scenario-toggle').setAttribute('aria-pressed',String(scenario));
  selectPart(selectedPart); selectTab(currentTab); syncControls();
}
function relaxLabel(a) { return a.field === 'budget_cents' ? `Set budget to ${money(a.value)}` : a.field === 'allow_driver' ? 'Permit a DisplayLink driver' : a.field === 'reuse_monitor' ? 'Replace the existing monitor' : a.field === 'height' ? 'Use Full HD' : a.field === 'hz' ? 'Use 60 Hz' : 'Use one display'; }
function focusPlan() { setFlowStep('explore'); $('plan-title').focus({preventScroll:true}); if (matchMedia('(max-width:780px)').matches) $('plan-title').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',block:'start'}); }
$('investigate').onclick = () => task(async () => { if (dirty()) throw Error('Update your setup before checking evidence.'); mission = await api('missions/investigate',{revision:mission.revision}); render(); toast('Relevant local specifications checked. No external calls.'); });
document.querySelectorAll('[data-workspace-choice]').forEach(button => button.onclick = () => {
  const a=$('workspace-a').value, b=$('workspace-b').value;
  task(async () => {
    if(dirty()) throw Error('Review your edited requirements before teaching preferences.');
    mission=await api('missions/preference',{revision:mission.revision,a,b,choice:button.dataset.workspaceChoice});
    render(); toast('Preference recorded. Hard constraints remain enforced; review the new exact quote.');
  });
});
$('budget').oninput = () => { $('budget-range').value = $('budget').value; $('budget-value').textContent = money(Number($('budget').value)*100); };
$('budget-range').oninput = () => { $('budget').value = $('budget-range').value; $('budget-value').textContent = money(Number($('budget').value)*100); };
$('goal-form').addEventListener('input',draftChanged); $('goal-form').addEventListener('change',draftChanged);
$('goal-form').addEventListener('invalid', e => {
  setFlowStep('brief');
  for(let parent=e.target.parentElement;parent;parent=parent.parentElement) {
    if(parent.tagName==='DETAILS') parent.open=true;
  }
  e.target.focus({preventScroll:true});
  e.target.scrollIntoView({block:'nearest',behavior:'auto'});
},true);
$('goal-form').onsubmit = e => { e.preventDefault(); if (needsReview()) { toast('Review your request first, then check the extracted settings.'); $('interpret').focus(); return; } task(async () => { mission = await api(mission ? 'missions/revise' : 'missions',mission ? {revision:mission.revision,text:$('goal-text').value,goal:goal()} : {text:$('goal-text').value,goal:goal()}); currentTab = 'setup'; scenario = false; render(); focusPlan(); toast(mission.result.plan ? 'Your setup is ready to review.' : 'The setup needs attention. Review the open questions and suggested changes.'); }); };
$('apply-draft').onclick = () => { setFlowStep('brief'); if(needsReview()) $('interpret').click(); else $('goal-form').requestSubmit(); };
$('empty-build').onclick = () => setFlowStep('brief',true);
$('start-fresh').onclick = () => { if (needsReview() || !$('goal-form').reportValidity()) return; task(async () => { mission = await api('missions',{text:$('goal-text').value,goal:goal()}); scenario = false; currentTab = 'setup'; render(); focusPlan(); toast('Fresh plan created. Saved orders remain; previous quotes are invalidated.'); }); };
$('interpret-local').onclick = () => task(async () => { const a = await api('missions/interpret',{query:$('goal-text').value}); fillGoal({...goal(),...a.suggestions}); $('compiler-note').textContent = a.notice; reviewedText = $('goal-text').value.trim(); draftChanged(); reviewGoalFields(); toast('Requirements extracted. Review the fields before building.'); });
$('interpret').onclick=()=>task(async()=>{const a=await api('agent/research/intake',{query:$('goal-text').value,catalog_kind:'fixture'});fillGoal({...goal(),...a.suggestions});$('compiler-note').textContent=a.notice;reviewedText=$('goal-text').value.trim();draftChanged();reviewGoalFields();toast('AI proposal ready. Review every field; software permission is off.');});
$('import-proposal').onclick = () => task(async () => { let proposed; try { proposed = JSON.parse($('proposal').value); } catch { throw Error('Paste one valid JSON goal object.'); } const result = await api('missions/proposal',{goal:proposed}); fillGoal(result.goal); $('compiler-note').textContent = result.notice; reviewedText = $('goal-text').value.trim(); draftChanged(); reviewGoalFields(); toast('Proposal loaded for review. Driver permission reset.'); });
$('scenario-toggle').onclick = () => { scenario = !scenario; $('scenario-note').hidden = !scenario; $('scenario-toggle').setAttribute('aria-pressed',String(scenario)); document.querySelectorAll('[data-exclude]').forEach(b => b.hidden = !scenario); };
$('show-investigations').onclick = () => { selectTab('evidence',true); };
const tabs = [...document.querySelectorAll('[data-tab]')];
tabs.forEach((b,i) => { b.onclick = () => selectTab(b.dataset.tab); b.onkeydown = e => { let n; if (e.key === 'ArrowRight') n = (i+1)%tabs.length; if (e.key === 'ArrowLeft') n = (i+tabs.length-1)%tabs.length; if (e.key === 'Home') n = 0; if (e.key === 'End') n = tabs.length-1; if (n !== undefined) { e.preventDefault(); selectTab(tabs[n].dataset.tab,true); } }; });
$('quote').onclick=()=>task(async()=>{if(!canQuote(mission,dirty(),false))throw Error('Update your setup before reviewing a quote.');activeQuote=await api('missions/quotes',{revision:mission.revision});$('approve').checked=false;$('approve').disabled=false;$('paypal-buttons').replaceChildren();$('check-status').hidden=true;$('quote-content').innerHTML=activeQuote.basket.map(i=>`<div class="quote-line"><span>${i.quantity} × ${esc(item(i.product_id).name)}</span><span>${money(item(i.product_id).price_cents*i.quantity)}</span></div>`).join('')+`<div class="quote-line"><span>Shipping + sandbox tax</span><span>$0.00</span></div><div class="quote-line total"><span>Exact total · USD</span><span>${money(activeQuote.total_cents)}</span></div><p class="fine">Fictional merchant, sandbox funds only. No goods or delivery. Expires ${new Date(activeQuote.expires_at*1000).toLocaleTimeString()}. Changing the plan invalidates this quote.</p>`;$('approval-label').textContent=`I approve this exact ${money(activeQuote.total_cents)} fictional sandbox basket.`;$('checkout-message').textContent=config.paypal_connected?'Check approval to load PayPal sandbox. Buyer approval is a separate step.':'Sandbox credentials are absent. The quote and decision receipt remain available; no payment will be simulated.';$('receipt-export').href='/api/decision-receipt/'+activeQuote.id+'?download=true';stopTour(); flowStep = 'review'; syncGuidance(); $('quote-dialog').showModal();});
async function loadPaypal(){if(window.paypal)return window.paypal;if(!paypalPromise)paypalPromise=new Promise((resolve,reject)=>{const s=document.createElement('script');s.src='https://www.paypal.com/sdk/js?'+new URLSearchParams({'client-id':config.paypal_client_id,currency:'USD',intent:'capture',components:'buttons','disable-funding':'card,credit,venmo'});s.onload=()=>resolve(window.paypal);s.onerror=()=>{paypalPromise=null;s.remove();reject(Error('Sandbox SDK unavailable. Reconcile any saved order before retrying.'));};document.head.append(s);});return paypalPromise;}
$('approve').onchange=async()=>{ $('paypal-buttons').replaceChildren();if(!$('approve').checked||!config.paypal_connected)return;const q=activeQuote;try{const sdk=await loadPaypal();if(activeQuote!==q||!$('approve').checked)return;await sdk.Buttons({style:{layout:'vertical',shape:'rect',label:'pay',height:45},createOrder:async()=>{if(activeQuote!==q||!$('approve').checked||dirty())throw Error('Exact quote approval is required.');const o=await api('paypal/create',{quote_id:q.id,approved:true});$('check-status').hidden=false;return o.id;},onApprove:async()=>{$('approve').disabled=true;try{const r=await api('paypal/capture',{quote_id:q.id});$('checkout-message').textContent='Verified sandbox status: '+r.status;await showReceipts();}catch(e){$('checkout-message').textContent=e.message;$('check-status').hidden=false;}},onCancel:()=>{$('checkout-message').textContent='Buyer cancelled. No capture requested.';$('check-status').hidden=false;},onError:()=>{$('checkout-message').textContent='Checkout interrupted. Reconcile the saved order before retrying.';$('check-status').hidden=false;}}).render('#paypal-buttons');}catch(e){toast(e.message);$('checkout-message').textContent=e.message;}};
$('check-status').onclick=()=>task(async()=>{const r=await api('paypal/status',{quote_id:activeQuote.id});$('checkout-message').textContent='Verified sandbox status: '+r.status;});
async function showReceipts(){const orders=await api('orders');$('receipt-list').innerHTML=orders.length?orders.map(o=>`<article class="receipt-card"><b>${esc(o.quote.product.name)} · ${money(o.quote.total_cents)}</b><p>${esc(o.status)} · sandbox<br>Order ${esc(o.order_id||'creation pending')}<br>Capture ${esc(o.capture_id||'none')}<br>Refund ${esc(o.refund_id||'none')}</p>${o.order_id?`<button data-reconcile="${esc(o.quote_id)}">Reconcile status</button>`:''}${o.status==='APPROVED'?`<button data-capture="${esc(o.quote_id)}">Finish approved sandbox payment</button>`:''}${['COMPLETED','REFUND_PENDING'].includes(o.status)?`<button data-refund="${esc(o.quote_id)}">${o.status==='REFUND_PENDING'?'Retry saved refund':'Refund sandbox capture'}</button>`:''}<a class="quiet" href="/api/decision-receipt/${encodeURIComponent(o.quote_id)}?download=true">Decision receipt ↓</a></article>`).join(''):'<p class="helper">No orders in this session. Quote review alone creates no payment or consent.</p>';document.querySelectorAll('[data-reconcile],[data-capture],[data-refund]').forEach(b=>b.onclick=()=>task(async()=>{const path=b.dataset.refund?'refund':b.dataset.capture?'capture':'status';const r=await api('paypal/'+path,{quote_id:b.dataset.refund||b.dataset.capture||b.dataset.reconcile});toast('Sandbox status: '+r.status);await showReceipts();}));if(!$('receipts-dialog').open)$('receipts-dialog').showModal();}
$('receipts').onclick=()=>task(showReceipts);
$('evidence-open').onclick=()=>task(async()=>{const e=await api('missions/evaluation');$('evaluation').innerHTML=`<p class="helper">${esc(e.description)}</p><table class="evidence-table"><thead><tr><th>Controller</th><th>Complete plans</th><th>Admissible deferrals</th><th>Spec checks</th></tr></thead><tbody>${e.policies.map(p=>`<tr><td>${esc(p.name)}</td><td>${p.successes}/${p.solvable}</td><td>${p.correct_deferrals}/${p.unsolvable}</td><td>${p.inspections}</td></tr>`).join('')}</tbody></table><p class="helper">${e.tasks} synthetic cases · ${esc(e.date)} · independent exhaustive fixture oracle. Reproduce: python scripts/evaluate_missions.py</p><p class="fine">${esc(e.conclusion)}</p><p class="helper">Repair oracle: ${e.repair_oracle_matches}/${e.repair_cases} exact matches. ${e.repair_recoveries} feasible repairs; remaining cases correctly have no admissible replacement.</p>`;$('evidence-dialog').showModal();});
for(const b of document.querySelectorAll('dialog .close'))b.onclick=()=>b.closest('dialog').close();
$('discover-open').onclick=()=>{$('discovery-status').textContent=`${config.channel3_calls_remaining} authorized calls remaining. Search is opt-in; search is disabled while the call ceiling is zero.`;syncControls();$('discovery-dialog').showModal();};
$('discovery-form').onsubmit=e=>{e.preventDefault();task(async()=>{const r=await api('discover',{query:$('discovery-query').value});config.channel3_calls_remaining=r.calls_remaining;$('discovery-status').textContent=`${r.calls_remaining} calls remaining. Discovery only.`;$('discovery-results').innerHTML=r.products.map(p=>`<article class="receipt-card"><b>${esc(p.title)}</b><p>${esc(p.description)}</p>${p.url?`<a class="quiet" href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">Visit retailer ↗</a>`:''}</article>`).join('');});};
async function start(){syncControls();const s=await api('session');csrf=s.csrf_token;config=s.config;catalog=await api('missions/catalog');const saved=await api('missions');mission=saved.mission;if(saved.stale)toast('Planner source changed. Compile a new mission; prior exports remain available.');if(mission){$('goal-text').value=mission.text;render();setFlowStep('explore');}const status=await api('missions/model-status');modelAvailable=status.enabled;$('engine-mode').textContent=modelAvailable?'Astropods AI · reviewed proposals':'AI inference connection needed';
if(new URLSearchParams(location.search).get('from')==='research'){
 const savedResearch=await api('agent/research'),run=savedResearch.run;
 if(run?.status==='COMPLETE'&&run.report.visual_handoff_available){
  $('goal-text').value=run.task.query;reviewedText=run.task.query.trim();fillGoal({...run.task.goal,allow_driver:false});setFlowStep('brief');reviewGoalFields();draftChanged();$('compiler-note').textContent='Research requirements loaded for review. Software permission reset. No evidence, recommendation or approval has been transferred.';
 }else toast('No current eligible research brief. Review this setup independently.');
}
syncControls();}
// Guidance explains existing state. It is not a model response or permission to pay.
function setFlowStep(step, focus = false) {
  if (step === 'review') { if (canQuote(mission,dirty(),busy)) $('quote').click(); return; }
  if (step === 'brief') { stopTour(); closeInspector(); if(evidenceView) setEvidenceView(false); }
  flowStep = step;
  document.body.classList.remove('scene-expanded');
  $('scene-expand').setAttribute('aria-pressed','false');
  $('scene-expand').querySelector('.expand-label').textContent=' Expand';
  $('scene-expand').title='Expand the spatial workspace';
  syncGuidance(); spatial?.resize();
  if (focus) {
    const target = step === 'brief' ? $('goal-text') : $('plan-title');
    target.focus({preventScroll:true});
    target.scrollIntoView({block:'center',behavior:motionPreference.matches ? 'auto' : 'smooth'});
  }
}
function syncGuidance() {
  const state = getGuideState(mission,{dirty:dirty(),busy,needsReview:needsReview()});
  const plan = mission?.result.plan, useful = mission?.result.investigations?.filter(x=>x.could_improve_cost) || [];
  if (mission) $('plan-badge').textContent=dirty() ? 'Previous plan · edits pending' : plan ? 'Supported in demo catalog' : mission.result.status==='NEEDS_EVIDENCE' ? 'EVIDENCE NEEDED' : 'REVIEW REQUIREMENTS';
  document.body.dataset.guide=state;
  $('edit-brief').hidden=flowStep==='brief';
  const copy = {
    loading:['Checking the connections…','Building from your reviewed settings.','Checking…'],
    'review-request':['Your idea changed.','Review the settings, then update your setup.','Review request'],
    start:['Start with an idea.','A few details are all you need.','Describe my setup'],
    update:['Ready to update.','Check your new settings against the catalog.','Update setup'],
    evidence:['One detail to check.','A missing specification needs a closer look.','Check specification'],
    conflict:['A small change is needed.','See what conflicts and choose a way forward.','Resolve issue'],
    opportunity:['A supported setup.','Fits the represented catalog checks.','Review quote'],
    ready:['A supported setup.','Review the exact basket before approval.','Review quote'],
  }[state];
  $('guide-title').textContent=copy[0]; $('guide-description').textContent=copy[1];
  $('guide-primary').innerHTML=`${copy[2]} <span>→</span>`; $('guide-primary').disabled=busy || !catalog;
  $('guide-price').textContent=plan ? money(plan.total_cents) : '—';
  $('guide-budget').textContent=plan ? dirty() ? 'Previous plan · update to refresh' : `${money(mission.goal.budget_cents-plan.total_cents)} under budget` : 'A complete plan comes before a quote';
  $('guide-secondary').hidden=!plan || dirty() || needsReview() || !useful.length;
  $('guide-secondary').disabled=busy;
  $('guide-checks').innerHTML=plan && !dirty() ? `<span><i>✓</i>${Object.values(plan.checks).filter(v=>v===true).length} compatibility checks passed</span><span><i>✓</i>${mission.goal.displays} ${mission.goal.height===2160?'4K':'Full HD'} display${mission.goal.displays===1?'':'s'} · ${mission.goal.hz} Hz</span><span><i>✓</i>${mission.goal.reuse_monitor?'Uses your existing monitor':'New displays included'}</span>` : '<span><i>○</i>Review your settings before building</span>';
  $('brief-panel').hidden=flowStep!=='brief'; $('guide-panel').hidden=flowStep==='brief';
  document.body.dataset.flow=flowStep;
  document.body.classList.toggle('request-unreviewed',needsReview());
  document.querySelectorAll('[data-step]').forEach(b=>{ if(b.dataset.step===flowStep)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current'); b.disabled=busy || (b.dataset.step==='review' && !canQuote(mission,dirty(),busy)); });
}
document.querySelectorAll('[data-step]').forEach(b=>b.onclick=()=>setFlowStep(b.dataset.step,true));
$('edit-brief').onclick=()=>setFlowStep('brief',true);
$('guide-primary').onclick=()=>{
  const state=getGuideState(mission,{dirty:dirty(),busy,needsReview:needsReview()});
  if(state==='review-request'){setFlowStep('brief');$('interpret').click();}
  else if(state==='start')setFlowStep('brief',true);
  else if(state==='update'){setFlowStep('brief');$('goal-form').requestSubmit();}
  else if(state==='evidence')$('investigate').click();
  else if(state==='conflict'){$('plan-details').open=true;selectTab('setup');$('conflict').scrollIntoView({block:'center',behavior:motionPreference.matches?'auto':'smooth'});$('conflict').tabIndex=-1;$('conflict').focus({preventScroll:true});}
  else if(state==='ready'||state==='opportunity')$('quote').click();
};
$('guide-secondary').onclick=()=>$('investigate').click();
$('plan-details').addEventListener('toggle',()=>{document.body.classList.toggle('details-open',$('plan-details').open);});
$('quote-dialog').addEventListener('close',()=>{flowStep='explore';syncGuidance();});
document.querySelectorAll('[data-preset]').forEach(b=>b.onclick=()=>{
  const single=b.dataset.preset==='single';
  fillGoal({laptop_id:'studio-pro',budget_cents:single?20000:35000,displays:single?1:2,height:1080,hz:60,reuse_monitor:!single,allow_driver:false});
  $('goal-text').value=single?'Build a one-cable single-monitor workspace under $200. Buy a new Full HD display.':'Build a one-cable dual-monitor workspace under $350. Reuse my current Full HD monitor.';
  reviewedText=$('goal-text').value.trim();$('compiler-note').textContent='Example settings loaded. Review them before building.';draftChanged();reviewGoalFields();
});
const tourParts=['laptop','dock','monitor','cable','power'];
function stopTour(restoreFocus = false) {
  const wasActive=tourIndex>=0;
  tourIndex=-1;$('tour-card').hidden=true;document.body.classList.remove('tour-active');$('scene-tour').setAttribute('aria-pressed','false');
  if(restoreFocus && wasActive) $('scene-tour').focus({preventScroll:true});
}
function showTourPart(index) {
  if(!spatial)return;
  if(evidenceView) setEvidenceView(false);
  inspecting=false;$('part-inspector').hidden=true;
  tourIndex=index;const kind=tourParts[index];
  const g=mission?.goal||goal();
  const established=!!mission?.result.plan && !dirty();
  const captions={
    laptop:['One cable. Your starting point.',established?'This plan uses one USB-C connection between the laptop and dock for data and charging.':'A complete setup needs a laptop connection that supports the requested display signals and charging.'],
    dock:['The connection hub.','The dock links the laptop, displays and power supply. Its specifications determine which combinations can work.'],
    monitor:['Room for your ideas.',established?`${g.displays} ${g.height===2160?'4K':'Full HD'} display${g.displays===1?'':'s'} at ${g.hz} Hz.${g.reuse_monitor?' Your existing Full HD monitor is part of the plan.':''}`:'Choose the number of displays and resolution you need. The planner checks the laptop, dock and cables together.'],
    cable:['Every connection counts.','A complete setup needs a cable kit that matches the display ports and signal requirements.'],
    power:['Power completes the system.','A complete setup needs a compatible supply to power the dock and charge the laptop. The planner checks the power requirement.'],
  }[kind];
  selectPart(kind);spatial.setAutoRotate(false);spatial.focusPart(kind);orbiting=false;topView=false;
  $('tour-count').textContent=`${String(index+1).padStart(2,'0')} / 05 · ${established?'YOUR SETUP':'CONCEPT TOUR'}`;
  $('tour-title').textContent=captions[0];$('tour-description').textContent=captions[1];
  $('tour-next').innerHTML=index===4?'Back to the full setup <span>↗</span>':'Next connection <span>→</span>';
  $('tour-card').hidden=false;document.body.classList.add('tour-active');syncSpatialControls();
  $('scene-announcement').textContent=`Connection ${index+1} of 5. ${captions[0]} ${captions[1]}`;
}
$('scene-tour').onclick=()=>{if(tourIndex>=0){stopTour(true);spatial?.setView('hero');}else showTourPart(0);playTone(620);};
$('tour-next').onclick=()=>{if(tourIndex<4)showTourPart(tourIndex+1);else{stopTour(true);spatial?.setView('hero');syncSpatialControls();}playTone(500);};
$('tour-close').onclick=()=>{stopTour(true);spatial?.setView('hero');syncSpatialControls();};
$('spatial-stage').addEventListener('pointerdown',()=>stopTour());
document.addEventListener('keydown',e=>{
  if(e.key!=='Escape') return;
  const activeElement=document.activeElement;
  stopTour(true);
  for(const menu of [$('view-options'),document.querySelector('.app-menu')]) {
    const restoreFocus=menu.open && menu.contains(activeElement);
    menu.open=false;
    if(restoreFocus) menu.querySelector('summary').focus({preventScroll:true});
  }
});

// View controls stay local: they never revise a goal, quote, or payment.
let spatial = null, explodedView = false, orbiting = true, topView = false, evidenceView = false;
let requestedMotion = true, soundEnabled = false, audioContext = null, lastSceneRevision;
const motionPreference = matchMedia('(prefers-reduced-motion: reduce)');
function playTone(frequency = 600) {
  if (!soundEnabled) return;
  try {
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) return;
    audioContext ||= new Audio();
    if (audioContext.state === 'suspended') audioContext.resume().catch(() => {});
    const oscillator = audioContext.createOscillator(), gain = audioContext.createGain();
    const now = audioContext.currentTime;
    oscillator.type = 'sine'; oscillator.frequency.setValueAtTime(frequency,now); oscillator.frequency.exponentialRampToValueAtTime(frequency*1.4,now+.075);
    gain.gain.setValueAtTime(.0001,now); gain.gain.exponentialRampToValueAtTime(.025,now+.01); gain.gain.exponentialRampToValueAtTime(.0001,now+.12);
    oscillator.connect(gain); gain.connect(audioContext.destination); oscillator.start(now); oscillator.stop(now+.13);
    oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
  } catch { soundEnabled = false; $('sound-toggle').textContent = 'Sound off'; $('sound-toggle').setAttribute('aria-pressed','false'); }
}
function syncSpatialControls() {
  for (const id of ['scene-orbit','scene-explode','scene-top','scene-reset','scene-zoom-in','scene-zoom-out','scene-tour']) $(id).disabled = busy || !spatial;
  $('scene-mode-evidence').setAttribute('aria-pressed',String(evidenceView));
  $('scene-mode-setup').setAttribute('aria-pressed',String(!evidenceView));
  $('scene-mode-evidence').disabled=busy; $('scene-mode-setup').disabled=busy;
  const moving = requestedMotion && !motionPreference.matches;
  $('motion-toggle').textContent = moving ? 'Motion on' : 'Motion off';
  $('motion-toggle').setAttribute('aria-pressed',String(moving));
  $('scene-orbit').setAttribute('aria-pressed',String(orbiting));
  $('scene-explode').setAttribute('aria-pressed',String(explodedView));
  $('scene-explode').innerHTML = `<span aria-hidden="true">◇</span> ${explodedView ? 'Reassemble' : 'Separate parts'}`;
  $('scene-tour').setAttribute('aria-pressed',String(tourIndex >= 0));
  $('scene-top').setAttribute('aria-pressed',String(topView));
  document.body.classList.toggle('motion-paused',!moving);
}
function syncSpatialState() {
  const g = mission?.goal || goal();
  const evidence=getSceneEvidence(mission,{dirty:dirty(),needsReview:needsReview()});
  document.body.dataset.evidence=evidence.state;
  $('scene-state-title').textContent=evidence.title;
  $('scene-state-detail').textContent=evidence.detail;
  $('evidence-lens-caption').textContent=evidence.caption;
  $('scene-reasoning').hidden=!mission;
  $('scene-reasoning').disabled=busy;
  const cards=validityCards(dirty() || needsReview() ? null : mission?.result.validity);
  $('scene-certificates').innerHTML=cards.map((c,i)=>`<div data-tone="${c.tone}"><span class="claim-index">${String(i+1).padStart(2,'0')}</span><div><small>${esc(c.title)}</small><b>${esc(c.label)}</b></div><i aria-hidden="true"></i></div>`).join('');
  spatial?.setState({evidenceState:evidence.state,hasPlan:!!mission?.result.plan,displays:g.displays,reuseMonitor:g.reuse_monitor,selected:selectedPart,dirty:dirty(),status:mission?.result.status || 'concept',revision:mission?.revision});
  if (spatial && mission?.revision && mission.revision !== lastSceneRevision) spatial.pulse();
  lastSceneRevision = mission?.revision;
  const draft = goal();
  $('brief-digest').textContent = `${draft.displays} display${draft.displays === 1 ? '' : 's'} · ${draft.height === 2160 ? '4K' : 'Full HD'} · ${Number.isFinite(draft.budget_cents) ? money(draft.budget_cents) : '—'} budget`;
  if (spatial) $('renderer-status').textContent = dirty() ? 'Update needed' : mission?.result.plan ? '3D setup' : 'Preview';
}
function fallbackScene() {
  spatial?.dispose(); spatial = null;
  document.body.classList.remove('spatial-ready'); document.body.classList.add('scene-fallback');
  $('renderer-status').textContent = 'ILLUSTRATED VIEW / 3D UNAVAILABLE';
  $('spatial-stage').setAttribute('aria-hidden','true'); $('spatial-stage').tabIndex=-1;
  $('scene-announcement').textContent = '3D rendering is unavailable. The illustrated setup and all planning controls remain usable.';
  syncSpatialControls();
}
async function initSpatial() {
  syncSpatialControls();
  try {
    const {createSpatialScene} = await import('./spatial-scene.js');
    spatial = createSpatialScene($('spatial-stage'), {
      onSelect: kind => { stopTour(); inspecting=true; selectPart(kind); playTone(460); $('scene-announcement').textContent = `${names[kind]} selected${mission?.result.plan ? '. Details below the scene.' : '. Assemble a setup to see its selected specification.'}`; },
      onReady: () => { document.body.classList.add('spatial-ready'); document.body.classList.remove('scene-fallback'); $('spatial-stage').removeAttribute('aria-hidden'); $('spatial-stage').tabIndex=0; syncSpatialState(); syncSpatialControls(); },
      onError: fallbackScene,
    });
    spatial.setEvidenceMode?.(evidenceView); spatial.setExploded(explodedView); spatial.setView(topView ? 'top' : 'hero');
    spatial.setAutoRotate(orbiting); spatial.setMotion(requestedMotion); syncSpatialState(); syncSpatialControls();
  } catch { fallbackScene(); }
}
function setEvidenceView(enabled) {
  if(enabled && flowStep==='brief') setFlowStep('explore');
  stopTour(); closeInspector(); evidenceView=Boolean(enabled);
  document.body.classList.toggle('evidence-view',evidenceView);
  $('evidence-lens').hidden=!evidenceView;
  spatial?.setEvidenceMode?.(evidenceView);
  syncSpatialControls(); syncSpatialState(); spatial?.resize();
  $('scene-announcement').textContent=evidenceView?'Evidence view. Separate compatibility, optimality, approval and execution claims.':'Physical setup view.';
}
$('scene-mode-evidence').onclick=()=>setEvidenceView(true);
$('scene-mode-setup').onclick=()=>setEvidenceView(false);
$('scene-reasoning').onclick=()=>{setFlowStep('explore');$('plan-details').open=true;selectTab('evidence',true);$('view-evidence').scrollIntoView({block:'start',behavior:motionPreference.matches?'auto':'smooth'});};
$('scene-orbit').onclick = () => { stopTour(); orbiting = !orbiting; spatial?.setAutoRotate(orbiting); if (orbiting) { topView = false; spatial?.setView('hero'); } syncSpatialControls(); playTone(440); };
$('scene-explode').onclick = () => { stopTour(); explodedView = !explodedView; spatial?.setExploded(explodedView); syncSpatialControls(); $('scene-announcement').textContent = explodedView ? 'Components separated for exploration.' : 'Components reassembled.'; playTone(explodedView ? 720 : 400); };
$('scene-top').onclick = () => { stopTour(); topView = !topView; spatial?.setView(topView ? 'top' : 'hero'); orbiting = false; spatial?.setAutoRotate(false); syncSpatialControls(); playTone(530); };
$('scene-reset').onclick = () => { stopTour(); explodedView = false; topView = false; orbiting = true; spatial?.setAutoRotate(true); spatial?.setExploded(false); spatial?.setView('hero'); spatial?.selectPart(selectedPart); syncSpatialControls(); $('scene-announcement').textContent = 'Perspective view restored.'; playTone(400); };
$('scene-zoom-in').onclick = () => { stopTour(); spatial?.zoom(-1); playTone(570); };
$('scene-zoom-out').onclick = () => { stopTour(); spatial?.zoom(1); playTone(470); };
$('scene-expand').onclick = () => { const expanded = document.body.classList.toggle('scene-expanded'); $('scene-expand').setAttribute('aria-pressed',String(expanded)); $('scene-expand').title = expanded ? 'Exit expanded view' : 'Expand the spatial workspace'; $('scene-expand').querySelector('.expand-label').textContent = expanded ? ' Exit view' : ' Expand'; spatial?.resize(); playTone(510); };
$('motion-toggle').onclick = () => { stopTour(); requestedMotion = !requestedMotion; spatial?.setMotion(requestedMotion); syncSpatialControls(); if (requestedMotion && motionPreference.matches) toast('Your device’s reduced-motion preference keeps the scene still. View controls remain available.'); };
$('sound-toggle').onclick = () => { soundEnabled = !soundEnabled; $('sound-toggle').textContent = soundEnabled ? 'Sound on' : 'Sound off'; $('sound-toggle').setAttribute('aria-pressed',String(soundEnabled)); playTone(680); };
motionPreference.addEventListener('change',() => { stopTour(); spatial?.setMotion(requestedMotion); syncSpatialControls(); });
$('spatial-stage').addEventListener('keydown',e => {
  if (!spatial || e.altKey || e.ctrlKey || e.metaKey) return;
  stopTour();
  const views = {ArrowLeft:'hero',ArrowRight:'detail',ArrowUp:'top',ArrowDown:'front'};
  if (views[e.key]) { e.preventDefault(); spatial.setView(views[e.key]); topView = e.key === 'ArrowUp'; orbiting = false; spatial.setAutoRotate(false); syncSpatialControls(); $('scene-announcement').textContent = `${views[e.key]} camera view.`; }
  if (e.key === '+' || e.key === '=') { e.preventDefault(); spatial.zoom(-1); }
  if (e.key === '-') { e.preventDefault(); spatial.zoom(1); }
});
window.addEventListener('pagehide',() => { stopTour(); spatial?.dispose(); spatial=null; document.body.classList.remove('spatial-ready'); audioContext?.close().catch(() => {}); audioContext=null; });
window.addEventListener('pageshow',e => { if(e.persisted && !spatial) initSpatial(); });
document.body.classList.add('spatial-entrance');
initSpatial();

start().catch(e=>{toast(e.message);$('compile').disabled=true;});
