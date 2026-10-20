import { validityCards } from './validity-view.js';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty = value => esc(JSON.stringify(value, null, 2));
const metric = (value, label) => `<div class="card"><b class="number">${esc(value)}</b><span class="label">${esc(label)}</span></div>`;
const raw = (title, value) => `<details><summary>${esc(title)}</summary><pre>${pretty(value)}</pre></details>`;
async function get(path) {
  const response = await fetch(path);
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'The saved result is unavailable.');
  return data;
}
function error(id, err) { $(id).innerHTML = `<div class="error"><b>Evidence unavailable</b><p>${esc(err.message)}</p><p>Results are shown only when their source identities match this installation.</p></div>`; }
function selectPanel(id) {
  if (!['validity','acquisition','reliability'].includes(id)) id = 'validity';
  document.querySelectorAll('[data-panel]').forEach(b => { b.setAttribute('aria-pressed',String(b.dataset.panel === id)); });
  document.querySelectorAll('.experiment').forEach(p => p.hidden = p.id !== id);
  history.replaceState(null,'','#' + id);
}
document.querySelectorAll('[data-panel]').forEach(b => b.onclick = () => selectPanel(b.dataset.panel));
selectPanel(location.hash.slice(1));

async function showValidity() {
  let html;
  try {
    const data = await get('/api/missions');
    const certificate = data.mission?.result?.validity;
    if (certificate) {
      const work = certificate.work;
      html = `<div class="claims">${validityCards(certificate).map(c => `<article class="card"><h3>${esc(c.title)}</h3><span class="status ${c.tone === 'good' ? '' : 'warn'}">${esc(c.label)}</span><p>${esc(c.detail)}</p></article>`).join('')}</div><p class="caption">Revision ${esc(certificate.revision)} · ${esc(work.reused_candidates)} candidate evaluations reused · ${esc(work.rechecked_candidates)} rechecked. These counts are not latency or cash savings.</p>${raw('Inspect the decision certificate',certificate)}`;
    } else {
      html = `<div class="empty"><h3>${data.stale ? 'Your previous plan belongs to an earlier source version.' : 'Start with a workspace plan.'}</h3><p>Build a reviewed mission to inspect its four validity claims here. Existing saved orders remain in your receipts.</p><a class="button" href="/missions">Build a workspace ↗</a></div>`;
    }
  } catch {
    html = '<div class="empty"><h3>Your workspace, when you are ready.</h3><p>Open the workspace and build a plan to inspect its evidence here.</p><a class="button" href="/missions">Open workspace ↗</a></div>';
  }
  $('validity-content').innerHTML = html + '<div id="validity-experiment"><p class="loading">Loading the selective revalidation comparison…</p></div>';
  try {
    const report = await get('/api/research/validity');
    $('validity-experiment').innerHTML = `<h3>Selective checks, compared with full recomputation.</h3><p class="caption">${esc(report.description)}</p><div class="metrics">${metric(`${report.semantic_matches}/${report.cases}`,'Paired cases with identical semantic claims')}${metric(report.selective_candidate_evaluations,'Candidate evaluations · selective analyzer')}${metric(report.full_candidate_evaluations,'Candidate evaluations · full analyzer')}${metric(`${report.passed_checks}/${report.checks}`,'Declared fixture assertions pass')}</div><p class="caption">The mission planner still performs its full solve for existing diagnostics. Reuse counts describe only the additional certificate analyzer, not total application work or speed.</p>${raw('Comparison identities and totals',report)}<a class="button quiet" href="/api/research/validity?full=true" target="_blank" rel="noopener">Inspect all paired records ↗</a>`;
  } catch (e) { error('validity-experiment',e); }
}

function showAcquisition(report) {
  const counts = report.counts;
  const labels = {exact:'Exact adaptive reference',decision_split:'Decision relevance + reuse',information:'Information per cost',restart_decision_split:'Decision relevance, restart',full_census:'Inspect every fact'};
  const budgets = [...new Set(report.summary.map(row => row.budget_label))];
  $('acquisition-content').innerHTML = `<div class="metrics">${metric(counts.scenario_structures,'Declared scenario structures')}${metric(counts.worlds,'Enumerated possible worlds')}${metric(counts.policies,'Policies compared')}${metric(counts.paired_rows,'Correlated world / policy / budget rows')}</div><div class="toolbar"><label for="budget-select">Inspection budget</label><select id="budget-select">${budgets.map(b => `<option ${b === 'unlimited' ? 'selected' : ''} value="${esc(b)}">${b === 'unlimited' ? 'Full resolution' : esc(b)+' cost units'}</option>`).join('')}</select><label for="split-select">Scenario set</label><select id="split-select"><option value="structural_check">Structural checks</option><option value="development">Development</option></select></div><div id="acquisition-results"></div><div class="note"><b>A reference policy, not a clairvoyant answer.</b><p>The selected hidden world is available only to the simulator. Policies choose from declared possible worlds and admitted observations. A consensus that no solution exists is different from running out of budget.</p><p>The exact policy minimizes unrestricted expected inspection cost under the declared prior. Truncating it at a budget does not make it optimal for completion at that budget.</p></div>${raw('Experiment protocol',report.protocol)}${raw('Policy summaries and source identities',{summary:report.summary,source_sha256:report.source_sha256})}<p class="caption">Local finite simulation. Structural checks are designed fixtures, not an untouched external benchmark. World rows are correlated, not independent human trials. No live-model comparison is established.</p>`;
  function update() {
    const rows = report.summary.filter(r => r.split === $('split-select').value && r.budget_label === $('budget-select').value);
    $('acquisition-results').innerHTML = `<div class="card"><h3>Supported resolution at this budget</h3><p class="caption">Prior-weighted within each structure, then averaged equally across structures. Includes correctly establishing infeasibility.</p><div class="budget-chart">${rows.map(r => `<div class="bar-row"><span>${esc(labels[r.policy] || r.policy)}</span><div class="bar-track"><div class="bar" style="width:${Math.max(0,Math.min(100,r.macro_prior_weighted_completion*100))}%"></div></div><b>${(100*r.macro_prior_weighted_completion).toFixed(1)}%</b></div>`).join('')}</div></div><div class="table-wrap"><table><thead><tr><th>Policy</th><th>Resolved worlds</th><th>Expected cost</th><th>Unsupported decisions</th><th>False infeasibility</th><th>Solvable worlds deferred at budget</th></tr></thead><tbody>${rows.map(r => `<tr><td><b>${esc(labels[r.policy] || r.policy)}</b></td><td>${r.valid_completion} / ${r.world_episodes}</td><td>${r.macro_expected_cost.toFixed(3)} units</td><td>${r.unsupported_decisions}</td><td>${r.false_infeasibility}</td><td>${r.budget_defer_solvable} / ${r.solvable_world_episodes}</td></tr>`).join('')}</tbody></table></div><p class="caption">Inspection costs are declared fixture units, not dollars, API latency, or tokens. Cost is additional work after admitted cached evidence; raw records also retain prior costs.</p>`;
  }
  $('budget-select').onchange = update;
  $('split-select').onchange = update;
  update();
}

