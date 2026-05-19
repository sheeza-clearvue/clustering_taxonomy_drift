import { useEffect, useState, lazy, Suspense } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  MousePointer2, RotateCcw, Move, ZoomIn, Maximize2,
  Layers, Tag, AlertTriangle, GitBranch, Cpu, Activity,
  Box, ChevronDown, Orbit,
} from 'lucide-react'
import useStore from '../store/useStore.js'
import RightInspector from '../components/layout/RightInspector.jsx'
import { getFieldColor } from '../components/scene/sceneUtils.js'

const SemanticScene = lazy(() => import('../components/scene/SemanticScene.jsx'))

// ── View control buttons config ────────────────────────────────────────────────
const VIEW_CONTROLS = [
  { id: 'select',     Icon: MousePointer2, label: 'Select' },
  { id: 'orbit',      Icon: Orbit,         label: 'Orbit' },
  { id: 'pan',        Icon: Move,          label: 'Pan' },
  { id: 'zoom',       Icon: ZoomIn,        label: 'Zoom' },
  { id: 'fullscreen', Icon: Maximize2,     label: 'Fullscreen' },
  { id: 'density',    Icon: Layers,        label: 'Density' },
  { id: 'cluster',    Icon: Box,           label: 'Cluster' },
  { id: 'labels',     Icon: Tag,           label: 'Labels' },
]

