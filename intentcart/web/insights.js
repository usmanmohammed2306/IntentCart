// Inspectable client-side explanations of the server's model, never payment authority.
function finite(value, name) {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new TypeError(`${name} must be finite.`);
  return value;
}

export function tradeOffs(leader, alternative, weights) {
  if (!weights.length || leader.features.length !== weights.length || alternative.features.length !== weights.length) {
    throw new RangeError('Features and preferences must have the same dimensions.');
  }
  const contributions = weights.map((weight, i) => {
    const importance = finite(weight.value, 'Preference');
    const a = finite(leader.features[i], 'Feature');
    const b = finite(alternative.features[i], 'Feature');
    return {name: weight.name, importance, leader: a * importance,
      alternative: b * importance, difference: (a - b) * importance};
  });
  return {contributions, margin: contributions.reduce((sum, c) => sum + c.difference, 0),
    priceDifference: leader.total_cents - alternative.total_cents};
}

export function budgetEnvelope(total, budget) {
  finite(budget, 'Budget');
  if (budget <= 0) throw new RangeError('Budget must be positive.');
  if (total === null) return {used: 0, remaining: budget, feasible: false, noPurchase: true};
  finite(total, 'Total');
  if (total < 0) throw new RangeError('Total cannot be negative.');
  return {used: Math.min(100, total / budget * 100), remaining: budget - total,
    feasible: total <= budget, noPurchase: false};
}

export function preferenceShape(weights) {
  const values = weights.map(w => finite(w.value, 'Preference'));
  if (values.some(v => v < 0 || v > 1)) throw new RangeError('Preferences must be between zero and one.');
  const scale = Math.max(.1, Math.ceil(Math.max(0, ...values) * 10) / 10);
  return {scale, radii: values.map(value => value / scale)};
}