function showReliability(report) {
  const d = report.denominators;
  const baseline = report.cases.filter(c => c.expected_outcome_matches).length;
  const detected = report.mutations.filter(c => c.detected).length;
  const options = [...report.cases.map(c => ({id:c.id,name:c.id,trace:c.trace,outcome:c.outcome,kind:c.kind})),
    ...report.mutations.map(c => ({id:'mutation-'+c.id,name:'Deliberate defect · '+c.id,trace:c.shrunk_trace || c.trace,outcome:c.shrunk_outcome || c.outcome,kind:'mutation',shrink:c.shrink}))];
  $('reliability-content').innerHTML = `<div class="metrics">${metric(`${baseline}/${report.cases.length}`,'Declared scenarios match expected outcomes')}${metric(`${detected}/${d.mutants}`,'Deliberate defects detected')}${metric(d.interruption_points,'Declared interruption points')}${metric(report.live_provider_calls,'Live provider calls')}</div><div class="toolbar"><label for="trace-select">Explore a saved case</label><select id="trace-select">${options.map(c => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('')}</select></div><div id="trace-view"></div>${raw('Suite checks and exact denominators',{checks:report.checks,denominators:d})}<div class="note"><b>What this establishes</b><p>${esc(report.kind)}</p><p>${report.limits.map(esc).join(' ')}</p></div>`;
  function renderTrace(id) {
    const entry = options.find(c => c.id === id);
    const events = entry.outcome.events;
    let step = 0;
    $('trace-view').innerHTML = `<p class="caption">${entry.kind === 'mutation' ? 'Deliberately weakened test-only behavior. The exported reduced trace retains a detected violation.' : 'Unmodified application, fictional fixture input and independent fake provider.'}</p><div class="trace-layout"><ol class="trace">${events.map((event,i) => `<li data-event="${i}"><b>${String(i+1).padStart(2,'0')} / ${esc(event.op.replaceAll('-',' '))}</b><small>${event.process_recreated ? 'New interpreter; durable state retained' : event.http_status ? `HTTP ${esc(event.http_status)} · ${esc(event.local_status || 'no saved order')}` : esc(event.at || event.local_status || 'local observation')}</small></li>`).join('')}</ol><aside class="card trace-detail"><p class="eyebrow" id="step-count"></p><h3 id="step-title"></h3><pre id="step-json"></pre><div class="actions"><button class="action quiet" id="previous-step">← Previous</button><button class="action" id="next-step">Next event →</button></div><p>Viewing this recording executes no payment or model request.</p><a id="trace-download" class="button quiet" href="/api/reliability/traces/${encodeURIComponent(entry.id)}" download>Download reproducible trace ↓</a><p class="caption">Run from the repository with its Python environment:</p><pre>python scripts/evaluate_reliability.py --replay PATH_TO_DOWNLOADED_TRACE</pre>${entry.shrink ? raw('Trace reduction',entry.shrink) : ''}</aside></div><div class="note"><b>${entry.outcome.violations.length ? 'Detected: '+entry.outcome.violations.map(esc).join(', ') : 'No declared invariant violation in this case.'}</b><p>Final local state: ${esc(entry.outcome.local_status || 'no order')}. Process restarts: ${esc(entry.outcome.process_restarts)}. Ledger counts are separate from local application state.</p>${raw('Independent fake ledger',entry.outcome.ledger_counts)}</div>`;
    function update() {
      document.querySelectorAll('[data-event]').forEach(el => el.classList.toggle('active',Number(el.dataset.event) === step));
      $('step-count').textContent = `EVENT ${step+1} OF ${events.length}`;
      $('step-title').textContent = events[step].op.replaceAll('-',' ');
      $('step-json').textContent = JSON.stringify(events[step],null,2);
      $('previous-step').disabled = step === 0;
      $('next-step').disabled = step === events.length-1;
    }
    $('previous-step').onclick = () => { if(step > 0) step--; update(); };
    $('next-step').onclick = () => { if(step < events.length-1) step++; update(); };
    update();
  }
  $('trace-select').onchange = () => renderTrace($('trace-select').value);
  renderTrace(options[0].id);
}

await Promise.allSettled([
  showValidity(),
  get('/api/research/acquisition').then(showAcquisition).catch(e => error('acquisition-content',e)),
  get('/api/research/reliability').then(showReliability).catch(e => error('reliability-content',e)),
]);
