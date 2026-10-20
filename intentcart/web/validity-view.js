// A planning certificate never establishes consent or a payment outcome.
export function validityCards(certificate) {
  const claims = certificate?.claims || {};
  const feasibility = claims.feasibility?.status;
  const optimality = claims.optimality?.status;
  return [
    {title:'Does it work?', label:feasibility === 'verified' ? 'Compatible in this catalog' : 'Not established',
      tone:feasibility === 'verified' ? 'good' : 'warn',
      detail:claims.feasibility?.note || 'Build a reviewed plan to check its requirements.'},
    {title:'Is it the best choice?', label:({verified:'Best under this objective',unresolved:'Evidence still unresolved',superseded:'A better plan is available',unavailable:'No verified plan'})[optimality] || 'Not established',
      tone:optimality === 'verified' ? 'good' : 'warn',
      detail:claims.optimality?.note || 'Cost and minimal-change repair are different objectives.'},
    {title:'May it be purchased?',label:'Exact approval required',tone:'warn',
      detail:'A planning certificate grants no permission. Review and approve the current exact sandbox quote.'},
    {title:'Did it complete?',label:'Not established by this plan',tone:'neutral',
      detail:'A plan does not establish payment status. If an order exists, open Your receipts and reconcile its saved status before retrying.'},
  ];
}
