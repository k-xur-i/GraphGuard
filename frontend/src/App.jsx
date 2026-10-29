import { useEffect, useState } from 'react'
import { api } from './api'
import GraphTab from './tabs/GraphTab'
import CheckTab from './tabs/CheckTab'
import TxTab from './tabs/TxTab'
import AuditTab from './tabs/AuditTab'

const HOUR = 3600000
const DAY = 24 * HOUR
const PRESETS = [
  ['now', 'Now', null],
  ['1h', '1 hour ago', HOUR],
  ['1d', '1 day ago', DAY],
  ['7d', '1 week ago', 7 * DAY],
  ['30d', '1 month ago', 30 * DAY],
  ['65d', '65 days ago', 65 * DAY],
]

export default function App() {
  const [lookups, setLookups] = useState({ users: [], groups: [], accounts: [] })
  const [error, setError] = useState('')
  const [tab, setTab] = useState('graph')
  const [preset, setPreset] = useState('now')
  const [custom, setCustom] = useState('')
  const [tick, setTick] = useState(0) // bump to force every tab to reload after a write
  const [focus, setFocus] = useState('a_kt')
  const [highlight, setHighlight] = useState(null) // {nodes:Set, links:Set} from "explain access"

  // asOf is epoch ms, or null for "now". It is recomputed when the preset changes.
  const [asOf, setAsOf] = useState(null)
  useEffect(() => {
    if (preset === 'custom') setAsOf(custom ? new Date(custom).getTime() : null)
    else {
      const p = PRESETS.find((x) => x[0] === preset)
      setAsOf(p[2] ? Date.now() - p[2] : null)
    }
  }, [preset, custom])

  useEffect(() => {
    Promise.all([api.users(), api.groups(), api.accounts()])
      .then(([users, groups, accounts]) => setLookups({ users, groups, accounts }))
      .catch((e) => setError(e.message))
  }, [tick])

  const ctx = { ...lookups, asOf, past: asOf !== null, refresh: () => setTick((t) => t + 1), tick,
                focus, setFocus, highlight, setHighlight, goto: setTab }
  const tabs = [['graph', 'Access graph'], ['check', 'Why can they access?'], ['tx', 'Transactions'], ['audit', 'Audit & security']]

  return (
    <div className="app">
      <header>
        <div className="brand">
          <span className="logo">&#9670;</span> GraphGuard
          <small>Graph-based access control &amp; audit for shared bank accounts (simulated data)</small>
        </div>
        <div className="timebar">
          <label>View the system as of</label>
          <select value={preset} onChange={(e) => setPreset(e.target.value)}>
            {PRESETS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            <option value="custom">Custom date&hellip;</option>
          </select>
          {preset === 'custom' && <input type="datetime-local" value={custom} onChange={(e) => setCustom(e.target.value)} />}
        </div>
      </header>

      {ctx.past && (
        <div className="banner time">
          Time travel: showing access as it was on <b>{new Date(asOf).toLocaleString()}</b>. Changes are disabled
          while viewing the past.
        </div>
      )}
      {error && <div className="banner error">Cannot reach the API: {error}. Is the backend running and seeded?</div>}

      <nav>
        {tabs.map(([k, label]) => (
          <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{label}</button>
        ))}
      </nav>

      <main>
        {tab === 'graph' && <GraphTab {...ctx} />}
        {tab === 'check' && <CheckTab {...ctx} />}
        {tab === 'tx' && <TxTab {...ctx} />}
        {tab === 'audit' && <AuditTab {...ctx} />}
      </main>
    </div>
  )
}
