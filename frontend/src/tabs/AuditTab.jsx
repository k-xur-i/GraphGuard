import { useState } from 'react'
import { api, fmtTime, money } from '../api'
import { Msg, Select, useLoad } from '../components/ui'

export default function AuditTab({ accounts, asOf, tick, refresh, past }) {
  const [account, setAccount] = useState('a_kt')
  const events = useLoad(() => api.events(account, asOf), [account, asOf, tick])
  const flagged = useLoad(() => api.flagged(), [tick])
  const orphans = useLoad(() => api.orphaned(asOf), [asOf, tick])
  const diff = useLoad(() => api.accessDiff(account, Date.now() - 30 * 86400000, Date.now()), [account, tick])
  const stats = useLoad(() => api.stats(), [tick])
  const [msg, setMsg] = useState('')

  const reseed = async () => {
    if (!window.confirm('Reset all data back to the original demo dataset?')) return
    try { await api.reseed(); setMsg('Demo data restored.'); refresh() } catch (e) { setMsg(e.message) }
  }

  return (
    <div className="stack">
      <section className="card">
        <div className="row">
          <Select label="Account" value={account} onChange={setAccount} options={accounts} />
        </div>
        <h3>Access changes in the last 30 days</h3>
        <Msg kind="bad">{diff.error}</Msg>
        {diff.data && (
          <div className="diff">
            <div><h4>Lost access ({diff.data.lost.length})</h4>{diff.data.lost.map((u) => <div key={u.user_id} className="lost">− {u.name} <small>({u.level})</small></div>)}</div>
            <div><h4>Gained access ({diff.data.gained.length})</h4>{diff.data.gained.map((u) => <div key={u.user_id} className="gained">+ {u.name} <small>({u.level})</small></div>)}</div>
            <div><h4>Unchanged ({diff.data.unchanged.length})</h4>{diff.data.unchanged.map((u) => <div key={u.user_id} className="muted">{u.name} <small>({u.level})</small></div>)}</div>
          </div>
        )}
      </section>

      <section className="card">
        <h3>Access audit log {past && `(up to ${fmtTime(asOf)})`}</h3>
        <Msg kind="bad">{events.error}</Msg>
        <div className="scroll short">
          <table>
            <thead><tr><th>When</th><th>Event</th><th>Subject</th><th>Relationship</th><th>Target</th><th>By</th><th>Reason</th></tr></thead>
            <tbody>
              {(events.data || []).map((e) => (
                <tr key={e.id}><td className="small">{fmtTime(e.ts)}</td><td><span className={`badge ev-${e.type}`}>{e.type}</span></td>
                  <td>{e.subject_name}</td><td className="small">{e.rel_type}{e.level && e.level !== 'MEMBER' ? ` (${e.level})` : ''}</td>
                  <td>{e.target_name}</td><td>{e.actor_name}</td><td className="small">{e.reason}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint">Events are append-only: revoking access never deletes anything, it adds a REVOKE event and stamps the edge with <code>revoked_at</code>.</p>
      </section>

      <section className="card">
        <h3>Orphaned access — worth reviewing</h3>
        <p className="hint">People with a direct grant on a sub-account who have no access to its parent. Often a leftover from someone who left.</p>
        <Msg kind="bad">{orphans.error}</Msg>
        <table>
          <thead><tr><th>User</th><th>Sub-account</th><th>Parent (no access)</th><th>Grant</th><th>Since</th><th>Inherits?</th></tr></thead>
          <tbody>
            {(orphans.data || []).map((o, i) => (
              <tr key={i}><td>{o.user_name}</td><td>{o.sub_name}</td><td>{o.parent_name}</td><td className="small">{o.grant_type}{o.level ? ` (${o.level})` : ''}</td>
                <td className="small">{fmtTime(o.granted_at)}</td><td>{o.inherits === false ? 'no' : 'yes'}</td></tr>
            ))}
            {orphans.data && !orphans.data.length && <tr><td colSpan="6" className="muted">None found.</td></tr>}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h3>Flagged transactions</h3>
        <Msg kind="bad">{flagged.error}</Msg>
        <div className="scroll short">
          <table>
            <thead><tr><th>When</th><th>Account</th><th>By</th><th>Type</th><th className="num">Amount</th><th>Why flagged</th><th>Access path used</th></tr></thead>
            <tbody>
              {(flagged.data || []).map((t) => (
                <tr key={t.id}><td className="small">{fmtTime(t.ts)}</td><td>{t.account_name}</td><td>{t.actor}</td><td>{t.type}</td>
                  <td className="num">{money(t.amount)}</td><td className="small">{(t.flag_reasons || []).join(', ')}</td><td className="small">{t.access_path}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h3>Database size</h3>
        {stats.data && (
          <div className="row wrap small">
            <div><b>Nodes</b>{stats.data.nodes.map((n) => <div key={n.label}>{n.label}: {n.count}</div>)}</div>
            <div><b>Relationships</b>{stats.data.relationships.map((n) => <div key={n.type}>{n.type}: {n.count}</div>)}</div>
          </div>
        )}
        <button className="danger" onClick={reseed}>Reset demo data</button> <span className="muted small">{msg}</span>
      </section>
    </div>
  )
}
