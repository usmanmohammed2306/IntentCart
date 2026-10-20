import test from 'node:test';
import assert from 'node:assert/strict';
import {isDraftDirty, canQuote, getGuideState, getSceneEvidence} from '../intentcart/web/missions-state.js';

const goal = {
  laptop_id: 'studio-pro', budget_cents: 35000, displays: 2,
  height: 1080, hz: 60, reuse_monitor: true, allow_driver: false,
};
const text = 'Build a two-display workstation.';
const mission = {goal, text, result: {plan: {items: [], total_cents: 27900}}};

test('no saved mission is not a dirty draft and cannot be quoted', () => {
  assert.equal(isDraftDirty(null, goal, text), false);
  assert.equal(isDraftDirty(undefined, goal, text), false);
  assert.equal(canQuote(null, false, false), false);
});

test('goal equality ignores property order and surrounding text whitespace', () => {
  const reordered = Object.fromEntries(Object.entries(goal).reverse());
  assert.equal(isDraftDirty(mission, reordered, `  ${text}\n`), false);
});

test('each submitted goal field participates in stale-plan detection', () => {
  const changes = {
    laptop_id: 'studio-air', budget_cents: 35001, displays: 1,
    height: 2160, hz: 120, reuse_monitor: false, allow_driver: true,
  };
  for (const [key, value] of Object.entries(changes)) {
    assert.equal(isDraftDirty(mission, {...goal, [key]: value}, text), true, key);
  }
});

test('numeric strings and checkbox strings do not equal reviewed typed values', () => {
  assert.equal(isDraftDirty(mission, {...goal, budget_cents: '35000'}, text), true);
  assert.equal(isDraftDirty(mission, {...goal, allow_driver: 'false'}, text), true);
});

test('changed or cleared outcome text requires explicit plan update', () => {
  assert.equal(isDraftDirty(mission, goal, 'Build a single-display workstation.'), true);
  assert.equal(isDraftDirty(mission, goal, ''), true);
  assert.equal(isDraftDirty(mission, goal, 'Build a two-display  workstation.'), true);
});

test('missing goal data cannot be treated as a reviewed matching draft', () => {
  assert.equal(isDraftDirty(mission, null, text), true);
  assert.equal(isDraftDirty(mission, {...goal, hz: undefined}, text), true);
  assert.equal(isDraftDirty({...mission, goal: null}, goal, text), true);
});

test('only an available plan with a clean idle draft can be quoted', () => {
  assert.equal(canQuote(mission, false, false), true);
  assert.equal(canQuote(mission, true, false), false);
  assert.equal(canQuote(mission, false, true), false);
  assert.equal(canQuote(mission, true, true), false);
});

test('absent and malformed plan responses never enable quote review', () => {
  for (const plan of [undefined, null, false, true, 1, 'ready', []]) {
    assert.equal(canQuote({result: {plan}}, false, false), false);
  }
  assert.equal(canQuote({}, false, false), false);
  assert.equal(canQuote({result: null}, false, false), false);
});

test('guide prioritizes in-flight work, request review, then existing draft changes', () => {
  assert.equal(getGuideState(mission, {dirty: true, needsReview: true, busy: true}), 'loading');
  assert.equal(getGuideState(mission, {dirty: true, needsReview: true}), 'review-request');
  assert.equal(getGuideState(mission, {dirty: true}), 'update');
  assert.equal(getGuideState(null, {busy: true, needsReview: true}), 'loading');
  assert.equal(getGuideState(null, {needsReview: true}), 'review-request');
  assert.equal(getGuideState(null, {dirty: true}), 'start');
  assert.equal(getGuideState(undefined), 'start');
});

test('reviewed valid plans distinguish optional savings from a completed plan', () => {
  const useful = {could_improve_cost: true};
  const irrelevant = {could_improve_cost: false};
  assert.equal(getGuideState(mission), 'ready');
  assert.equal(getGuideState({...mission, result: {...mission.result, investigations: []}}), 'ready');
  assert.equal(getGuideState({...mission, result: {...mission.result, investigations: [irrelevant]}}), 'ready');
  assert.equal(getGuideState({...mission, result: {...mission.result, investigations: [irrelevant, useful]}}), 'opportunity');
  assert.equal(getGuideState({...mission, result: {...mission.result, investigations: [useful]}}, {dirty: true}), 'update');
});

test('missing or malformed plans never receive a ready or opportunity guide state', () => {
  for (const plan of [undefined, null, false, true, 1, 'ready', []]) {
    assert.equal(getGuideState({result: {plan}}), 'conflict');
    assert.equal(getGuideState({result: {plan, investigations: [{could_improve_cost: true}]}}), 'evidence');
    assert.equal(canQuote({result: {plan}}, false, false), false);
  }
  assert.equal(getGuideState({}), 'conflict');
  assert.equal(getGuideState({result: null}), 'conflict');
});

test('only explicit useful investigation evidence changes the recommended next step', () => {
  for (const investigations of [undefined, null, {}, 'pending', [null], [{could_improve_cost: 'false'}], [{could_improve_cost: false}]]) {
    assert.equal(getGuideState({result: {plan: null, investigations}}), 'conflict');
    assert.equal(getGuideState({...mission, result: {...mission.result, investigations}}), 'ready');
  }
});

test('scene cannot imply verified compatibility from a plan or payment claim alone', () => {
  assert.equal(getSceneEvidence(null).state, 'concept');
  assert.equal(getSceneEvidence(mission).state, 'unresolved');
  for (const feasibility of ['unknown', 'unresolved', true, undefined]) {
    const claims={feasibility:{status:feasibility},execution:{status:'completed'},authorization:{consent_granted:true}};
    assert.equal(getSceneEvidence({...mission,result:{...mission.result,validity:{claims}}}).state, 'unresolved');
  }
  assert.equal(getSceneEvidence({result:{plan:null,validity:{claims:{feasibility:{status:'verified'}}}}}).state,'unresolved');
});

test('scene colors bind to reviewed feasibility without conflating optimality or approval', () => {
  const verified={...mission,result:{...mission.result,validity:{claims:{feasibility:{status:'verified'},optimality:{status:'unresolved'}}}}};
  assert.equal(getSceneEvidence(verified).state,'verified');
  assert.match(getSceneEvidence(verified).detail,/Approval stays yours/);
  assert.equal(getSceneEvidence(verified,{dirty:true}).state,'changed');
  assert.equal(getSceneEvidence(verified,{needsReview:true}).state,'changed');
  assert.equal(getSceneEvidence(null,{needsReview:true}).state,'changed');
  assert.doesNotMatch(getSceneEvidence(null,{needsReview:true}).caption,/previous plan/);
});

test('scene keeps a conflicting arrangement conceptual', () => {
  assert.equal(getSceneEvidence({result:{status:'INFEASIBLE'}}).state,'conflict');
  assert.equal(getSceneEvidence({result:{status:'NEEDS_EVIDENCE'}}).state,'unresolved');
  assert.equal(getSceneEvidence({result:{validity:{claims:{feasibility:{status:'invalid'}}}}}).state,'conflict');
  assert.equal(getSceneEvidence({result:{status:'NEEDS_EVIDENCE',plan:null,validity:{claims:{feasibility:{status:'no_plan'}}}}}).state,'unresolved');
  assert.equal(getSceneEvidence({result:{plan:null,validity:{claims:{feasibility:{status:'no_plan'}}}}}).state,'unresolved');
});
