import { useEffect, useState, useRef, useCallback } from 'react'
import { useAppCtx } from '../context/AppContext.jsx'
import { getFieldColor } from '../utils/colors.js'
import { fmt } from '../utils/format.js'
import SemanticGraph3D from '../components/graph/SemanticGraph3D.jsx'
import SemanticGraph2D from '../components/graph/SemanticGraph2D.jsx'

const VIEW_MODES = ['3D', '2D']
const SHOW_FILTERS = ['all', 'standard', 'anomaly']

function GraphOverlay({ nodeCount, edgeCount, loading }) {
  return (
    <div className="graph-overlay">
      {loading
        ? <span className="graph-overlay-status">Loading graph…</span>
        : (
          <>
            <span className="graph-overlay-stat">{fmt(nodeCount)} nodes</span>
            <span className="graph-overlay-sep">·</span>
            <span className="graph-overlay-stat">{fmt(edgeCount)} edges</span>
          </>
        )
      }
    </div>
  )
}

function FieldLegend({ fields, activeFields, onToggle }) {
  if (!fields.length) return null
  return (
    <div className="graph-legend">
      <div className="gl-title">Fields</div>
      {fields.map(f => {
        const active = activeFields.size === 0 || activeFields.has(f)
        const color  = getFieldColor(f)
        return (
          <button
            key={f}
            className={['gl-item', !active && 'gl-item--dim'].filter(Boolean).join(' ')}
            onClick={() => onToggle(f)}
          >
            <span className="gl-dot" style={{ background: color }} />
            <span className="gl-label">{f}</span>
          </button>
        )
      })}
    </div>
  )
}

function SelectedNodePanel({ node, onClose, onOpenDetail }) {
  if (!node) return null
  const color = getFieldColor(node.field_name)
  return (
    <div className="graph-selected-panel">
      <div className="gsp-header">
        <span className="gsp-field" style={{ color }}>{node.field_name}</span>
        <button className="gsp-close" onClick={onClose}>✕</button>
      </div>
      <div className="gsp-name">{node.label || node.display_name || <span className="unnamed">unnamed</span>}</div>
      <div className="gsp-stats">
        <span><span className="gsp-stat-label">Size</span> {fmt(node.cluster_size)}</span>
        {node.is_anomaly && <span className="gsp-anom">⚠ Anomaly</span>}
      </div>
      {node.cluster_id && (
        <div style={{ fontSize: 10, color: 'var(--text-3)', fontFamily: 'monospace', marginTop: 4, wordBreak: 'break-all' }}>
          {node.cluster_id}
        </div>
      )}
      {node.id && (
        <button className="gsp-detail-btn" onClick={() => onOpenDetail(node.id)}>
          Open Detail →
        </button>
      )}
    </div>
  )
}

