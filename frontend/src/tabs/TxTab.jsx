import { useState } from 'react'
import { api, fmtTime, money } from '../api'
import { LevelBadge, Msg, Select, useLoad } from '../components/ui'

const REASONS = {
  LARGE_AMOUNT: 'much larger than this account’s usual transaction',
  HIGH_VELOCITY: 'many transactions by one user within 10 minutes',
  NEW_ACCESS_LARGE_TX: 'large transaction soon after the user was given access',
}

export default function TxTab({ users, accounts, asOf, past, tick, refresh }) {
  const [mode, setMode] = useState('account')
  const [account, setAccount] = useState('a_kt')
  const [viewer, setViewer] = useState('')
  const [who, setWho] = useState('u_dev')
  const rows = useLoad(
    () => (mode === 'account' ? api.statement(account, asOf, viewer || null) : api.visibleTx(who, asOf)),
    [mode, account, viewer, who, asOf, tick])

  const [f, setF] = useState({ user: 'u_priya', type: 'TRANSFER', amount: 450000, to: 'a_kt_payroll', note: 'Urgent vendor payment' })
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }))
  const [res, setRes] = useState({ kind: '', text: '' })

  const submit = async () => {
    setRes({ kind: '', text: '' })
    try {
      const r = await api.newTx({ user_id: f.user, account_id: account, type: f.type, amount: Number(f.amount),
                                  to_account_id: f.type === 'TRANSFER' ? f.to : null, note: f.note })
      const flag = r.flagged ? ` FLAGGED: ${r.flag_reasons.map((x) => REASONS[x] || x).join('; ')}.` : ''
      setRes({ kind: r.flagged ? 'warn' : 'ok', text: `Recorded as ${r.transaction_id} (access: ${r.access_level}). Balance after: ${money(r.balance_after)}.${flag}` })
      refresh()
    } catch (e) { setRes({ kind: 'bad', text: `${e.message} — the attempt was logged in the audit trail.` }) }
  }

  return (
    <div className="grid2">
      <section className="card wide">
        <div className="row">
          <Select label="View" value={mode} onChange={setMode} options={[
            { id: 'account', name: 'Statement of one account' }, { id: 'user', name: 'Everything one user could see' }]} />
          {mode === 'account' ? (
            <>
              <Select label="Account" value={account} onChange={setAccount} options={accounts} />
              <Select label="Only if this user had access (optional)" value={viewer} onChange={setViewer} options={users} placeholder="— no check —" />
            </>
          ) : <Select label="User" value={who} onChange={setWho} options={users} />}
        </div>
        {past && <p className="hint">Showing the ledger up to {fmtTime(asOf)}. Access checks use the access state of that moment.</p>}
        <Msg kind="bad">{rows.error}</Msg>
        <div className="scroll">
          <table>
            <thead><tr><th>Date</th>{mode === 'user' && <th>Account</th>}<th>Description</th><th>By</th><th>Access at the time</th>
              <th className="num">Debit</th><th className="num">Credit</th><th className="num">Balance</th><th></th></tr></thead>
            <tbody>
              {(rows.data || []).map((r) => (
                <tr key={r.id + r.leg + r.account_id} className={r.flagged ? 'flag' : ''}>
                  <td className="small">{fmtTime(r.ts)}</td>
                  {mode === 'user' && <td className="small">{r.account_name}</td>}
                  <td>{r.type}{r.type === 'TRANSFER' ? (r.direction === 'DEBIT' ? ` → ${r.to_account}` : ` ← ${r.from_account}`) : ''}<div className="small muted">{r.note}</div></td>
                  <td>{r.actor}</td>
                  <td title={r.access_path}><LevelBadge level={r.access_level} /></td>
                  <td className="num">{r.direction === 'DEBIT' ? money(r.amount) : ''}</td>
                  <td className="num">{r.direction === 'CREDIT' ? money(r.amount) : ''}</td>
                  <td className="num">{money(r.balance_after)}</td>
                  <td>{r.flagged && <span className="badge flagb" title={(r.flag_reasons || []).map((x) => REASONS[x] || x).join('; ')}>⚑ flagged</span>}</td>
                </tr>
              ))}
              {rows.data && !rows.data.length && <tr><td colSpan="9" className="muted">No transactions.</td></tr>}
            </tbody>
          </table>
        </div>
        <p className="hint">Hover the access badge to see the exact path that justified each transaction when it happened.</p>
      </section>

      <section className="card">
        <h3>New transaction (simulated money)</h3>
        <p className="hint">Posts to the account chosen above. Defaults reproduce the suspicious-transfer demo: a brand-new signatory moves a large amount.</p>
        <Select label="Acting user" value={f.user} onChange={set('user')} options={users} />
        <Select label="Type" value={f.type} onChange={set('type')} options={['DEPOSIT', 'WITHDRAWAL', 'TRANSFER'].map((x) => ({ id: x, name: x }))} />
        <label className="field"><span>Amount</span><input type="number" min="1" value={f.amount} onChange={(e) => set('amount')(e.target.value)} /></label>
        {f.type === 'TRANSFER' && <Select label="To account" value={f.to} onChange={set('to')} options={accounts.filter((a) => a.id !== account)} />}
        <label className="field"><span>Note</span><input value={f.note} maxLength={140} onChange={(e) => set('note')(e.target.value)} /></label>
        <button disabled={past || mode !== 'account'} onClick={submit}>Submit transaction</button>
        {mode !== 'account' && <p className="hint">Switch to “Statement of one account”.</p>}
        <Msg kind={res.kind}>{res.text}</Msg>
      </section>
    </div>
  )
}
