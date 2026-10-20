import test from 'node:test';
import assert from 'node:assert/strict';
import {tradeOffs, budgetEnvelope, preferenceShape} from '../intentcart/web/insights.js';

test('weighted differences decompose the utility margin in either direction',()=>{
  const a={features:[.9,.2],total_cents:7200},b={features:[.5,.8],total_cents:6200};
  const weights=[{name:'comfort',value:.7},{name:'price',value:.3}];
  const result=tradeOffs(a,b,weights),reverse=tradeOffs(b,a,weights);
  assert.ok(Math.abs(result.margin-.1)<1e-12);
  assert.ok(Math.abs(result.margin+reverse.margin)<1e-12);
  assert.equal(result.priceDifference,1000);
  assert.ok(result.contributions[0].difference>0);
  assert.ok(result.contributions[1].difference<0);
});
test('equal alternatives produce no artificial advantage',()=>{
  const a={features:[.5],total_cents:6200};
  assert.equal(tradeOffs(a,a,[{name:'comfort',value:1}]).margin,0);
});
test('dimension mismatch and non-finite inputs cannot produce misleading charts',()=>{
  assert.throws(()=>tradeOffs({features:[1]},{features:[]},[{value:1}]),RangeError);
  assert.throws(()=>tradeOffs({features:[NaN]},{features:[1]},[{value:1}]),TypeError);
});
test('budget envelope preserves overspend amount while bounding display',()=>{
  assert.deepEqual(budgetEnvelope(7200,9000),{used:80,remaining:1800,feasible:true,noPurchase:false});
  assert.deepEqual(budgetEnvelope(10000,9000),{used:100,remaining:-1000,feasible:false,noPurchase:false});
  assert.equal(budgetEnvelope(9000,9000).feasible,true);
});
test('no purchase is distinct from a feasible zero-priced purchase',()=>{
  assert.equal(budgetEnvelope(null,3000).noPurchase,true);
  assert.equal(budgetEnvelope(null,3000).feasible,false);
  assert.equal(budgetEnvelope(0,3000).feasible,true);
  assert.throws(()=>budgetEnvelope(10,0),RangeError);
});
test('radar uses a disclosed adaptive scale and rejects invalid preference values',()=>{
  const shape=preferenceShape([{value:.12},{value:.28},{value:.1}]);
  assert.equal(shape.scale,.3);
  assert.ok(shape.radii.every(v=>v>=0&&v<=1));
  assert.equal(preferenceShape([]).scale,.1);
  assert.throws(()=>preferenceShape([{value:-.1}]),RangeError);
});