export default function SemanticSpacePage() {
  const { setSelectedClusterId } = useAppCtx()
  const containerRef = useRef(null)
  const [dims,         setDims]         = useState({ w: 800, h: 600 })
  const [graphData,    setGraphData]    = useState(null)
  const [loading,      setLoading]      = useState(false)
  const [error,        setError]        = useState(null)
  const [viewMode,     setViewMode]     = useState('3D')
  const [selectedNode, setSelectedNode] = useState(null)
  const [activeFields, setActiveFields] = useState(new Set())
  const [highlightIds, setHighlightIds] = useState(new Set())
  const [showFilter,   setShowFilter]   = useState('all')   // 'all' | 'standard' | 'anomaly'
  const [minSize,      setMinSize]      = useState(1)

  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setDims({ w: Math.floor(width), h: Math.floor(height) })
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetch('/api/semantic-graph?limit=1200')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(d => setGraphData(d))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const allFields = graphData
    ? [...new Set((graphData.nodes || []).map(n => n.field_name).filter(Boolean))].sort()
    : []

  const filteredData = (() => {
    if (!graphData) return null
    const nodeIds = new Set()
    const nodes = (graphData.nodes || []).filter(n => {
      if (activeFields.size > 0 && !activeFields.has(n.field_name)) return false
      if (showFilter === 'anomaly'  && !n.is_anomaly) return false
      if (showFilter === 'standard' &&  n.is_anomaly) return false
      if (minSize > 1 && (n.cluster_size || 1) < minSize) return false
      nodeIds.add(n.id)
      return true
    })
    const links = (graphData.links || []).filter(l => {
      const s = l.source?.id ?? l.source
      const t = l.target?.id ?? l.target
      return nodeIds.has(s) && nodeIds.has(t)
    })
    return { nodes, links }
  })()

  function toggleField(f) {
    setActiveFields(prev => {
      const next = new Set(prev)
      if (next.has(f)) next.delete(f)
      else next.add(f)
      return next
    })
  }

  const handleNodeClick = useCallback((node) => {
    setSelectedNode(node)
    setHighlightIds(new Set([node.id]))
  }, [])

  function handleOpenDetail(id) {
    setSelectedClusterId(id)
  }

  const nodeCount = filteredData?.nodes?.length ?? 0
  const edgeCount = filteredData?.links?.length ?? 0
  const hasActiveFilters = activeFields.size > 0 || showFilter !== 'all' || minSize > 1

  return (
    <div className="semantic-space-page">
      {/* Top controls bar */}
      <div className="graph-controls-bar">
        <div className="gcb-left">
          <h1 className="gcb-title">Semantic Space</h1>
          <p className="gcb-sub">Force-directed cluster topology — all fields</p>
        </div>
        <div className="gcb-right">
          <div className="view-mode-toggle">
            {VIEW_MODES.map(m => (
              <button
                key={m}
                className={['vmt-btn', viewMode === m && 'vmt-btn--active'].filter(Boolean).join(' ')}
                onClick={() => setViewMode(m)}
              >
                {m}
              </button>
            ))}
          </div>
          {hasActiveFilters && (
            <button
              className="gcb-clear-btn"
              onClick={() => { setActiveFields(new Set()); setShowFilter('all'); setMinSize(1) }}
            >
              Clear filters
            </button>
          )}
        </div>
      </div>

      {/* Filter bar */}
      <div className="graph-filter-bar">
        <span className="gfb-label">Show:</span>
        {SHOW_FILTERS.map(f => (
          <button
            key={f}
            className={[
              'gfb-pill',
              f === 'anomaly' && 'gfb-pill--anom',
              showFilter === f && 'gfb-pill--active',
            ].filter(Boolean).join(' ')}
            onClick={() => setShowFilter(f)}
          >
            {f === 'all' ? 'All clusters' : f === 'standard' ? 'Standard only' : 'Anomalies only'}
          </button>
        ))}
        <span className="gfb-sep" />
        <span className="gfb-label">Min size:</span>
        {[1, 3, 10, 25].map(n => (
          <button
            key={n}
            className={['gfb-pill', minSize === n && 'gfb-pill--active'].filter(Boolean).join(' ')}
            onClick={() => setMinSize(n)}
          >
            ≥{n}
          </button>
        ))}
      </div>

      {error && <div className="state-error" style={{ margin: '0 20px' }}>⚠ {error}</div>}

      {/* Graph canvas */}
      <div className="graph-canvas-area" ref={containerRef}>
        <GraphOverlay nodeCount={nodeCount} edgeCount={edgeCount} loading={loading} />

        {!loading && !error && filteredData && (
          viewMode === '3D'
            ? <SemanticGraph3D
                graphData={filteredData}
                onNodeClick={handleNodeClick}
                highlightIds={highlightIds}
                width={dims.w}
                height={dims.h}
              />
            : <SemanticGraph2D
                graphData={filteredData}
                onNodeClick={handleNodeClick}
                width={dims.w}
                height={dims.h}
              />
        )}

        {loading && (
          <div className="graph-loading">
            <div className="graph-loading-spinner" />
            <span>Building semantic graph…</span>
          </div>
        )}

        <FieldLegend fields={allFields} activeFields={activeFields} onToggle={toggleField} />
        <SelectedNodePanel
          node={selectedNode}
          onClose={() => { setSelectedNode(null); setHighlightIds(new Set()) }}
          onOpenDetail={handleOpenDetail}
        />
      </div>
    </div>
  )
}
