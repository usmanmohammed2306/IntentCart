// A single reviewed shopping path. Models never receive payment controls.
export function attachCommerce(hooks){
 const $=id=>document.getElementById(id),clone=v=>structuredClone(v),node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;},money=n=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(n/100);
 const dialog=node('dialog');dialog.id='shop-dialog';
 // Static authored markup only. Catalog, model and account data use textContent.
 dialog.innerHTML='<div class="dialog-head"><div><span class="eyebrow">PAYPAL SANDBOX</span><h2>Plan. Review. Pay.</h2></div><button id="shop-close" aria-label="Close shopping">×</button></div><p class="helper">Fictional products. Test funds. No goods or delivery.</p><form id="shop-form"><div class="pair"><label>Budget · USD<input id="shop-budget" type="number" min="10" max="3000" step="0.01" value="300" required></label><label>Screens<select id="shop-screens"><option value="1">One</option><option value="2" selected>Two</option></select></label></div><label>Example laptop<select id="shop-laptop"></select></label><label class="check"><input id="shop-reuse" type="checkbox" checked> Keep one existing screen</label><details><summary>Screen & software settings</summary><div class="pair"><label>Resolution<select id="shop-resolution"><option value="1080">1080p</option><option value="2160">4K</option></select></label><label>Refresh rate<select id="shop-hz"><option value="60">60 Hz</option><option value="120">120 Hz</option></select></label></div><label class="check"><input id="shop-driver" type="checkbox"> I permit a software-dependent setup</label><p class="helper">Planning permission only. Nothing is installed.</p></details><button id="shop-build" class="primary">Find my complete cart</button></form><p id="shop-status" role="status" aria-live="polite"></p><ol id="shop-progress"></ol><div id="shop-cart" class="shop-cart"></div><div class="button-row"><button id="shop-stop" hidden>Stop</button><button id="shop-resume" hidden>Resume saved plan</button><button id="shop-preview" hidden>Preview as a new draft</button><button id="shop-review" class="primary" hidden>Review PayPal Sandbox quote</button></div><section id="shop-checkout" hidden><div id="shop-quote"></div><label class="check"><input id="shop-approve" type="checkbox"><span id="shop-approval-label"></span></label><div id="shop-paypal"></div><p id="shop-payment-status" role="status"></p><div class="button-row"><button id="shop-refresh-quote">Get a fresh quote</button><button id="shop-reconcile" hidden>Check saved payment</button><a id="shop-receipt" class="quiet" hidden>Decision receipt ↓</a></div></section><details id="shop-history"><summary>Saved sandbox payments</summary><button id="shop-history-refresh">Show my payments</button><div id="shop-orders"></div></details>';
 document.body.append(dialog);
 let account=null,config=null,run=null,busy=false,starting=null,loading=false,loadSequence=0,historySequence=0,epoch=0,applied=null,quote=null,quoteOperation=null,sdkPromise=null,lastEditorRevision='';
 const signature=()=>JSON.stringify([hooks.current().workspace,hooks.current().planning]);
 const canonical=value=>JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b))):v);
 const button=(label,fn)=>{const b=node('button',label);b.type='button';b.onclick=()=>act(fn);return b;};
 function goalDraft(){return {laptop_id:$('shop-laptop').value,budget_cents:Math.round(Number($('shop-budget').value)*100),displays:Number($('shop-screens').value),height:Number($('shop-resolution').value),hz:Number($('shop-hz').value),reuse_monitor:$('shop-reuse').checked,allow_driver:$('shop-driver').checked};}
 function goalDirty(){if(!run)return false;const g=goalDraft();return Object.keys(g).some(k=>g[k]!==run.mission.goal[k]);}
 function resetQuote(){quote=null;quoteOperation=null;$('shop-checkout').hidden=true;$('shop-approve').checked=false;$('shop-approve').disabled=true;$('shop-paypal').replaceChildren();$('shop-payment-status').textContent='';$('shop-quote').replaceChildren();$('shop-approval-label').textContent='';$('shop-receipt').hidden=true;$('shop-receipt').removeAttribute('href');$('shop-reconcile').hidden=true;$('shop-reconcile').disabled=false;}
 function clearApproval(){$('shop-approve').checked=false;$('shop-paypal').replaceChildren();}
 function status(t){$('shop-status').textContent=t;}
 function changed(){const editor=hooks.current(),v=JSON.stringify([editor.project_id,editor.revision]);if(lastEditorRevision&&v!==lastEditorRevision&&quote){resetQuote();status('Saved work changed. Review a fresh sandbox quote.');}lastEditorRevision=v;if(applied&&signature()!==applied){applied=null;resetQuote();$('shop-open').textContent='Shop';$('shop-review').hidden=true;if(run?.status==='READY_FOR_REVIEW')status('The draft changed. Preview and review the exact cart again.');}}
 async function act(fn){try{await fn();}catch(e){hooks.notice(e.message);status(e.message);}}
 function showRun(){
  if(!run){$('shop-preview').hidden=true;$('shop-review').hidden=true;$('shop-resume').hidden=true;$('shop-stop').hidden=!starting;return;}const ready=run.status==='READY_FOR_REVIEW'&&run.fresh&&!goalDirty()&&!busy&&!starting&&!loading;
  $('shop-progress').replaceChildren(...run.events.map(e=>node('li',({search:'Searched the sandbox catalog',inspect:'Checked a missing specification',recommend:'Verified a complete cart',defer:'Stopped at an unresolved condition'})[e.model_tool]||'Paused for review')));
  $('shop-stop').hidden=!starting&&run.status!=='RUNNING';$('shop-resume').hidden=!!starting||busy||!(run.status==='RUNNING'||run.status==='MODEL_PAUSED')||!run.fresh;
  $('shop-preview').hidden=!ready;$('shop-review').hidden=!ready||!applied;$('shop-cart').replaceChildren();
  if(ready){const plan=run.mission.result.plan;for(const row of plan.items){const p=config.products.find(p=>p.id===row.product_id),card=node('article');card.append(node('span',({dock:'▰',monitor:'▣',cable:'⌁',power:'ϟ'})[p.kind]||'◇','shop-icon'),node('strong',p.name),node('small',row.quantity+' × '+money(p.price_cents)));$('shop-cart').append(card);}status('Complete cart · '+money(plan.total_cents)+' · review before paying.');}
  else status(starting?'Starting a new plan…':run.status==='RUNNING'?(busy?'Your local AI is checking the cart…':'Saved plan. Resume when you are ready.'):run.status==='CANCELLED'?'Plan stopped. Start again when you are ready.':run.error||'No supported cart yet. Review these settings.');
 }
 async function continueRun(){
  if(busy||starting||!run)return;const own=++epoch;busy=true;$('shop-build').disabled=true;showRun();
  try{while(run.status==='RUNNING'&&own===epoch){const next=await hooks.api('/api/commerce/advance',{run_id:run.id,revision:run.revision});if(own!==epoch)return;run=next;showRun();}}
  finally{if(own===epoch){busy=false;$('shop-build').disabled=false;showRun();}}
 }
 async function load(){
  const own=account?.id;if(!own||starting||busy)return;const sequence=++loadSequence;loading=true;$('shop-build').disabled=true;showRun();
  try{const data=await hooks.api('/api/commerce/config');if(account?.id!==own||sequence!==loadSequence)return;config=data;
  $('shop-laptop').replaceChildren(...data.laptops.map(p=>{const n=node('option',p.name);n.value=p.id;return n;}));
  const r=await hooks.api('/api/commerce/runs');if(account?.id!==own||sequence!==loadSequence||starting||busy)return;run=r.runs.at(-1)||null;if(run){const g=run.mission.goal;for(const [id,v] of Object.entries({'shop-laptop':g.laptop_id,'shop-budget':g.budget_cents/100,'shop-screens':g.displays,'shop-resolution':g.height,'shop-hz':g.hz}))$(id).value=v;$('shop-reuse').checked=g.reuse_monitor;$('shop-driver').checked=g.allow_driver;}
  const current=hooks.current();applied=run?.fresh&&run.status==='READY_FOR_REVIEW'&&run.projection&&canonical([current.workspace,current.planning])===canonical([run.projection.workspace,run.projection.planning])?signature():null;
  $('shop-open').textContent=applied?'Review cart':'Shop';
  }finally{if(account?.id===own&&sequence===loadSequence){loading=false;$('shop-build').disabled=!!starting||busy;showRun();}}
 }
 $('shop-open').onclick=()=>act(async()=>{if(!account)return;if($('planning-dialog').open)$('planning-dialog').close();if(!dialog.open)dialog.showModal();await load();});
 $('shop-form').onsubmit=e=>{e.preventDefault();act(async()=>{
  if(loading)throw Error('Wait for the saved cart to finish loading.');if(busy||starting)throw Error('Stop the current plan before starting another.');const own=account?.id;if(!own)return;
  resetQuote();applied=null;const c=hooks.current(),goal=goalDraft(),pending={account:own,cancelled:false};run=null;starting=pending;$('shop-build').disabled=true;$('shop-preview').hidden=true;$('shop-review').hidden=true;$('shop-resume').hidden=true;$('shop-stop').hidden=false;$('shop-cart').replaceChildren();$('shop-progress').replaceChildren();status('Starting a new plan…');
  const work=(async()=>{try{const next=await hooks.api('/api/commerce/start',{goal,space:c.workspace.surface});if(account?.id!==own)return;run=next;if(pending.cancelled){run=await hooks.api('/api/commerce/cancel',{run_id:next.id,revision:next.revision});return;}if(starting!==pending)return;starting=null;await continueRun();}finally{if(starting===pending){starting=null;$('shop-build').disabled=false;showRun();}}})();pending.done=work;await work;
 });};
 async function stop(){
  if(starting){const pending=starting;pending.cancelled=true;status('Stopping before the investigation starts…');await pending.done;return;}
  if(!run||run.status!=='RUNNING')return;const own=account?.id,guard=++epoch,id=run.id;busy=false;$('shop-build').disabled=false;
  const currentContext=()=>account?.id===own&&epoch===guard&&!starting;
  // A completing step can change revision after the lookup. Reconcile once;
  // an account switch or newer action must never receive the old response.
  for(let attempt=0;attempt<2;attempt++){
   const current=(await hooks.api('/api/commerce/runs')).runs.find(r=>r.id===id);if(!currentContext())return;
   if(!current||current.status!=='RUNNING'){run=current||run;showRun();return;}
   try{const stopped=await hooks.api('/api/commerce/cancel',{run_id:current.id,revision:current.revision});if(!currentContext())return;run=stopped;showRun();return;}
   catch(error){if(!currentContext())return;if(attempt===1)throw error;}
  }
 }
 $('shop-stop').onclick=()=>act(stop);$('shop-close').onclick=()=>act(async()=>{clearApproval();await stop();dialog.close();});dialog.addEventListener('cancel',e=>{e.preventDefault();act(async()=>{clearApproval();await stop();dialog.close();});});
 $('shop-resume').onclick=()=>act(async()=>{if(busy||starting||!run)return;if(run.busy||run.status==='MODEL_PAUSED')run=await hooks.api('/api/commerce/recover',{run_id:run.id,revision:run.revision});await continueRun();});
 $('shop-preview').onclick=()=>act(()=>{
  if(starting||busy||!run?.fresh||run.status!=='READY_FOR_REVIEW'||goalDirty())throw Error('Review a finished current purchase plan first.');
  hooks.newProject();hooks.commit(clone(run.projection.workspace),clone(run.projection.planning));applied=signature();resetQuote();$('shop-open').textContent='Review cart';showRun();dialog.close();hooks.notice('Sandbox cart opened as a new draft. Previous saved projects remain. Sizes are unknown; physical fit is not certified.');
 });
 async function review(){
  if(starting||busy||!run||!applied||signature()!==applied||goalDirty())throw Error('Preview the exact finished cart as a new draft first.');const own=account?.id,original=signature(),planId=run.id,goal=JSON.stringify(goalDraft());
  const unchanged=()=>account?.id===own&&signature()===original&&applied===original&&run?.id===planId&&JSON.stringify(goalDraft())===goal;
  quoteOperation=quoteOperation||crypto.randomUUID().replaceAll('-','');const current=hooks.current();const q=await hooks.api('/api/commerce/quotes',{run_id:planId,revision:run.revision,operation_id:quoteOperation,workspace:current.workspace,planning:current.planning});
  if(!unchanged())throw Error('The draft or settings changed. Review the current cart again.');const latest=await hooks.api('/api/commerce/runs');if(!unchanged())throw Error('Account, draft or settings changed; review again.');const selected=latest.runs.find(r=>r.id===planId);if(!selected?.fresh||selected.status!=='READY_FOR_REVIEW')throw Error('The purchase plan changed. Build a fresh cart.');run=selected;quote=q;$('shop-checkout').hidden=false;$('shop-approve').checked=false;$('shop-paypal').replaceChildren();$('shop-quote').replaceChildren();
  for(const row of q.basket){const p=config.products.find(p=>p.id===row.product_id),line=node('div',undefined,'row-card');line.append(node('span',row.quantity+' × '+p.name),node('strong',money(p.price_cents*row.quantity)));$('shop-quote').append(line);}
  $('shop-quote').append(node('h3',money(q.total_cents)+' USD · exact sandbox total'),node('p','Shipping and sandbox tax: $0.00. No goods or delivery. Quote expires in 15 minutes.','helper'));
  $('shop-approval-label').textContent='I approve this exact '+money(q.total_cents)+' fictional sandbox cart.';$('shop-approve').disabled=!config.paypal_connected;$('shop-payment-status').textContent=config.paypal_connected?'Buyer approval happens separately in PayPal Sandbox.':(config.paypal_test?.notice||'PayPal Sandbox is unavailable. Your plan remains saved; no payment is simulated.');
  $('shop-receipt').hidden=false;$('shop-receipt').href='/api/decision-receipt/'+encodeURIComponent(q.id)+'?download=true';$('shop-reconcile').hidden=false;$('shop-reconcile').disabled=!!config.paypal_test?.closed;if(!dialog.open)dialog.showModal();
 }
 $('shop-review').onclick=()=>act(review);
 $('shop-refresh-quote').onclick=()=>act(async()=>{const id=run?.id;resetQuote();run=(await hooks.api('/api/commerce/runs')).runs.find(r=>r.id===id);await review();});
 // One persistent shopping entry reopens the cart after its3D preview.
 function loadSDK(){if(window.paypal)return Promise.resolve(window.paypal);if(sdkPromise)return sdkPromise;sdkPromise=new Promise((resolve,reject)=>{const script=node('script');let timer;const fail=()=>{clearTimeout(timer);script.remove();sdkPromise=null;reject(Error('PayPal could not load. Your quote remains saved; retry when connected.'));};script.src='https://www.paypal.com/sdk/js?client-id='+encodeURIComponent(config.paypal_client_id)+'&currency=USD&intent=capture';script.onload=()=>{clearTimeout(timer);if(window.paypal)resolve(window.paypal);else fail();};script.onerror=fail;timer=setTimeout(fail,15000);document.head.append(script);});return sdkPromise;}
 $('shop-approve').onchange=()=>act(async()=>{
  $('shop-paypal').replaceChildren();if(!$('shop-approve').checked||!config?.paypal_connected||!quote)return;
  const q=quote,own=account?.id,input=signature();const sdk=await loadSDK();if(account?.id!==own||q!==quote||!$('shop-approve').checked||signature()!==input)return;
  await sdk.Buttons({createOrder:async()=>{if(q!==quote||!$('shop-approve').checked||signature()!==input||goalDirty())throw Error('Cart or approval changed. Review again.');const r=await hooks.api('/api/paypal/create',{quote_id:q.id,approved:true});return r.id;},onApprove:async()=>{
   if(account?.id!==own||q!==quote||!$('shop-approve').checked||signature()!==input||goalDirty()){hooks.notice('An earlier sandbox order needs explicit review in saved payments.');return;}
   try{const r=await hooks.api('/api/paypal/capture',{quote_id:q.id});$('shop-payment-status').textContent='Verified sandbox status: '+r.status;$('shop-approve').checked=false;$('shop-paypal').replaceChildren();await history();}catch(e){$('shop-payment-status').textContent=e.message;}
  },onCancel:()=>{if(account?.id!==own||q!==quote)return;clearApproval();$('shop-payment-status').textContent='Buyer cancelled. No capture requested.';},onError:()=>{if(account?.id!==own||q!==quote)return;clearApproval();$('shop-payment-status').textContent='Checkout interrupted. Check the saved payment before retrying.';}}).render('#shop-paypal');
 });
 $('shop-reconcile').onclick=()=>act(async()=>{if(!quote)return;const r=await hooks.api('/api/paypal/status',{quote_id:quote.id});$('shop-payment-status').textContent='Verified sandbox status: '+r.status;await history();});
 async function history(){
  const own=account?.id,sequence=++historySequence;
  const [orders,latestConfig]=await Promise.all([hooks.api('/api/orders'),hooks.api('/api/commerce/config')]);
  if(account?.id!==own||sequence!==historySequence)return;config=latestConfig;$('shop-orders').replaceChildren();
  if(quote){const active=orders.find(order=>order.quote_id===quote.id);if(active){$('shop-payment-status').textContent='Verified sandbox status: '+active.status;if(['COMPLETED','REFUND_PENDING','REFUNDED'].includes(active.status))clearApproval();}
   $('shop-approve').disabled=!config.paypal_connected||!!(active&&['COMPLETED','REFUND_PENDING','REFUNDED'].includes(active.status));
   $('shop-reconcile').disabled=!!config.paypal_test?.closed;
  }
  for(const order of orders){const card=node('article',undefined,'planning-check');card.append(node('strong',money(order.quote.total_cents)+' · '+order.status),node('p',order.quote.product.name,'helper'));
   if(order.order_id){const check=button('Check saved status',async()=>{await hooks.api('/api/paypal/status',{quote_id:order.quote_id});await history();});check.disabled=!!config.paypal_test?.closed;card.append(check);}
   if(order.status==='APPROVED'&&config.paypal_connected)card.append(button('Finish approved sandbox payment',async()=>{if(!confirm('Finish this exact '+money(order.quote.total_cents)+' sandbox payment?'))return;await hooks.api('/api/paypal/capture',{quote_id:order.quote_id});await history();}));
   if(['COMPLETED','REFUND_PENDING'].includes(order.status)&&config.paypal_connected)card.append(button(order.status==='REFUND_PENDING'?'Retry saved refund':'Refund sandbox capture',async()=>{if(!confirm('Refund this exact '+money(order.quote.total_cents)+' sandbox capture?'))return;await hooks.api('/api/paypal/refund',{quote_id:order.quote_id});await history();}));
   const a=node('a','Decision receipt ↓');a.href='/api/decision-receipt/'+encodeURIComponent(order.quote_id)+'?download=true';card.append(a);$('shop-orders').append(card);
  }
  if(!orders.length)$('shop-orders').append(node('p','No saved payments. Planning and quote review do not move funds.','helper'));
  if(config.paypal_test?.closed)$('shop-orders').append(node('p','Sandbox checkout is paused. Saved receipts remain available.','helper'));
 }
 $('shop-history-refresh').onclick=()=>act(history);
 for(const event of ['input','change'])$('shop-form').addEventListener(event,()=>{if(goalDirty()){applied=null;resetQuote();$('shop-open').textContent='Shop';$('shop-preview').hidden=true;$('shop-review').hidden=true;status('Settings changed. Build a new cart before reviewing payment.');}else showRun();});
 function accountChanged(user){
  if(account?.id!==user?.id){++epoch;++loadSequence;++historySequence;loading=false;if(starting)starting.cancelled=true;starting=null;run=null;config=null;applied=null;busy=false;$('shop-build').disabled=false;$('shop-form').reset();$('shop-laptop').replaceChildren();$('shop-open').textContent='Shop';resetQuote();$('shop-cart').replaceChildren();$('shop-orders').replaceChildren();$('shop-progress').replaceChildren();status('');if(dialog.open)dialog.close();}
  account=user;$('shop-open').hidden=!user;
 }
 return {changed,accountChanged};
}
