import { useState } from 'react'
import { api, fmtTime, money } from '../api'
import { LevelBadge, Msg, PathChips, Select, toHighlight } from '../components/ui'

export default function CheckTab({ users, accounts, asOf, past, setHighlight, setFocus, goto }) {
  const [user, setUser] = useState('u_lakshmi')
  const [account, setAccount] = useState('a_kt_payroll')
  const [res, setRes] = useState(null)
  const [list, setList] = useState(null)
  const [err, setErr] = useState('')

  const run = async () => {
    setErr('')
    try {
      const [r, l] = await Promise.all([api.check(user, account, asOf), api.userAccounts(user, asOf)])
      setRes(r); setList(l)
      setHighlight(r.allowed ? toHighlight(r.path) : null)
    } catch (e) { setErr(e.message) }
  }

  const show = () => { setFocus(account); goto('graph') }

  return (
    <div className="grid2">
      <section className="card">
        <h3>Can this user access this account{past ? ` (as of ${fmtTime(asOf)})` : ''}?</h3>
        <Select label="User" value={user} onChange={setUser} options={users} />
        <Select label="Account" value={account} onChange={setAccount} options={accounts} />
        <button onClick={run}>Explain access</button>
        <Msg kind="bad">{err}</Msg>

        {res && (
          <div className="result">
            <div className="row">
              <LevelBadge level={res.level} />
              <b>{res.allowed ? (res.can_transact ? 'Can view and transact' : 'Can view only') : 'No active access path'}</b>
            </div>
            {res.allowed ? (
              <>
                <p className="hint">Strongest, shortest path ({res.hops} edge{res.hops > 1 ? 's' : ''}); access has been in effect since {fmtTime(res.access_since)}:</p>
                <PathChips steps={res.path} />
                {res.alternatives.length > 0 && (
                  <details><summary>{res.alternatives.length} other path(s)</summary>
                    {res.alternatives.map((a, i) => <div key={i}><LevelBadge level={a.level} /><PathChips steps={a.path} /></div>)}
                  </details>
                )}
                <button className="link" onClick={show}>show this path in the graph</button>
              </>
            ) : (
              <p className="hint">No chain of OWNS / AUTHORIZED_SIGNATORY_OF / HAS_ACCESS_TO (directly, through a group, or inherited from a parent
                account) was active at that time.</p>
            )}
          </div>
        )}
      </section>

      <section className="card">
        <h3>Everything this user can reach</h3>
        {!list && <p className="muted">Run “Explain access” to list every account the selected user can reach.</p>}
        {list && (
          <table>
            <thead><tr><th>Account</th><th>Level</th><th>Balance</th><th>Via</th></tr></thead>
            <tbody>
              {list.map((a) => (
                <tr key={a.account_id}><td>{a.name}</td><td><LevelBadge level={a.level} /></td>
                  <td className="num">{money(a.balance)}</td><td className="small">{a.via.join(' → ')}</td></tr>
              ))}
              {!list.length && <tr><td colSpan="4" className="muted">No accounts.</td></tr>}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
