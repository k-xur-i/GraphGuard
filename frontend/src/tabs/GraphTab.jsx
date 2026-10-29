import { useState } from 'react'
import { api, fmtTime } from '../api'
import GraphView from '../components/GraphView'
import { LevelBadge, Msg, Select, useLoad } from '../components/ui'

export default function GraphTab({ users, groups, accounts, asOf, past, tick, refresh, focus, setFocus, highlight, setHighlight }) {
  const graph = useLoad(() => api.graph(focus, asOf), [focus, asOf, tick])
  const who = useLoad(() => api.whoHasAccess(focus, asOf), [focus, asOf, tick])
  const [f, setF] = useState({ actor: 'u_suresh', subject: 'u_dev', rel: 'AUTHORIZED_SIGNATORY_OF', target: 'a_kt', level: 'TRANSACT' })
  const [msg, setMsg] = useState({ kind: '', text: '' })
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }))

  const isMember = f.rel === 'MEMBER_OF'
  const subjects = isMember ? users : [...users, ...groups]
  const targets = isMember ? groups : accounts

  const run = async (kind) => {
    setMsg({ kind: '', text: '' })
    const body = { subject_id: f.subject, target_id: f.target, rel_type: f.rel, actor_id: f.actor, level: f.level }
    try {
      if (kind === 'grant') await api.grant(body)
      else await api.revoke({ subject_id: f.subject, target_id: f.target, rel_type: f.rel, actor_id: f.actor })
      setMsg({ kind: 'ok', text: kind === 'grant' ? 'Access granted and logged.' : 'Access revoked and logged. The edge is kept (dashed) for the audit trail.' })
      setHighlight(null)
      refresh()
    } catch (e) { setMsg({ kind: 'bad', text: e.message }) }
  }

  return (
    <div className="grid2">
      <section className="card wide">
        <div className="row">
          <Select label="Account to show (its whole parent / sub-account tree is drawn)" value={focus} onChange={setFocus}
                  options={accounts} />
          {highlight && <button className="link" onClick={() => setHighlight(null)}>clear highlighted path</button>}
        </div>
        <Msg kind="bad">{graph.error}</Msg>
        {graph.data && <GraphView data={graph.data} highlight={highlight} />}
        <p className="hint">
          Dashed grey = access that was revoked (kept for audit). Dotted teal = sub-account that does <b>not</b> inherit
          from its parent. Hover a node for details.
        </p>
      </section>

      <section className="card">
        <h3>Who has access {past ? `(as of ${fmtTime(asOf)})` : 'now'}</h3>
        <Msg kind="bad">{who.error}</Msg>
        <table>
          <thead><tr><th>User</th><th>Level</th><th>Reached via</th></tr></thead>
          <tbody>
            {(who.data || []).map((r) => (
              <tr key={r.user_id}><td>{r.name}</td><td><LevelBadge level={r.level} /></td><td className="small">{r.via.join(' → ')}</td></tr>
            ))}
            {who.data && !who.data.length && <tr><td colSpan="3" className="muted">Nobody.</td></tr>}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h3>Grant or revoke access</h3>
        <p className="hint">Only an account owner (or the group admin) is allowed. Try it with the wrong actor to see the denial get logged.</p>
        <Select label="Acting user" value={f.actor} onChange={set('actor')} options={users} />
        <Select label="Relationship" value={f.rel} onChange={(v) => setF((x) => ({ ...x, rel: v, subject: '', target: '' }))}
                options={[{ id: 'OWNS', name: 'OWNS' }, { id: 'AUTHORIZED_SIGNATORY_OF', name: 'AUTHORIZED_SIGNATORY_OF' },
                          { id: 'HAS_ACCESS_TO', name: 'HAS_ACCESS_TO' }, { id: 'MEMBER_OF', name: 'MEMBER_OF (join a group)' }]} />
        <Select label={isMember ? 'User' : 'User or group'} value={f.subject} onChange={set('subject')} options={subjects} placeholder="choose…" />
        <Select label={isMember ? 'Group' : 'Account'} value={f.target} onChange={set('target')} options={targets} placeholder="choose…" />
        {f.rel === 'HAS_ACCESS_TO' && (
          <Select label="Level" value={f.level} onChange={set('level')} options={[{ id: 'VIEW', name: 'VIEW' }, { id: 'TRANSACT', name: 'TRANSACT' }]} />
        )}
        <div className="row">
          <button disabled={past || !f.subject || !f.target} onClick={() => run('grant')}>Grant</button>
          <button className="danger" disabled={past || !f.subject || !f.target} onClick={() => run('revoke')}>Revoke</button>
        </div>
        <Msg kind={msg.kind}>{msg.text}</Msg>
      </section>
    </div>
  )
}
