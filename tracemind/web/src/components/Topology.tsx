import type { Span } from '../api/types'

interface Props {
  services: string[]
  edges: [string, string][]
  spans?: Span[]
}

/** Layered left-to-right SVG dependency graph. Dashed nodes have no spans in the loaded trace (inferred). */
export default function Topology({ services, edges, spans }: Props) {
  const names = Array.from(new Set([...services, ...edges.flat()]))
  const depth: Record<string, number> = {}
  names.forEach((n) => (depth[n] = 0))
  for (let pass = 0; pass < names.length; pass++)
    for (const [a, b] of edges) if (depth[b] <= depth[a]) depth[b] = Math.min(depth[a] + 1, names.length)
  const layers: string[][] = []
  names.forEach((n) => (layers[depth[n]] ??= []).push(n))
  const cols = layers.filter(Boolean)
  const W = 150, H = 58, GX = 70, GY = 30
  const pos: Record<string, { x: number; y: number }> = {}
  const maxRows = Math.max(...cols.map((c) => c.length), 1)
  cols.forEach((col, ci) =>
    col.forEach((n, ri) => {
      const offset = ((maxRows - col.length) * (H + GY)) / 2
      pos[n] = { x: 16 + ci * (W + GX), y: 16 + offset + ri * (H + GY) }
    }),
  )
  const width = 32 + cols.length * W + (cols.length - 1) * GX
  const height = 32 + maxRows * H + (maxRows - 1) * GY
  const stat = (n: string) => {
    const s = (spans ?? []).filter((x) => x.service_name === n)
    return { count: s.length, errors: s.filter((x) => x.status_code === 'ERROR').length }
  }
  return (
    <div className="topo" role="img" aria-label={`Service topology: ${edges.map(([a, b]) => `${a} calls ${b}`).join(', ')}`}>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', maxWidth: width * 1.3, height: 'auto' }}>
        <defs>
          <marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0 0L8 4L0 8z" fill="var(--text-3)" />
          </marker>
        </defs>
        {edges.map(([a, b]) => {
          const pa = pos[a], pb = pos[b]
          if (!pa || !pb) return null
          const x1 = pa.x + W, y1 = pa.y + H / 2, x2 = pb.x - 2, y2 = pb.y + H / 2
          const mx = (x1 + x2) / 2
          return <path key={a + b} d={`M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`} fill="none" stroke="var(--text-3)" strokeWidth="1.4" markerEnd="url(#arr)" />
        })}
        {names.map((n) => {
          const p = pos[n]
          const { count, errors } = stat(n)
          const inferred = spans !== undefined && count === 0
          const bad = errors > 0
          return (
            <g key={n} transform={`translate(${p.x},${p.y})`}>
              <rect width={W} height={H} rx="9" className={`tnode ${bad ? 'tnode-bad' : ''} ${inferred ? 'tnode-inf' : ''}`} />
              <text x="14" y="25" className="tnode-name">{n}</text>
              <text x="14" y="43" className="tnode-sub">
                {inferred ? 'inferred · no spans' : spans ? `${count} spans${bad ? ` · ${errors} error` : ''}` : ''}
              </text>
              {bad && <circle cx={W - 14} cy="16" r="5" fill="var(--bad)" />}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
