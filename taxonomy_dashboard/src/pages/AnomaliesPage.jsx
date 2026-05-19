import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, GitBranch, Minus, Radar, Search, ShieldQuestion, TrendingDown, Zap } from 'lucide-react'
import { useAppCtx } from '../context/AppContext.jsx'
import Filters from '../components/Filters.jsx'
import { fmt } from '../utils/format.js'
import { getAnomalyTypeColor } from '../utils/colors.js'
import { useDebounce } from '../hooks/useDebounce.js'

const DEFAULT_FILTERS = { field_name: '', search: '', limit: 100, offset: 0 }
const SEVERITY_RANK = { noise: 0, threshold_failure: 1, semantic_outlier: 2, emerging: 3 }
const TYPE_META = {
  semantic_outlier: { label: 'True isolated concepts', Icon: AlertTriangle, desc: 'Semantic islands that did not join stable taxonomy neighborhoods.' },
  threshold_failure: { label: 'Recoverable anomalies', Icon: TrendingDown, desc: 'Borderline groups prepared for future nearest-cluster recovery scoring.' },
  noise: { label: 'Naming noise / low-frequency variants', Icon: Minus, desc: 'Rare phrases, small variants, or ambiguous fragments.' },
  emerging: { label: 'Emerging operational themes', Icon: Zap, desc: 'Large repeated anomalies that may indicate new taxonomy language.' },
}

function LabCard({ title, value, detail, Icon, color }) {
  return (
    <div className="rounded-lg px-3 py-2" style={{ background: 'rgba(255,255,255,0.025)', border: `1px solid ${color}22` }}>
      <div className="flex items-center gap-2 text-[9px] uppercase tracking-[0.16em]" style={{ color: `${color}aa` }}>
        <Icon size={11} /> {title}
      </div>
      <div className="text-[18px] font-bold mt-1" style={{ color }}>{value}</div>
      <div className="text-[10px] leading-snug text-dust mt-1">{detail}</div>
    </div>
  )
}

function CategoryLab({ summary, typeFilter, setTypeFilter }) {
  return (
    <div className="grid gap-2 mb-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
      {Object.entries(TYPE_META).map(([type, meta]) => {
        const color = getAnomalyTypeColor(type)
        const count = summary.by_type?.[type] || 0
        const Icon = meta.Icon
        return (
          <button key={type} onClick={() => setTypeFilter(typeFilter === type ? '' : type)} className="rounded-lg px-3 py-2 text-left"
            style={{ background: typeFilter === type ? `${color}18` : 'rgba(255,255,255,0.025)', border: `1px solid ${color}30` }}>
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.14em]" style={{ color }}><Icon size={11} /> {meta.label}</div>
            <div className="text-[18px] font-bold mt-1" style={{ color }}>{fmt(count)}</div>
            <div className="text-[10px] text-dust leading-snug">{meta.desc}</div>
          </button>
        )
      })}
    </div>
  )
}

function FieldPressure({ fields = [] }) {
  const max = Math.max(...fields.map(f => Number(f.anomaly_clusters) || 0), 1)
  if (!fields.length) return <div className="state-empty">Anomaly field pressure is not available.</div>
  return (
    <div className="rounded-xl p-3" style={{ background: 'rgba(6,13,26,0.78)', border: '1px solid rgba(26,45,74,0.65)' }}>
      <div className="text-[10px] uppercase tracking-[0.18em] text-dust/70 mb-2">Anomaly Hotspots</div>
      {fields.slice(0, 10).map(f => {
        const color = '#ef4444'
        const pct = (Number(f.anomaly_clusters) || 0) / max
        return (
          <div key={f.field_name} className="field-drift-row">
            <span className="fdr-dot" style={{ background: color }} />
            <span className="fdr-name">{f.field_name}</span>
            <div className="fdr-bar-wrap"><div className="fdr-bar" style={{ width: `${Math.max(4, pct * 100)}%`, background: `${color}66` }} /></div>
            <span className="fdr-count">{fmt(f.anomaly_clusters)}</span>
            <span className="fdr-anom">{fmt(f.anomaly_occurrences)} occ.</span>
          </div>
        )
      })}
    </div>
  )
}

function ThemePanel({ clusters }) {
  const themes = useMemo(() => {
    const stop = new Set(['with', 'from', 'that', 'this', 'have', 'will', 'been', 'into', 'other', 'unknown'])
    const counts = {}
    clusters.forEach(c => {
      const text = `${c.display_name || ''} ${c.medoid_label || ''} ${c.representative_labels || ''}`.toLowerCase()
      text.split(/[^a-z0-9]+/).filter(t => t.length > 3 && !stop.has(t)).forEach(t => { counts[t] = (counts[t] || 0) + 1 })
    })
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 16)
  }, [clusters])
  return (
    <div className="rounded-xl p-3" style={{ background: 'rgba(6,13,26,0.78)', border: '1px solid rgba(26,45,74,0.65)' }}>
      <div className="text-[10px] uppercase tracking-[0.18em] text-dust/70 mb-2">Emerging Taxonomy Themes</div>
      <p className="text-[11px] text-dust mb-2">Repeated anomaly terms derived from real display names, medoids, and representative labels. These are discovery prompts, not confirmed merges.</p>
      <div className="ic-examples">
        {themes.map(([theme, count]) => <span key={theme} className="ic-example-chip">{theme} · {count}</span>)}
        {!themes.length && <span className="text-dust text-[11px]">No repeated themes in current sample.</span>}
      </div>
    </div>
  )
}

