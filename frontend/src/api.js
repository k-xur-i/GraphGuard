const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function req(path, opts = {}) {
  const r = await fetch(BASE + path, { headers: { 'Content-Type': 'application/json' }, ...opts })
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail) || r.statusText)
  return body
}

const q = (params) => {
  const p = Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== '')
  return p.length ? '?' + new URLSearchParams(p).toString() : ''
}

export const api = {
  health: () => req('/health'),
  users: () => req('/users'),
  groups: () => req('/groups'),
  accounts: () => req('/accounts'),
  stats: () => req('/stats'),
  graph: (id, asOf) => req(`/graph/focus/${id}${q({ as_of: asOf })}`),
  whoHasAccess: (id, asOf) => req(`/accounts/${id}/access${q({ as_of: asOf })}`),
  accessDiff: (id, from, to) => req(`/accounts/${id}/access-diff${q({ from, to })}`),
  check: (user_id, account_id, asOf) => req(`/access/check${q({ user_id, account_id, as_of: asOf })}`),
  userAccounts: (id, asOf) => req(`/users/${id}/accounts${q({ as_of: asOf })}`),
  grant: (b) => req('/access/grant', { method: 'POST', body: JSON.stringify(b) }),
  revoke: (b) => req('/access/revoke', { method: 'POST', body: JSON.stringify(b) }),
  newTx: (b) => req('/transactions', { method: 'POST', body: JSON.stringify(b) }),
  statement: (id, asOf, viewer) => req(`/accounts/${id}/transactions${q({ as_of: asOf, viewer_id: viewer })}`),
  visibleTx: (uid, asOf) => req(`/users/${uid}/visible-transactions${q({ as_of: asOf })}`),
  flagged: () => req('/transactions/flagged'),
  events: (account_id, asOf) => req(`/audit/events${q({ account_id, as_of: asOf })}`),
  orphaned: (asOf) => req(`/audit/orphaned-access${q({ as_of: asOf })}`),
  reseed: () => req('/admin/reseed', { method: 'POST' }),
}

export const fmtTime = (ms) => (ms ? new Date(ms).toLocaleString() : '')
export const money = (n) =>
  n === null || n === undefined ? '' : Number(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
