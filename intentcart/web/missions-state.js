const GOAL_KEYS = [
  'laptop_id', 'budget_cents', 'displays', 'height', 'hz',
  'reuse_monitor', 'allow_driver',
];

const normalizedText = value => String(value ?? '').trim();
const hasPlan = mission => {
  const plan = mission?.result?.plan;
  return Boolean(plan && typeof plan === 'object' && !Array.isArray(plan));
};

// The form is a draft until the server returns a mission for these values.
export function isDraftDirty(mission, goal, text) {
  if (!mission) return false;
  if (!mission.goal || !goal) return true;
  return GOAL_KEYS.some(key => mission.goal[key] !== goal[key])
    || normalizedText(mission.text) !== normalizedText(text);
}

// This client gate protects the review flow; the server remains authoritative.
export function canQuote(mission, dirty, busy) {
  return hasPlan(mission) && !dirty && !busy;
}

// Guide actions describe the reviewed server state, never a speculative basket.
export function getGuideState(mission, {dirty = false, busy = false, needsReview = false} = {}) {
  if (busy) return 'loading';
  if (needsReview) return 'review-request';
  if (!mission) return 'start';
  if (dirty) return 'update';

  const investigations = mission.result?.investigations;
  const useful = Array.isArray(investigations)
    && investigations.some(investigation => investigation?.could_improve_cost === true);
  if (!hasPlan(mission)) return useful ? 'evidence' : 'conflict';
  return useful ? 'opportunity' : 'ready';
}

// Scene lighting describes catalog feasibility only. Optimality, consent and
// payment remain separate claims; an attractive render cannot establish them.
export function getSceneEvidence(mission, {dirty = false, needsReview = false} = {}) {
  if (dirty || needsReview) return {
    state:'changed', title:'Your intent changed.',
    detail:'Review and rebuild before relying on this setup.',
    caption:mission ? 'The hardware shows the previous plan. Your edited requirements have not been checked.' : 'This is a conceptual arrangement. Review your edited requirements before building a checked plan.',
  };
  if (!mission) return {
    state:'concept', title:'A concept, ready to check.',
    detail:'Build your setup to verify the connections.',
    caption:'This is a conceptual arrangement. Build a reviewed plan to inspect its supporting evidence.',
  };
  const feasibility = mission.result?.validity?.claims?.feasibility?.status;
  if (hasPlan(mission) && feasibility === 'verified') return {
    state:'verified', title:'The connections check out.',
    detail:'Compatible in this fictional catalog. Approval stays yours.',
    caption:'The selected basket meets the declared specifications. A better choice, permission to buy, and payment completion each need separate evidence.',
  };
  if (mission.result?.status === 'INFEASIBLE' || feasibility === 'invalid') return {
    state:'conflict', title:'A connection needs rethinking.',
    detail:'No complete verified basket. Review the conflicting requirements.',
    caption:'This arrangement is only a concept. The planner has not established a complete compatible basket for these requirements.',
  };
  return {
    state:'unresolved', title:'Some evidence is still missing.',
    detail:'Inspect the open specifications before relying on this setup.',
    caption:'Unknown or conflicting observations cannot establish compatibility. Inspect the reasoning to see what remains unresolved.',
  };
}
