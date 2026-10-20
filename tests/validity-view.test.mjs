import test from 'node:test';
import assert from 'node:assert/strict';
import { validityCards } from '../intentcart/web/validity-view.js';

test('feasibility is not presented as optimality', () => {
  const cards = validityCards({claims:{feasibility:{status:'verified'},optimality:{status:'unresolved'}}});
  assert.equal(cards[0].tone,'good');
  assert.equal(cards[1].tone,'warn');
  assert.match(cards[1].label,/unresolved/);
});
test('untrusted planning data cannot claim consent or execution', () => {
  const cards = validityCards({claims:{authorization:{status:'approved',consent_granted:true},execution:{status:'COMPLETED'}}});
  assert.equal(cards[2].label,'Exact approval required');
  assert.equal(cards[3].label,'Not established by this plan');
});
test('missing and unknown certificate states fail closed', () => {
  for (const input of [undefined,{}, {claims:{feasibility:{status:'probably'},optimality:{status:'maybe'}}}]) {
    const cards = validityCards(input);
    assert.equal(cards[0].tone,'warn');
    assert.equal(cards[1].tone,'warn');
    assert.equal(cards.length,4);
  }
});