// ── Mini sparkline (no gradient, just glowing line) ────────────────────────────
function Sparkline({ seed = 2.1, color = '#00d4ff', width = 78, height = 30 }) {
  const pts = Array.from({ length: 10 }, (_, i) => {
    const base = 0.2 + 0.55 * (i / 9)
    const wave = Math.sin(i * seed * 2.7 + seed * 0.9) * 0.14
    return Math.max(0.05, Math.min(0.95, base + wave))
  })
  const w = width, h = height
  const d = pts
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * w / 9).toFixed(1)},${(h - v * h * 0.86 - 2).toFixed(1)}`)
    .join(' ')
  const lx = w.toFixed(1)
  const ly = (h - pts[9] * h * 0.86 - 2).toFixed(1)
  return (
    <svg width={w} height={h} style={{ display: 'block', overflow: 'visible' }}>
      <path d={d} stroke={color} strokeWidth="1.5" fill="none" strokeLinejoin="round" opacity={0.8} />
      <circle cx={lx} cy={ly} r="2.5" fill={color} style={{ filter: `drop-shadow(0 0 4px ${color})` }} />
    </svg>
  )
}

// ── Anomaly donut ring ─────────────────────────────────────────────────────────
function AnomalyDonut({ pct = 0.08, color = '#ef4444' }) {
  const r = 15, cx = 19, cy = 19
  const circ = 2 * Math.PI * r
  const used = Math.max(0, Math.min(1, pct)) * circ
  return (
    <svg width={38} height={38} style={{ flexShrink: 0 }}>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={3.5} />
      <circle
        cx={cx} cy={cy} r={r} fill="none"
        stroke={color} strokeWidth={3.5}
        strokeDasharray={`${used.toFixed(1)} ${circ.toFixed(1)}`}
        strokeLinecap="round"
        transform={`rotate(-90 ${cx} ${cy})`}
        style={{ filter: `drop-shadow(0 0 4px ${color}99)` }}
      />
      <text x={cx} y={cy + 3.5} textAnchor="middle" fontSize="7.5" fill={color} fontWeight="700">
        {Math.round(pct * 100)}%
      </text>
    </svg>
  )
}

// ── Bottom metric card container ───────────────────────────────────────────────
function BottomCard({ label, color, children }) {
  return (
    <div
      className="flex flex-col gap-1.5 px-3 pt-2.5 pb-2 rounded-xl flex-shrink-0"
      style={{
        background: 'rgba(6,13,26,0.92)',
        border: `1px solid ${color}28`,
        backdropFilter: 'blur(16px)',
        boxShadow: `0 4px 24px rgba(0,0,0,0.55), 0 0 28px ${color}08`,
        minWidth: 148,
        maxWidth: 195,
      }}
    >
      <div className="text-[8.5px] uppercase tracking-[0.22em] font-bold" style={{ color: color + 'aa' }}>
        {label}
      </div>
      {children}
    </div>
  )
}

// ── Left panel section divider ─────────────────────────────────────────────────
function CtrlSection({ label, children }) {
  return (
    <div className="flex-shrink-0">
      <div className="text-[8px] uppercase tracking-[0.22em] font-bold pb-1.5" style={{ color: '#1e3450' }}>
        {label}
      </div>
      {children}
    </div>
  )
}

// ── Toggle switch ──────────────────────────────────────────────────────────────
function Toggle({ label, value, onChange, color = '#00d4ff' }) {
  return (
    <button
      onClick={() => onChange(!value)}
      className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg transition-all duration-150"
      style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(26,45,74,0.5)' }}
    >
      <span className="text-[10px]" style={{ color: value ? '#94a3b8' : '#475569' }}>{label}</span>
      <div
        className="relative rounded-full transition-all duration-200"
        style={{
          width: 28, height: 14,
          background: value ? color + '40' : 'rgba(26,45,74,0.8)',
          border: `1px solid ${value ? color + '70' : 'rgba(26,45,74,0.6)'}`,
        }}
      >
        <div
          className="absolute top-0.5 rounded-full transition-all duration-200"
          style={{
            width: 10, height: 10,
            background: value ? color : '#334155',
            left: value ? 15 : 2,
            boxShadow: value ? `0 0 6px ${color}` : 'none',
          }}
        />
      </div>
    </button>
  )
}

// ── Field chip ─────────────────────────────────────────────────────────────────
function FieldChip({ field, active, count, onClick }) {
  const color = getFieldColor(field)
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-left transition-all duration-150"
      style={active
        ? { background: color + '18', border: `1px solid ${color}44`, boxShadow: `0 0 10px ${color}18` }
        : { background: 'transparent', border: '1px solid transparent' }
      }
    >
      <span
        className="w-1.5 h-1.5 rounded-full flex-shrink-0"
        style={{ background: active ? color : '#1e3450', boxShadow: active ? `0 0 5px ${color}` : 'none' }}
      />
      <span className="flex-1 text-[10px] truncate" style={{ color: active ? color : '#475569' }}>{field}</span>
      <span className="text-[9px]" style={{ color: active ? color + '88' : '#334155' }}>{count}</span>
    </button>
  )
}

// ── Default inspector (no cluster selected) ────────────────────────────────────
function DefaultInspector({ health, clusters, fields }) {
  const top5 = [...clusters].sort((a, b) => (b.cluster_size || 0) - (a.cluster_size || 0)).slice(0, 5)
  return (
    <div className="flex flex-col h-full overflow-y-auto" style={{ scrollbarWidth: 'thin', scrollbarColor: '#1a2d4a transparent' }}>
      {/* Header */}
      <div className="px-4 py-4 flex-shrink-0" style={{ borderBottom: '1px solid rgba(26,45,74,0.5)' }}>
        <div className="text-[9px] uppercase tracking-[0.2em] font-bold mb-1" style={{ color: '#00d4ff88' }}>
          Cluster Inspector
        </div>
        <div className="text-[13px] font-semibold text-dust mb-0.5">Select a node</div>
        <div className="text-[10px]" style={{ color: '#475569' }}>Click any cluster in the semantic space to inspect its intelligence data.</div>
        <div className="mt-3 h-px" style={{ background: 'linear-gradient(90deg, rgba(0,212,255,0.3), transparent)' }} />
      </div>

      {/* System overview metrics */}
      {health && (
        <div className="px-4 py-3 grid grid-cols-2 gap-2.5" style={{ borderBottom: '1px solid rgba(26,45,74,0.5)' }}>
          {[
            { v: (health.total_clusters || 0).toLocaleString(),  l: 'Clusters',  c: '#00d4ff' },
            { v: health.fields_count || '—',                      l: 'Fields',    c: '#a855f7' },
            { v: (health.named_clusters || 0).toLocaleString(),  l: 'Named',     c: '#10b981' },
            { v: (health.anomaly_clusters || 0).toLocaleString(), l: 'Anomalies', c: '#ef4444' },
          ].map(({ v, l, c }) => (
            <div key={l} className="flex flex-col items-center py-2.5 rounded-lg"
              style={{ background: 'rgba(255,255,255,0.02)', border: `1px solid ${c}18` }}>
              <span className="text-[16px] font-bold" style={{ color: c, textShadow: `0 0 12px ${c}44` }}>{v}</span>
              <span className="text-[8.5px] uppercase tracking-wider text-dust mt-0.5">{l}</span>
            </div>
          ))}
        </div>
      )}

      {/* Top clusters by size */}
      {top5.length > 0 && (
        <div className="px-4 py-3 flex-shrink-0" style={{ borderBottom: '1px solid rgba(26,45,74,0.5)' }}>
          <div className="text-[9px] uppercase tracking-[0.18em] text-dust/60 mb-2.5 font-bold">Largest Clusters</div>
          <div className="flex flex-col gap-1.5">
            {top5.map(c => {
              const fc = getFieldColor(c.field_name)
              return (
                <div key={c.id} className="flex items-center gap-2 px-2.5 py-2 rounded-lg"
                  style={{ background: 'rgba(255,255,255,0.02)', border: `1px solid ${fc}1a` }}>
                  <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: fc, boxShadow: `0 0 5px ${fc}` }} />
                  <span className="flex-1 text-[11px] truncate" style={{ color: '#94a3b8' }}>
                    {c.display_name || <em style={{ color: '#475569' }}>unnamed</em>}
                  </span>
                  <span className="text-[9.5px] flex-shrink-0" style={{ color: fc + 'cc' }}>
                    {(c.cluster_size || 0).toLocaleString()}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Field distribution bars */}
      {fields.length > 0 && (
        <div className="px-4 py-3">
          <div className="text-[9px] uppercase tracking-[0.18em] text-dust/60 mb-2.5 font-bold">Field Distribution</div>
          <div className="flex flex-col gap-2">
            {fields.slice(0, 7).map(([field, count]) => {
              const fc = getFieldColor(field)
              const total = fields.reduce((a, [, n]) => a + n, 0)
              const pct = total ? (count / total) * 100 : 0
              return (
                <div key={field} className="flex items-center gap-2">
                  <span className="text-[9.5px] truncate" style={{ color: fc, width: 80, flexShrink: 0 }}>{field}</span>
                  <div className="flex-1 h-1 rounded-full" style={{ background: 'rgba(26,45,74,0.7)' }}>
                    <div style={{
                      width: `${pct}%`, height: '100%', borderRadius: 999,
                      background: `linear-gradient(90deg, ${fc}cc, ${fc}55)`,
                      boxShadow: `0 0 6px ${fc}44`,
                      transition: 'width 0.8s ease',
                    }} />
                  </div>
                  <span className="text-[9px] text-dust flex-shrink-0" style={{ width: 28, textAlign: 'right' }}>{count}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Scene loading spinner ──────────────────────────────────────────────────────
function SceneLoader({ label = 'Initializing…' }) {
  return (
    <div className="flex items-center justify-center h-full flex-col gap-4">
      <div className="relative">
        <div className="w-14 h-14 rounded-full border-2 animate-spin" style={{ borderColor: 'rgba(0,212,255,0.15)', borderTopColor: '#00d4ff' }} />
        <div className="absolute inset-2 rounded-full border animate-spin" style={{ borderColor: 'rgba(168,85,247,0.1)', borderBottomColor: '#a855f7', animationDirection: 'reverse', animationDuration: '1.4s' }} />
      </div>
      <p className="text-xs tracking-widest uppercase" style={{ color: '#1e3450' }}>{label}</p>
    </div>
  )
}

// ── Observatory ────────────────────────────────────────────────────────────────
export default function Observatory() {
  const {
    selectedClusterId, setSelectedClusterId,
    activeField, setActiveField,
    projectionMode, setProjectionMode,
    showLabels, setShowLabels,
    anomalyFilter, setAnomalyFilter,
    triggerCameraReset,
    health,
  } = useStore()

  const [clusters,       setClusters]       = useState([])
  const [loading,        setLoading]        = useState(false)
  const [anomalySummary, setAnomalySummary] = useState(null)
  const [compression,    setCompression]    = useState(null)
  const [drift,          setDrift]          = useState(null)
  const [medoid,         setMedoid]         = useState(null)
  const [renderMode,     setRenderMode]     = useState('points')
  const [viewControl,    setViewControl]    = useState('orbit')
  const [sizeFilter,     setSizeFilter]     = useState(1)

  useEffect(() => {
    setLoading(true)

    // Fetch fields + analytics in parallel first, then fetch clusters per field
    // so every field is guaranteed a representative slice (not just the dominant one).
    Promise.allSettled([
      fetch('/api/fields').then(r => r.json()),
      fetch('/api/anomaly-intelligence').then(r => r.json()),
      fetch('/api/semantic-compression').then(r => r.json()),
      fetch('/api/drift-summary').then(r => r.json()),
      fetch('/api/medoid-intelligence').then(r => r.json()),
    ]).then(([fieldsRes, an, comp, dr, med]) => {
      if (an.status === 'fulfilled') setAnomalySummary(an.value?.summary)
      if (comp.status === 'fulfilled') setCompression(comp.value)
      if (dr.status === 'fulfilled') setDrift(dr.value)
      if (med.status === 'fulfilled') setMedoid(med.value)

      const fieldList = (fieldsRes.status === 'fulfilled' && Array.isArray(fieldsRes.value))
        ? fieldsRes.value
        : []

      if (fieldList.length === 0) {
        // Fallback: flat fetch when no field list available
        return fetch('/api/clusters?limit=1000').then(r => r.json()).then(data => {
          if (Array.isArray(data)) setClusters(data)
        })
      }

      // Per-field fetch: up to 600 clusters per field ensures all fields appear
      return Promise.allSettled(
        fieldList.map(f =>
          fetch(`/api/clusters?field_name=${encodeURIComponent(f)}&limit=600`)
            .then(r => r.json())
        )
      ).then(results => {
        const seen = new Set()
        const merged = results
          .filter(r => r.status === 'fulfilled' && Array.isArray(r.value))
          .flatMap(r => r.value)
          .filter(c => {
            const key = c.id ?? c.cluster_id
            if (seen.has(key)) return false
            seen.add(key)
            return true
          })
        setClusters(merged)
      })
    }).finally(() => setLoading(false))
  }, [])

  const displayClusters = clusters.filter(c => {
    if (activeField && c.field_name !== activeField)          return false
    if (anomalyFilter === 'anomaly'  && !c.is_true_anomaly_cluster) return false
    if (anomalyFilter === 'standard' &&  c.is_true_anomaly_cluster) return false
    if (sizeFilter > 1 && (c.cluster_size || 0) < sizeFilter)      return false
    return true
  })

  const fieldGroups = clusters.reduce((acc, c) => {
    acc[c.field_name] = (acc[c.field_name] || 0) + 1
    return acc
  }, {})
  const fields = Object.entries(fieldGroups).sort((a, b) => b[1] - a[1])

  const anomalyCount  = health?.anomaly_clusters || anomalySummary?.total || 0
  const totalClusters = health?.total_clusters || clusters.length || 0
  const namedCount    = health?.named_clusters || 0
  const coveragePct   = totalClusters ? namedCount / totalClusters : 0

  const showClusterLabels = showLabels || renderMode === 'labels'

  function handleViewControl(id) {
    if (id === 'fullscreen') {
      document.documentElement.requestFullscreen?.().catch(() => {})
    } else if (id === 'labels') {
      setShowLabels(!showLabels)
      if (!showLabels) setRenderMode('labels')
      else setRenderMode(prev => prev === 'labels' ? 'points' : prev)
    } else if (id === 'density') {
      setRenderMode(m => m === 'density' ? 'points' : 'density')
    } else {
      setViewControl(id)
    }
  }

  function isActive(id) {
    if (id === 'labels')  return showLabels || renderMode === 'labels'
    if (id === 'density') return renderMode === 'density'
    return viewControl === id
  }

  return (
    <div className="flex flex-col w-full h-full overflow-hidden" style={{ background: '#02050a' }}>

      {/* ══ THREE-COLUMN MAIN AREA ══════════════════════════════════════════════ */}
      <div className="flex flex-1 overflow-hidden min-h-0">

        {/* ── LEFT CONTROL PANEL ─────────────────────────────────────────────── */}
        <div
          className="flex flex-col flex-shrink-0 overflow-y-auto overflow-x-hidden gap-3.5 px-3 py-3"
          style={{
            width: 192,
            background: 'linear-gradient(180deg, #070e1c 0%, #030810 100%)',
            borderRight: '1px solid rgba(26,45,74,0.65)',
            scrollbarWidth: 'thin',
            scrollbarColor: '#1a2d4a transparent',
          }}
        >
          {/* Live indicator */}
          <div className="flex-shrink-0 pb-1" style={{ borderBottom: '1px solid rgba(26,45,74,0.5)' }}>
            <div className="text-[8.5px] uppercase tracking-[0.25em] font-bold" style={{ color: '#00d4ff', textShadow: '0 0 10px rgba(0,212,255,0.35)' }}>
              3D Semantic Space
            </div>
            <div className="flex items-center gap-1.5 mt-1.5">
              <span className="w-1.5 h-1.5 rounded-full flex-shrink-0 animate-pulse" style={{ background: '#10b981', boxShadow: '0 0 5px #10b981' }} />
              <span className="text-[9px]" style={{ color: '#1e3450' }}>LIVE · {displayClusters.length.toLocaleString()} nodes</span>
            </div>
          </div>

          {/* View Controls */}
          <CtrlSection label="View Controls">
            <div className="grid grid-cols-4 gap-1">
              {VIEW_CONTROLS.map(({ id, Icon, label }) => (
                <button
                  key={id}
                  title={label}
                  onClick={() => handleViewControl(id)}
                  className="flex items-center justify-center rounded-md transition-all duration-150"
                  style={{
                    height: 30,
                    background: isActive(id) ? 'rgba(0,212,255,0.14)' : 'rgba(255,255,255,0.025)',
                    border: `1px solid ${isActive(id) ? 'rgba(0,212,255,0.40)' : 'rgba(26,45,74,0.65)'}`,
                    color: isActive(id) ? '#00d4ff' : '#334155',
                    boxShadow: isActive(id) ? '0 0 10px rgba(0,212,255,0.2)' : 'none',
                  }}
                >
                  <Icon size={11} />
                </button>
              ))}
            </div>
          </CtrlSection>

          {/* Render Mode */}
          <CtrlSection label="Render Mode">
            <div className="flex rounded-lg overflow-hidden" style={{ border: '1px solid rgba(26,45,74,0.65)' }}>
              {[['points', 'Points'], ['density', 'Density'], ['labels', 'Labels']].map(([mode, lbl]) => (
                <button
                  key={mode}
                  onClick={() => setRenderMode(mode)}
                  className="flex-1 py-1.5 text-[9px] font-semibold transition-all duration-150"
                  style={renderMode === mode
                    ? { background: 'rgba(0,212,255,0.16)', color: '#00d4ff' }
                    : { background: 'rgba(3,8,15,0.85)', color: '#334155' }
                  }
                >
                  {lbl}
                </button>
              ))}
            </div>
          </CtrlSection>

          {/* Color By */}
          <CtrlSection label="Color By">
            <div
              className="flex items-center justify-between px-2.5 py-1.5 rounded-lg text-[10px]"
              style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(26,45,74,0.65)', color: '#64748b' }}
            >
              <span style={{ color: '#94a3b8' }}>Field</span>
              <span style={{ fontSize: 8, color: '#334155' }}>▾</span>
            </div>
          </CtrlSection>

          {/* Projection */}
          <CtrlSection label="Projection">
            <div className="flex rounded-lg overflow-hidden" style={{ border: '1px solid rgba(26,45,74,0.65)' }}>
              {['UMAP', 't-SNE', 'PCA'].map(p => (
                <button
                  key={p}
                  onClick={() => setProjectionMode(p.toLowerCase())}
                  className="flex-1 py-1.5 text-[8.5px] font-mono transition-all duration-150"
                  style={projectionMode === p.toLowerCase()
                    ? { background: 'rgba(168,85,247,0.16)', color: '#a855f7' }
                    : { background: 'rgba(3,8,15,0.85)', color: '#334155' }
                  }
                >
                  {p}
                </button>
              ))}
            </div>
          </CtrlSection>

          {/* Filters */}
          <CtrlSection label="Filters">
            <div className="flex flex-col gap-1.5">
              <Toggle label="Show Labels" value={showClusterLabels} onChange={v => { setShowLabels(v); if (!v && renderMode === 'labels') setRenderMode('points') }} />

              {/* Anomaly filter */}
              <div className="flex rounded-lg overflow-hidden" style={{ border: '1px solid rgba(26,45,74,0.65)' }}>
                {[['all', 'All'], ['standard', 'Std'], ['anomaly', 'Anom']].map(([v, l]) => (
                  <button
                    key={v}
                    onClick={() => setAnomalyFilter(v)}
                    className="flex-1 py-1 text-[9px] transition-all duration-150"
                    style={anomalyFilter === v
                      ? v === 'anomaly'
                        ? { background: 'rgba(239,68,68,0.18)', color: '#ef4444' }
                        : { background: 'rgba(0,212,255,0.12)', color: '#00d4ff' }
                      : { background: 'rgba(3,8,15,0.85)', color: '#334155' }
                    }
                  >
                    {l}
                  </button>
                ))}
              </div>

              {/* Size filter */}
              <div>
                <div className="flex justify-between items-center mb-1">
                  <span className="text-[9px]" style={{ color: '#475569' }}>Min Size</span>
                  <span className="text-[9px] font-mono" style={{ color: '#00d4ff' }}>{sizeFilter}</span>
                </div>
                <input
                  type="range" min={1} max={50} step={1} value={sizeFilter}
                  onChange={e => setSizeFilter(Number(e.target.value))}
                  className="w-full h-1 rounded-full cursor-pointer appearance-none"
                  style={{ accentColor: '#00d4ff', background: 'rgba(26,45,74,0.7)' }}
                />
              </div>
            </div>
          </CtrlSection>

          {/* Field selector */}
          <CtrlSection label="Field">
            <div className="flex flex-col gap-0.5">
              <button
                onClick={() => setActiveField(null)}
                className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-left transition-all duration-150"
                style={!activeField
                  ? { background: 'rgba(0,212,255,0.12)', border: '1px solid rgba(0,212,255,0.32)' }
                  : { background: 'transparent', border: '1px solid transparent' }
                }
              >
                <span className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                  style={{ background: !activeField ? '#00d4ff' : '#1e3450', boxShadow: !activeField ? '0 0 5px #00d4ff' : 'none' }} />
                <span className="flex-1 text-[10px]" style={{ color: !activeField ? '#00d4ff' : '#475569' }}>All Fields</span>
                <span className="text-[9px]" style={{ color: !activeField ? '#00d4ff88' : '#334155' }}>{clusters.length}</span>
              </button>
              {fields.map(([field, count]) => (
                <FieldChip
                  key={field} field={field} count={count}
                  active={activeField === field}
                  onClick={() => setActiveField(activeField === field ? null : field)}
                />
              ))}
            </div>
          </CtrlSection>

          {/* Camera reset */}
          <button
            onClick={triggerCameraReset}
            className="flex items-center justify-center gap-1.5 rounded-lg py-2 text-[9.5px] transition-all duration-150 mt-auto flex-shrink-0"
            style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(26,45,74,0.6)', color: '#475569' }}
            onMouseEnter={e => { e.currentTarget.style.color = '#00d4ff'; e.currentTarget.style.borderColor = 'rgba(0,212,255,0.3)' }}
            onMouseLeave={e => { e.currentTarget.style.color = '#475569'; e.currentTarget.style.borderColor = 'rgba(26,45,74,0.6)' }}
          >
            <RotateCcw size={11} /> Reset Camera
          </button>
        </div>

        {/* ── CENTER: 3D SEMANTIC SPACE ───────────────────────────────────────── */}
        <div className="relative flex-1 min-w-0 overflow-hidden">
          <Suspense fallback={<SceneLoader label="Initializing Semantic Space…" />}>
            {!loading
              ? (
                <SemanticScene
                  clusters={displayClusters}
                  showLabels={showClusterLabels}
                  renderMode={renderMode}
                />
              )
              : <SceneLoader label="Loading semantic space…" />
            }
          </Suspense>

          {/* Top overlay strip */}
          <div
            className="absolute top-0 left-0 right-0 z-10 flex items-center justify-between px-4 py-2.5"
            style={{ background: 'linear-gradient(180deg, rgba(2,5,10,0.8) 0%, transparent 100%)', pointerEvents: 'none' }}
          >
            <div className="flex items-center gap-3" style={{ pointerEvents: 'auto' }}>
              <span className="text-[8.5px] uppercase tracking-[0.2em] font-bold" style={{ color: '#00d4ff55' }}>
                Semantic Space
              </span>
              <span className="text-[8.5px]" style={{ color: '#1e3450' }}>
                {displayClusters.length.toLocaleString()} clusters · {fields.length} fields
              </span>
            </div>
            <div className="flex items-center gap-1.5" style={{ pointerEvents: 'auto' }}>
              <div className="px-2 py-1 rounded text-[8.5px] font-mono" style={{ background: 'rgba(3,8,15,0.85)', border: '1px solid rgba(26,45,74,0.6)', color: '#a855f7' }}>
                {projectionMode.toUpperCase()}
              </div>
              <button
                onClick={triggerCameraReset}
                className="flex items-center justify-center rounded p-1.5 transition-colors"
                style={{ background: 'rgba(3,8,15,0.85)', border: '1px solid rgba(26,45,74,0.6)', color: '#334155' }}
                onMouseEnter={e => e.currentTarget.style.color = '#00d4ff'}
                onMouseLeave={e => e.currentTarget.style.color = '#334155'}
              >
                <RotateCcw size={10} />
              </button>
            </div>
          </div>
        </div>

        {/* ── RIGHT INSPECTOR PANEL ─────────────────────────────────────────── */}
        <div
          className="flex-shrink-0 overflow-hidden"
          style={{
            width: 300,
            background: 'linear-gradient(180deg, #060d1a 0%, #03080f 100%)',
            borderLeft: '1px solid rgba(26,45,74,0.75)',
          }}
        >
          <AnimatePresence mode="wait">
            {selectedClusterId ? (
              <motion.div
                key="inspector"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="h-full overflow-hidden"
              >
                <RightInspector clusterId={selectedClusterId} />
              </motion.div>
            ) : (
              <motion.div
                key="default"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="h-full"
              >
                <DefaultInspector health={health} clusters={clusters} fields={fields} />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* ══ BOTTOM INTELLIGENCE METRICS ROW ════════════════════════════════════ */}
      <div
        className="flex-shrink-0 flex items-center gap-2 px-3 py-2 overflow-x-auto"
        style={{
          background: 'linear-gradient(0deg, rgba(2,5,10,0.99) 0%, rgba(4,10,20,0.95) 100%)',
          borderTop: '1px solid rgba(26,45,74,0.6)',
          minHeight: 88,
          maxHeight: 96,
          scrollbarWidth: 'none',
        }}
      >
        {/* Compression */}
        <BottomCard label="Compression" color="#a855f7">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="text-[19px] font-bold leading-none" style={{ color: '#a855f7', textShadow: '0 0 12px rgba(168,85,247,0.4)' }}>
                {compression?.compression_ratio != null ? `${compression.compression_ratio}×` : '—'}
              </div>
              <div className="text-[8.5px] mt-1" style={{ color: '#475569' }}>
                {(compression?.raw_label_count || 0).toLocaleString()} labels
              </div>
            </div>
            <Sparkline seed={compression?.compression_ratio || 2.4} color="#a855f7" />
          </div>
        </BottomCard>

        {/* Semantic Quality */}
        <BottomCard label="Semantic Quality" color="#10b981">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="text-[19px] font-bold leading-none" style={{ color: '#10b981', textShadow: '0 0 12px rgba(16,185,129,0.4)' }}>
                {totalClusters ? `${(coveragePct * 100).toFixed(0)}%` : '—'}
              </div>
              <div className="text-[8.5px] mt-1" style={{ color: '#475569' }}>
                {namedCount.toLocaleString()} named
              </div>
            </div>
            <Sparkline seed={coveragePct * 8 + 1.2} color="#10b981" />
          </div>
        </BottomCard>

        {/* Anomalies */}
        <BottomCard label="Anomalies" color="#ef4444">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="text-[19px] font-bold leading-none" style={{ color: '#ef4444', textShadow: '0 0 12px rgba(239,68,68,0.4)' }}>
                {anomalyCount.toLocaleString()}
              </div>
              {anomalySummary?.by_type && (
                <div className="text-[8.5px] mt-1" style={{ color: '#475569' }}>
                  {Object.keys(anomalySummary.by_type).length} types
                </div>
              )}
              {!anomalySummary?.by_type && (
                <div className="text-[8.5px] mt-1" style={{ color: '#475569' }}>clusters</div>
              )}
            </div>
            <AnomalyDonut
              pct={totalClusters ? Math.min(anomalyCount / totalClusters, 1) : 0}
              color="#ef4444"
            />
          </div>
        </BottomCard>

        {/* Drift */}
        <BottomCard label="Drift" color="#f97316">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="text-[19px] font-bold leading-none" style={{ color: '#f97316', textShadow: '0 0 12px rgba(249,115,22,0.4)' }}>
                {drift?.total_drift_events ?? drift?.run_count ?? '—'}
              </div>
              <div className="text-[8.5px] mt-1" style={{ color: '#475569' }}>
                {drift ? 'events' : 'no data'}
              </div>
            </div>
            <Sparkline seed={3.2} color="#f97316" />
          </div>
        </BottomCard>

        {/* Merge Intelligence */}
        <BottomCard label="Merge Intelligence" color="#06b6d4">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="text-[19px] font-bold leading-none" style={{ color: '#06b6d4', textShadow: '0 0 12px rgba(6,182,212,0.4)' }}>
                {medoid?.merge_candidates ?? medoid?.total_clusters_with_medoids ?? '—'}
              </div>
              <div className="text-[8.5px] mt-1" style={{ color: '#475569' }}>
                {medoid ? 'candidates' : 'no data'}
              </div>
            </div>
            <Sparkline seed={1.7} color="#06b6d4" />
          </div>
        </BottomCard>

        {/* Coverage */}
        <BottomCard label="Coverage" color="#00d4ff">
          <div className="flex flex-col gap-1.5">
            <div className="text-[19px] font-bold leading-none" style={{ color: '#00d4ff', textShadow: '0 0 12px rgba(0,212,255,0.4)' }}>
              {totalClusters ? `${(coveragePct * 100).toFixed(0)}%` : '—'}
            </div>
            <div className="w-full h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(26,45,74,0.7)' }}>
              <div
                style={{
                  width: `${coveragePct * 100}%`,
                  height: '100%',
                  background: 'linear-gradient(90deg, #00d4ff, #a855f7)',
                  borderRadius: 999,
                  boxShadow: '0 0 8px rgba(0,212,255,0.45)',
                  transition: 'width 1.2s ease',
                }}
              />
            </div>
            <div className="text-[8.5px]" style={{ color: '#475569' }}>
              {(health?.total_label_rows || 0).toLocaleString()} labels
            </div>
          </div>
        </BottomCard>
      </div>
    </div>
  )
}
