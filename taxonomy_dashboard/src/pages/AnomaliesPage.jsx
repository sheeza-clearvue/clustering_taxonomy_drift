import { useEffect, useState } from 'react'
import { useAppCtx } from '../context/AppContext.jsx'
import Filters from '../components/Filters.jsx'
import AnomalyRingChart from '../components/charts/AnomalyRingChart.jsx'
import { fmt } from '../utils/format.js'
import { getAnomalyTypeColor, getAnomalyTypeLabel } from '../utils/colors.js'
import { useDebounce } from '../hooks/useDebounce.js'
import { AlertTriangle, Zap, Minus, TrendingDown, Activity } from 'lucide-react'

const DEFAULT_FILTERS = { field_name: '', search: '', limit: 100, offset: 0 }

const SEVERITY_RANK = { noise: 0, threshold_failure: 1, semantic_outlier: 2, emerging: 3 }

const TYPE_META = {
  noise:             { label: 'Noise',               Icon: Minus,         desc: 'Singleton or tiny — likely irrelevant' },
  threshold_failure: { label: 'Threshold Failure',   Icon: TrendingDown,  desc: 'Just below merge threshold — borderline' },
  semantic_outlier:  { label: 'Semantic Outlier',    Icon: AlertTriangle, desc: 'Mid-size but clearly not grouped — investigate' },
  emerging:          { label: 'Emerging Pattern',    Icon: Zap,           desc: 'Large anomaly — may be a real taxonomy gap' },
}

function TypePill({ type, count, active, onClick }) {
  const color = getAnomalyTypeColor(type)
  const meta  = TYPE_META[type] || {}
  return (
    <button
      className={['atype-pill', active && 'atype-pill--active'].filter(Boolean).join(' ')}
      style={active
        ? { borderColor: color, background: color + '20', color }
        : { borderColor: color + '44', background: color + '0a' }
      }
      onClick={onClick}
      title={meta.desc}
    >
      {meta.Icon && <meta.Icon size={11} style={{ flexShrink: 0 }} />}
      <span className="atype-label" style={{ color: active ? color : undefined }}>{meta.label}</span>
      <span className="atype-count" style={{ color: active ? color : undefined }}>{count}</span>
    </button>
  )
}

function SeverityBar({ clusters }) {
  const total = clusters.length
  if (!total) return null
  const byType = clusters.reduce((a, c) => { a[c.anomaly_type] = (a[c.anomaly_type] || 0) + 1; return a }, {})
  const order = ['noise', 'threshold_failure', 'semantic_outlier', 'emerging']
  return (
    <div className="anomaly-severity-bar">
      {order.filter(t => byType[t]).map(t => (
        <div
          key={t}
          className="asb-segment"
          title={`${getAnomalyTypeLabel(t)}: ${byType[t]}`}
          style={{
            width: `${(byType[t] / total) * 100}%`,
            background: getAnomalyTypeColor(t),
          }}
        />
      ))}
    </div>
  )
}

function AnomalyCard({ cluster, onClick }) {
  const typeColor = getAnomalyTypeColor(cluster.anomaly_type)
  const meta      = TYPE_META[cluster.anomaly_type] || {}
  const Icon      = meta.Icon || Activity
  const isHigh    = cluster.anomaly_type === 'emerging' || cluster.anomaly_type === 'semantic_outlier'

  return (
    <div
      className={['anomaly-card', isHigh && 'anomaly-card--high'].filter(Boolean).join(' ')}
      style={{ '--type-color': typeColor }}
      onClick={() => onClick(cluster.id)}
    >
      <div className="ac-type-strip" style={{ background: typeColor }} />

      <div className="ac-content">
        <div className="ac-top">
          <div className="ac-badge-row">
            <span className="ac-type-badge" style={{ color: typeColor, borderColor: typeColor + '44', background: typeColor + '14' }}>
              <Icon size={10} />
              {meta.label}
            </span>
            {cluster.is_true_anomaly_cluster && (
              <span className="ac-confirmed-badge">confirmed</span>
            )}
          </div>
          <div className="ac-stats-row">
            <span className="ac-stat"><span className="ac-stat-n">{fmt(cluster.cluster_size)}</span><span className="ac-stat-l">size</span></span>
            <span className="ac-stat"><span className="ac-stat-n">{fmt(cluster.label_count)}</span><span className="ac-stat-l">labels</span></span>
          </div>
        </div>

        <div className="ac-identity">
          <span className="ac-name">
            {cluster.display_name || <span className="unnamed">unnamed</span>}
          </span>
          <span className="ac-field">{cluster.field_name}</span>
        </div>

        {cluster.medoid_label && (
          <div className="ac-medoid" title={cluster.medoid_label}>
            {cluster.medoid_label.length > 50 ? cluster.medoid_label.slice(0, 50) + '…' : cluster.medoid_label}
          </div>
        )}
      </div>
    </div>
  )
}

