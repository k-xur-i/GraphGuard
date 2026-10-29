import { useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'

const COLORS = { User: '#3b82f6', Group: '#a855f7', Account: '#16a34a', SubAccount: '#0d9488' }
const LINK = { OWNS: '#16a34a', AUTHORIZED_SIGNATORY_OF: '#2563eb', HAS_ACCESS_TO: '#7c3aed', MEMBER_OF: '#9ca3af', PART_OF: '#0d9488' }
const id = (x) => (typeof x === 'object' ? x.id : x)
const key = (a, b) => [id(a), id(b)].sort().join('|')

export default function GraphView({ data, highlight, height = 520 }) {
  const box = useRef(null)
  const fg = useRef(null)
  const [width, setWidth] = useState(800)
  const [hover, setHover] = useState(null)

  useEffect(() => {
    if (!box.current) return
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(300, e.contentRect.width)))
    ro.observe(box.current)
    return () => ro.disconnect()
  }, [])

  // force-graph mutates its input, so hand it a fresh copy each time the data changes
  const graph = useMemo(() => ({
    nodes: data.nodes.map((n) => ({ ...n })),
    links: data.links.map((l) => ({ ...l })),
  }), [data])

  // spread the nodes out, then fit the whole graph in view once it settles
  useEffect(() => {
    const g = fg.current
    if (!g) return
    g.d3Force('charge').strength(-520)
    g.d3Force('link').distance(135)
    g.d3ReheatSimulation()
  }, [graph])

  const hn = highlight?.nodes, hl = highlight?.links
  const linkHot = (l) => hl && hl.has(key(l.source, l.target))

  return (
    <div className="graphbox" ref={box}>
      <ForceGraph2D
        ref={fg}
        graphData={graph}
        onEngineStop={() => fg.current && fg.current.zoomToFit(400, 90)}
        width={width}
        height={height}
        cooldownTicks={140}
        nodeRelSize={6}
        linkDirectionalArrowLength={5}
        linkDirectionalArrowRelPos={0.92}
        linkColor={(l) => (linkHot(l) ? '#f97316' : l.active ? LINK[l.type] : '#c7cbd1')}
        linkWidth={(l) => (linkHot(l) ? 4 : l.active ? 1.6 : 1)}
        linkLineDash={(l) => (!l.active ? [4, 3] : l.type === 'PART_OF' && l.inherits === false ? [2, 2] : null)}
        onNodeHover={setHover}
        nodeCanvasObject={(n, ctx, scale) => {
          const r = n.type === 'User' ? 5 : 7
          ctx.beginPath()
          ctx.arc(n.x, n.y, r, 0, 2 * Math.PI)
          ctx.fillStyle = COLORS[n.type] || '#64748b'
          ctx.fill()
          if (n.focus || (hn && hn.has(n.id))) {
            ctx.lineWidth = 2.5 / scale
            ctx.strokeStyle = '#f97316'
            ctx.stroke()
          }
          const fs = 11 / scale
          ctx.font = `${fs}px system-ui, sans-serif`
          ctx.textAlign = 'center'
          const w = ctx.measureText(n.name).width
          ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--bg') || '#fff'
          ctx.globalAlpha = 0.75
          ctx.fillRect(n.x - w / 2 - 2, n.y + r + 1, w + 4, fs + 3)
          ctx.globalAlpha = 1
          ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--fg') || '#111'
          ctx.fillText(n.name, n.x, n.y + r + fs)
        }}
        nodePointerAreaPaint={(n, color, ctx) => {
          ctx.fillStyle = color
          ctx.beginPath()
          ctx.arc(n.x, n.y, 9, 0, 2 * Math.PI)
          ctx.fill()
        }}
      />
      <div className="legend">
        {Object.entries(COLORS).map(([k, c]) => <span key={k}><i style={{ background: c }} />{k}</span>)}
        <span><i className="line" />active edge</span>
        <span><i className="line dashed" />revoked edge</span>
        <span><i className="line orange" />explained path</span>
      </div>
      {hover && (
        <div className="tip">
          <b>{hover.name}</b> · {hover.type}
          {hover.kind ? ` · ${hover.kind}` : ''}
          {hover.balance !== undefined && hover.balance !== null ? ` · balance ${Number(hover.balance).toLocaleString('en-IN')}` : ''}
        </div>
      )}
    </div>
  )
}
