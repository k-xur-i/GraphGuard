import { useEffect, useState } from 'react'

export function Select({ label, value, onChange, options, placeholder, disabled }) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value ?? ''} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
      </select>
    </label>
  )
}

export const LevelBadge = ({ level }) =>
  level ? <span className={`badge lvl-${level}`}>{level}</span> : <span className="badge lvl-NONE">NO ACCESS</span>

// A path like  Ravi -[MEMBER_OF]-> Family -[HAS_ACCESS_TO]-> Account  drawn as chips
export function PathChips({ steps }) {
  if (!steps || !steps.length) return null
  const out = [<span key="n0" className="chip node">{steps[0].src_name}</span>]
  steps.forEach((s, i) => {
    out.push(<span key={`r${i}`} className="chip rel">{s.forward ? `${s.rel_type} →` : `← ${s.rel_type}`}</span>)
    out.push(<span key={`n${i + 1}`} className="chip node">{s.dst_name}</span>)
  })
  return <div className="pathchips">{out}</div>
}

// Turn an access-check path into the node/link sets GraphView highlights
export function toHighlight(steps) {
  const nodes = new Set(), links = new Set()
  ;(steps || []).forEach((s) => {
    nodes.add(s.src_id); nodes.add(s.dst_id)
    links.add([s.src_id, s.dst_id].sort().join('|'))
  })
  return { nodes, links }
}

export function useLoad(fn, deps) {
  const [state, set] = useState({ data: null, error: '', loading: true })
  useEffect(() => {
    let live = true
    set((s) => ({ ...s, loading: true }))
    fn().then((data) => live && set({ data, error: '', loading: false }))
        .catch((e) => live && set({ data: null, error: e.message, loading: false }))
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}

export const Msg = ({ kind, children }) => (children ? <div className={`msg ${kind}`}>{children}</div> : null)