function SummaryPanel({ summary, typeFilter, setTypeFilter }) {
  const types = Object.entries(summary.by_type)
    .sort(([a], [b]) => (SEVERITY_RANK[b] ?? 0) - (SEVERITY_RANK[a] ?? 0))

  return (
    <div className="anomaly-summary-panel">
      <div className="asp-left">
        <div className="asp-total">
          <span className="asp-total-num">{summary.total}</span>
          <span className="asp-total-label">total anomalies</span>
        </div>
        <div className="atype-pills">
          <button
            className={['atype-pill atype-pill--all', !typeFilter && 'atype-pill--active'].filter(Boolean).join(' ')}
            onClick={() => setTypeFilter('')}
          >
            All <span className="atype-count">{summary.total}</span>
          </button>
          {types.map(([t, n]) => (
            <TypePill
              key={t} type={t} count={n}
              active={typeFilter === t}
              onClick={() => setTypeFilter(typeFilter === t ? '' : t)}
            />
          ))}
        </div>
      </div>
      <div className="asp-right">
        <AnomalyRingChart byType={summary.by_type} />
      </div>
    </div>
  )
}

export default function AnomaliesPage() {
  const { fields, setSelectedClusterId } = useAppCtx()
  const [filters,    setFilters]    = useState(DEFAULT_FILTERS)
  const [data,       setData]       = useState(null)
  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState(null)
  const [typeFilter, setTypeFilter] = useState('')
  const [sortBy,     setSortBy]     = useState('severity') // severity | size | field

  const debouncedSearch = useDebounce(filters.search, 280)

  async function fetchAnomalies() {
    setLoading(true); setError(null)
    try {
      const res = await fetch('/api/anomaly-intelligence')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchAnomalies() }, [])

  const clusters = data?.clusters || []
  const summary  = data?.summary

  const filtered = clusters.filter(c => {
    if (typeFilter && c.anomaly_type !== typeFilter) return false
    if (filters.field_name && c.field_name !== filters.field_name) return false
    if (debouncedSearch) {
      const q = debouncedSearch.toLowerCase()
      const hit = (c.display_name || '').toLowerCase().includes(q)
        || (c.cluster_id || '').toLowerCase().includes(q)
        || (c.medoid_label || '').toLowerCase().includes(q)
      if (!hit) return false
    }
    return true
  })

  const sorted = [...filtered].sort((a, b) => {
    if (sortBy === 'severity') return (SEVERITY_RANK[b.anomaly_type] ?? 0) - (SEVERITY_RANK[a.anomaly_type] ?? 0)
    if (sortBy === 'size')     return (b.cluster_size || 0) - (a.cluster_size || 0)
    if (sortBy === 'field')    return (a.field_name || '').localeCompare(b.field_name || '')
    return 0
  })

  return (
    <div className="page-wrap">
      <div className="page-header">
        <div>
          <h1 className="page-title">Anomaly Intelligence</h1>
          <p className="page-subtitle">Investigate, classify, and understand anomalous clusters</p>
        </div>
        {summary && (
          <div className="anomaly-header-right">
            <span className="anomaly-total-badge">
              <AlertTriangle size={13} />
              {summary.total} anomalies
            </span>
          </div>
        )}
      </div>

      {error  && <div className="state-error">⚠ {error}</div>}
      {loading && <div className="state-loading">Scanning anomaly space…</div>}

      {summary && (
        <>
          <SummaryPanel summary={summary} typeFilter={typeFilter} setTypeFilter={setTypeFilter} />
          {filtered.length > 0 && <SeverityBar clusters={filtered} />}
        </>
      )}

      <Filters
        filters={filters}
        fields={fields}
        onChange={p => setFilters(prev => ({ ...prev, ...p }))}
        onRefresh={fetchAnomalies}
        anomalyMode
        compact
      />

      {!loading && !error && (
        <>
          {/* Sort controls */}
          {sorted.length > 0 && (
            <div className="anomaly-sort-bar">
              <span className="asort-label">{sorted.length} shown · Sort:</span>
              {['severity', 'size', 'field'].map(s => (
                <button
                  key={s}
                  className={['asort-btn', sortBy === s && 'asort-btn--active'].filter(Boolean).join(' ')}
                  onClick={() => setSortBy(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          <div className="anomaly-cards-grid">
            {sorted.length === 0 && (
              <div className="state-empty">No anomalies match the current filters.</div>
            )}
            {sorted.map((c, i) => (
              <AnomalyCard
                key={c.id || i}
                cluster={c}
                onClick={id => setSelectedClusterId(id)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