function AnomalyCard({ cluster, onClick }) {
  const color = getAnomalyTypeColor(cluster.anomaly_type)
  const meta = TYPE_META[cluster.anomaly_type] || TYPE_META.semantic_outlier
  const Icon = meta.Icon
  const reason = cluster.anomaly_type === 'emerging'
    ? 'large anomalous group with repeated language; may become a new taxonomy concept.'
    : cluster.anomaly_type === 'semantic_outlier'
      ? 'embedding neighborhood did not merge into a standard cluster.'
      : cluster.anomaly_type === 'threshold_failure'
        ? 'borderline small group; recovery candidate scoring is not computed yet.'
        : 'low-frequency variant with limited support.'
  return (
    <button className="anomaly-card" style={{ '--type-color': color, textAlign: 'left' }} onClick={() => onClick(cluster.id)}>
      <div className="ac-type-strip" style={{ background: color }} />
      <div className="ac-content">
        <div className="ac-top">
          <span className="ac-type-badge" style={{ color, borderColor: `${color}44`, background: `${color}14` }}><Icon size={10} />{meta.label}</span>
          <div className="ac-stats-row">
            <span className="ac-stat"><span className="ac-stat-n">{fmt(cluster.cluster_size)}</span><span className="ac-stat-l">size</span></span>
            <span className="ac-stat"><span className="ac-stat-n">{fmt(cluster.total_occurrences)}</span><span className="ac-stat-l">occ.</span></span>
          </div>
        </div>
        <div className="ac-identity">
          <span className="ac-name">{cluster.display_name || cluster.medoid_label || cluster.cluster_id}</span>
          <span className="ac-field">{cluster.field_name}</span>
        </div>
        <div className="text-[10px] text-dust mt-2 leading-snug">Why: {reason}</div>
        <div className="text-[10px] mt-1" style={{ color: '#94a3b8' }}>Suggested action: review manually; nearest-cluster candidates not computed.</div>
      </div>
    </button>
  )
}

export default function AnomaliesPage() {
  const { fields, setSelectedClusterId } = useAppCtx()
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [typeFilter, setTypeFilter] = useState('')
  const [sortBy, setSortBy] = useState('severity')
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
  const summary = data?.summary
  const filtered = clusters.filter(c => {
    if (typeFilter && c.anomaly_type !== typeFilter) return false
    if (filters.field_name && c.field_name !== filters.field_name) return false
    if (debouncedSearch) {
      const q = debouncedSearch.toLowerCase()
      if (!`${c.display_name || ''} ${c.cluster_id || ''} ${c.medoid_label || ''}`.toLowerCase().includes(q)) return false
    }
    return true
  })
  const sorted = [...filtered].sort((a, b) => {
    if (sortBy === 'severity') return (SEVERITY_RANK[b.anomaly_type] ?? 0) - (SEVERITY_RANK[a.anomaly_type] ?? 0)
    if (sortBy === 'size') return (b.cluster_size || 0) - (a.cluster_size || 0)
    if (sortBy === 'field') return (a.field_name || '').localeCompare(b.field_name || '')
    return 0
  })

  return (
    <div className="page-wrap">
      <div className="page-header">
        <div>
          <h1 className="page-title">Anomaly Investigation Lab</h1>
          <p className="page-subtitle">Separate true isolation, recoverable candidates, noise, and emerging taxonomy themes.</p>
        </div>
      </div>

      {error && <div className="state-error">⚠ {error}</div>}
      {loading && <div className="state-loading">Scanning anomaly neighborhoods...</div>}

      {summary && (
        <>
          <div className="grid gap-2 mb-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))' }}>
            <LabCard title="Overview" value={fmt(summary.total)} detail={`${fmt(summary.anomaly_labels)} labels, ${fmt(summary.anomaly_occurrences)} occurrences`} Icon={AlertTriangle} color="#ef4444" />
            <LabCard title="Rate" value={summary.anomaly_rate != null ? `${(summary.anomaly_rate * 100).toFixed(1)}%` : 'not computed'} detail="Share of clusters currently marked anomalous." Icon={Radar} color="#f97316" />
            <LabCard title="Recoverability" value="not computed" detail="Nearest-cluster candidate data is not available yet." Icon={GitBranch} color="#06b6d4" />
            <LabCard title="True Isolation" value="not computed" detail="Isolation requires nearest-neighbor similarity scores." Icon={ShieldQuestion} color="#a855f7" />
          </div>
          <CategoryLab summary={summary} typeFilter={typeFilter} setTypeFilter={setTypeFilter} />
          <div className="charts-grid">
            <FieldPressure fields={summary.by_field || []} />
            <ThemePanel clusters={clusters} />
          </div>
        </>
      )}

      <Filters filters={filters} fields={fields} onChange={p => setFilters(prev => ({ ...prev, ...p }))} onRefresh={fetchAnomalies} anomalyMode compact />

      {!loading && !error && (
        <>
          {sorted.length > 0 && (
            <div className="anomaly-sort-bar">
              <span className="asort-label">{sorted.length} shown · Sort:</span>
              {['severity', 'size', 'field'].map(s => (
                <button key={s} className={['asort-btn', sortBy === s && 'asort-btn--active'].filter(Boolean).join(' ')} onClick={() => setSortBy(s)}>{s}</button>
              ))}
            </div>
          )}
          <div className="anomaly-cards-grid">
            {sorted.length === 0 && <div className="state-empty">No anomalies match the current filters.</div>}
            {sorted.map(c => <AnomalyCard key={c.id} cluster={c} onClick={id => setSelectedClusterId(id)} />)}
          </div>
        </>
      )}
    </div>
  )
}
