import { useEffect, useState } from 'react'
import {
  RefreshCw, AlertTriangle, CheckCircle, Info, Zap, ArrowRight,
  Layers, GitMerge, Cpu, Activity,
} from 'lucide-react'
import { useAppCtx } from '../context/AppContext.jsx'
import FieldDistributionChart from '../components/charts/FieldDistributionChart.jsx'
import ClusterSizeHistogram from '../components/charts/ClusterSizeHistogram.jsx'
import { fmt, pct } from '../utils/format.js'
import { getFieldColor } from '../utils/colors.js'

// ── Semantic Compression Hero ─────────────────────────────────────────────────
function SemanticHero({ health, compression, medoid }) {
  const namingRate = health
    ? Math.round((health.named_clusters / (health.total_clusters || 1)) * 100)
    : null
  const anomalyPct = health && health.anomaly_clusters !== null
    ? Math.round((health.anomaly_clusters / (health.total_clusters || 1)) * 100)
    : null
  const embCoverage = medoid?.coverage_rate != null
    ? Math.round(medoid.coverage_rate * 100)
    : null

  const isLoading = !health && !compression

  if (isLoading) {
    return (
      <div className="sc-hero">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="sc-stat skeleton" />
        ))}
      </div>
    )
  }

  return (
    <div className="sc-hero">
      <div className="sc-stat sc-stat--blue">
        <span className="sc-stat-val">{fmt(compression?.raw_label_count ?? health?.total_label_rows)}</span>
        <span className="sc-stat-label">Raw Labels</span>
        <span className="sc-stat-sub">distinct values in label map</span>
      </div>
      <div className="sc-stat sc-stat--teal">
        <span className="sc-stat-val">{fmt(health?.total_clusters ?? compression?.total_clusters)}</span>
        <span className="sc-stat-label">Clusters</span>
        <span className="sc-stat-sub">{health?.fields_count ? `${health.fields_count} fields` : 'taxonomy groups'}</span>
      </div>
      <div className="sc-stat sc-stat--purple">
        <span className="sc-stat-val">
          {compression?.compression_ratio != null
            ? `${compression.compression_ratio}×`
            : <span className="sc-stat-empty">—</span>}
        </span>
        <span className="sc-stat-label">Compression</span>
        <span className="sc-stat-sub">raw labels per cluster</span>
      </div>
      <div className="sc-stat sc-stat--red">
        <span className="sc-stat-val">
          {health?.anomaly_clusters !== null && health?.anomaly_clusters !== undefined
            ? fmt(health.anomaly_clusters)
            : <span className="sc-stat-empty">N/A</span>}
        </span>
        <span className="sc-stat-label">Anomaly Load</span>
        <span className="sc-stat-sub">{anomalyPct != null ? `${anomalyPct}% of clusters` : 'no anomaly data'}</span>
      </div>
      <div className="sc-stat sc-stat--green">
        <span className="sc-stat-val">
          {namingRate != null
            ? `${namingRate}%`
            : <span className="sc-stat-empty">—</span>}
        </span>
        <span className="sc-stat-label">Named</span>
        <span className="sc-stat-sub">
          {embCoverage != null ? `${embCoverage}% medoid coverage` : 'clusters with display names'}
        </span>
      </div>
    </div>
  )
}

// ── Insight Card ─────────────────────────────────────────────────────────────
const SEVERITY_META = {
  critical: { icon: AlertTriangle, color: '#f44747', bg: 'rgba(244,71,71,0.08)', border: 'rgba(244,71,71,0.25)' },
  warning:  { icon: AlertTriangle, color: '#dcdcaa', bg: 'rgba(220,220,170,0.07)', border: 'rgba(220,220,170,0.25)' },
  info:     { icon: Info,          color: '#569cd6', bg: 'rgba(86,156,214,0.07)',  border: 'rgba(86,156,214,0.2)'  },
}

function InsightCard({ insight, onAction }) {
  const meta = SEVERITY_META[insight.severity] || SEVERITY_META.info
  const Icon = meta.icon
  return (
    <div
      className="insight-card"
      style={{ background: meta.bg, borderColor: meta.border }}
      onClick={() => onAction && onAction(insight)}
    >
      <div className="ic-left">
        <span className="ic-icon" style={{ color: meta.color }}><Icon size={14} /></span>
      </div>
      <div className="ic-body">
        <div className="ic-header">
          <span className="ic-title">{insight.title}</span>
          <span className="ic-value" style={{ color: meta.color }}>{insight.value}</span>
        </div>
        {insight.affected_field && (
          <span className="ic-field" style={{ color: getFieldColor(insight.affected_field) }}>
            {insight.affected_field}
          </span>
        )}
        <p className="ic-reason">{insight.reason}</p>
        {insight.examples && (
          <div className="ic-examples">
            {insight.examples.slice(0, 2).map((e, i) => (
              <span key={i} className="ic-example-chip" title={e.name}>
                {(e.name || '').slice(0, 22)}{e.size ? ` (${fmt(e.size)})` : ''}
              </span>
            ))}
          </div>
        )}
      </div>
      <ArrowRight size={13} className="ic-arrow" />
    </div>
  )
}

// ── Top Cluster Row ───────────────────────────────────────────────────────────
function TopClusterRow({ cluster, maxSize, onClick }) {
  const p  = maxSize ? Math.max(4, Math.round((cluster.cluster_size / maxSize) * 100)) : 4
  const fc = getFieldColor(cluster.field_name)
  return (
    <div className="top-cluster-row" onClick={() => onClick(cluster.id)}>
      <div className="tcr-bar" style={{ width: `${p}%`, background: fc + '18' }} />
      <span className="tcr-field" style={{ color: fc }}>{cluster.field_name}</span>
      <span className="tcr-name">{cluster.display_name || <span className="unnamed">unnamed</span>}</span>
      <div className="tcr-right">
        <span className="tcr-size">{fmt(cluster.cluster_size)}</span>
        {cluster.is_true_anomaly_cluster && <span className="tcr-anom-badge">anom</span>}
      </div>
    </div>
  )
}

// ── Review Priority Row ───────────────────────────────────────────────────────
function ReviewRow({ item, onClick }) {
  const fc = getFieldColor(item.field_name)
  const sc = item.priority_score > 0.6 ? '#f44747' : item.priority_score > 0.3 ? '#dcdcaa' : '#858585'
  return (
    <div className="review-row" onClick={() => onClick(item.id)}>
      <div className="rr-bar" style={{ width: `${Math.round(item.priority_score * 100)}%`, background: sc + '22' }} />
      <span className="rr-field" style={{ color: fc }}>{item.field_name}</span>
      <span className="rr-name">{item.display_name || item.medoid_label || <span className="unnamed">unnamed</span>}</span>
      <div className="rr-right">
        <div className="rr-reasons">
          {item.reasons.map(r => (
            <span key={r} className="rr-reason-chip">{r.replace(/_/g, ' ')}</span>
          ))}
        </div>
        <span className="rr-score" style={{ color: sc }}>{Math.round(item.priority_score * 100)}%</span>
      </div>
    </div>
  )
}

// ── Compression by Field panel ────────────────────────────────────────────────
function CompressionPanel({ compression }) {
  if (!compression?.by_field?.length) return null
  const max = Math.max(...compression.by_field.map(f => f.label_count || 0), 1)
  return (
    <div className="intel-panel">
      <div className="intel-panel-head">
        <span className="intel-panel-title"><Layers size={12} /> Compression by Field</span>
        <span className="intel-panel-badge">{compression.by_field.length} fields</span>
      </div>
      <div className="intel-panel-body">
        {compression.by_field.map(f => {
          const fc = getFieldColor(f.field_name)
          const pctW = max > 0 ? Math.max(3, (f.label_count / max) * 100) : 3
          return (
            <div key={f.field_name} className="intel-field-row">
              <span className="intel-field-name" style={{ color: fc }}>{f.field_name}</span>
              <div className="intel-bar-track">
                <div className="intel-bar-fill" style={{ width: `${pctW}%`, background: fc + '88' }} />
              </div>
              <span className="intel-field-val">
                {f.compression_ratio != null ? `${f.compression_ratio}×` : fmt(f.cluster_count)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Recovery Intelligence panel ───────────────────────────────────────────────
function RecoveryPanel({ recovery }) {
  if (!recovery) {
    return (
      <div className="intel-panel">
        <div className="intel-panel-head">
          <span className="intel-panel-title"><GitMerge size={12} /> Recovery Intelligence</span>
        </div>
        <div className="intel-empty">Loading…</div>
      </div>
    )
  }

  if (!recovery.has_recovery) {
    return (
      <div className="intel-panel">
        <div className="intel-panel-head">
          <span className="intel-panel-title"><GitMerge size={12} /> Recovery Intelligence</span>
        </div>
        <div className="intel-empty">No label recovery data found (base_cluster_id not tracked).</div>
      </div>
    )
  }

  const rescuePct = Math.round(recovery.rescue_rate * 100)
  const maxRescue = Math.max(...(recovery.by_field || []).map(f => f.recovered_labels || 0), 1)

  return (
    <div className="intel-panel">
      <div className="intel-panel-head">
        <span className="intel-panel-title"><GitMerge size={12} /> Recovery Intelligence</span>
        <span className="intel-panel-badge">{rescuePct}% rescue rate</span>
      </div>
      <div className="intel-stat-row">
        <div>
          <div className="intel-stat-num" style={{ color: '#4ec994' }}>{fmt(recovery.recovered_labels)}</div>
          <div className="intel-stat-text">
            <span className="intel-stat-label">labels rescued</span>
            <span className="intel-stat-sub">re-routed to a better cluster</span>
          </div>
        </div>
        <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#8a8a96' }}>
            {fmt(recovery.total_labels - recovery.recovered_labels)}
          </div>
          <span className="intel-stat-sub">stayed in original</span>
        </div>
      </div>
      <div className="intel-panel-body">
        {(recovery.by_field || []).slice(0, 6).map(f => {
          const fc = getFieldColor(f.field_name)
          const pw = maxRescue > 0 ? Math.max(3, (f.recovered_labels / maxRescue) * 100) : 3
          return (
            <div key={f.field_name} className="intel-field-row">
              <span className="intel-field-name" style={{ color: fc }}>{f.field_name}</span>
              <div className="intel-bar-track">
                <div className="intel-bar-fill" style={{ width: `${pw}%`, background: '#4ec99488' }} />
              </div>
              <span className="intel-field-val">{fmt(f.recovered_labels)}</span>
            </div>
          )
        })}
        {!recovery.by_field?.length && (
          <div className="intel-empty">No per-field breakdown available.</div>
        )}
      </div>
    </div>
  )
}

// ── Medoid Intelligence panel ─────────────────────────────────────────────────
function MedoidPanel({ medoid, onOpenCluster }) {
  if (!medoid) return null
  if (!medoid.has_medoids) {
    return (
      <div className="intel-panel">
        <div className="intel-panel-head">
          <span className="intel-panel-title"><Cpu size={12} /> Medoid Intelligence</span>
        </div>
        <div className="intel-empty">No medoid_label column found.</div>
      </div>
    )
  }

  const covPct = Math.round(medoid.coverage_rate * 100)

  return (
    <div className="intel-panel">
      <div className="intel-panel-head">
        <span className="intel-panel-title"><Cpu size={12} /> Medoid Intelligence</span>
        <span className="intel-panel-badge">{covPct}% coverage</span>
      </div>
      {medoid.weak?.length > 0 && (
        <>
          <div style={{ padding: '8px 16px 4px', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-3)' }}>
            Weak medoids
          </div>
          {medoid.weak.slice(0, 4).map((c, i) => {
            const fc = getFieldColor(c.field_name)
            return (
              <div key={i} className="intel-item-row" style={{ cursor: 'pointer' }} onClick={() => onOpenCluster(c.id)}>
                <span className="intel-item-field" style={{ color: fc }}>{c.field_name}</span>
                <span className="intel-item-label" style={{ color: 'var(--yellow)', fontStyle: 'italic' }}>
                  "{c.medoid_label}"
                </span>
                {c.cluster_size != null && <span className="intel-item-size">{fmt(c.cluster_size)}</span>}
              </div>
            )
          })}
        </>
      )}
      {medoid.strong?.length > 0 && (
        <>
          <div style={{ padding: '8px 16px 4px', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-3)' }}>
            Strong medoids
          </div>
          {medoid.strong.slice(0, 3).map((c, i) => {
            const fc = getFieldColor(c.field_name)
            return (
              <div key={i} className="intel-item-row" style={{ cursor: 'pointer' }} onClick={() => onOpenCluster(c.id)}>
                <span className="intel-item-field" style={{ color: fc }}>{c.field_name}</span>
                <span className="intel-item-label">{c.medoid_label}</span>
                {c.cluster_size != null && <span className="intel-item-size">{fmt(c.cluster_size)}</span>}
              </div>
            )
          })}
        </>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function OverviewPage() {
  const { health, refreshAll, setSelectedClusterId, navigate } = useAppCtx()
  const [fieldDist,    setFieldDist]   = useState(null)
  const [sizeDist,     setSizeDist]    = useState(null)
  const [topClusters,  setTop]         = useState([])
  const [insights,     setInsights]    = useState(null)
  const [priorities,   setPriorities]  = useState(null)
  const [compression,  setCompression] = useState(null)
  const [recovery,     setRecovery]    = useState(null)
  const [medoid,       setMedoid]      = useState(null)
  const [refreshing,   setRefreshing]  = useState(false)

  useEffect(() => { fetchPageData() }, [])

  async function fetchPageData() {
    const [fd, sd, tc, ins, pri, comp, rec, med] = await Promise.allSettled([
      fetch('/api/field-distribution').then(r => r.json()),
      fetch('/api/cluster-size-distribution').then(r => r.json()),
      fetch('/api/clusters?limit=15').then(r => r.json()),
      fetch('/api/insights').then(r => r.json()),
      fetch('/api/review-priorities').then(r => r.json()),
      fetch('/api/semantic-compression').then(r => r.json()),
      fetch('/api/recovery-intelligence').then(r => r.json()),
      fetch('/api/medoid-intelligence').then(r => r.json()),
    ])
    if (fd.status  === 'fulfilled') setFieldDist(Array.isArray(fd.value) ? fd.value : [])
    if (sd.status  === 'fulfilled') setSizeDist(Array.isArray(sd.value) ? sd.value : [])
    if (tc.status  === 'fulfilled' && Array.isArray(tc.value))
      setTop([...tc.value].sort((a, b) => (b.cluster_size || 0) - (a.cluster_size || 0)))
    if (ins.status === 'fulfilled' && Array.isArray(ins.value)) setInsights(ins.value)
    else setInsights([])
    if (pri.status === 'fulfilled' && Array.isArray(pri.value)) setPriorities(pri.value)
    else setPriorities([])
    if (comp.status === 'fulfilled' && comp.value?.total_clusters != null) setCompression(comp.value)
    if (rec.status  === 'fulfilled') setRecovery(rec.value)
    if (med.status  === 'fulfilled') setMedoid(med.value)
  }

  async function handleRefresh() {
    setRefreshing(true)
    await Promise.allSettled([refreshAll(), fetchPageData()])
    setRefreshing(false)
  }

  function handleInsightAction(insight) {
    if (insight.action?.type === 'filter_field') navigate('clusters')
    else if (insight.action?.type === 'page') navigate(insight.action.page)
    else if (insight.examples?.[0]?.id) setSelectedClusterId(insight.examples[0].id)
  }

  function openCluster(id) {
    navigate('clusters')
    setSelectedClusterId(id)
  }

  const maxSize   = topClusters[0]?.cluster_size || 1
  const criticals = insights?.filter(i => i.severity === 'critical').length || 0
  const warnings  = insights?.filter(i => i.severity === 'warning').length  || 0

  return (
    <div className="page-wrap">
      <div className="page-header">
        <div>
          <h1 className="page-title">Semantic Intelligence</h1>
          <p className="page-subtitle">Embedding observability — compression, recovery, and quality signals</p>
        </div>
        <div className="overview-header-right">
          {criticals > 0 && (
            <span className="alert-chip alert-chip--critical">
              <AlertTriangle size={11} /> {criticals} critical
            </span>
          )}
          {warnings > 0 && (
            <span className="alert-chip alert-chip--warning">
              <AlertTriangle size={11} /> {warnings} warnings
            </span>
          )}
          <button
            className={['btn-icon-text', refreshing && 'spinning'].filter(Boolean).join(' ')}
            onClick={handleRefresh}
          >
            <RefreshCw size={13} />
            Refresh
          </button>
        </div>
      </div>

      {/* Semantic compression hero */}
      <SemanticHero health={health} compression={compression} medoid={medoid} />

      {/* Insights panel */}
      {insights !== null && (
        <div className="section-block">
          <div className="section-head">
            <span className="section-head-title">
              <Zap size={14} className="section-head-icon" />
              Intelligence Insights
            </span>
            <span className="section-head-count">{insights.length} signals</span>
          </div>
          {insights.length === 0 ? (
            <div className="insights-empty">
              <CheckCircle size={16} style={{ color: '#4ec994' }} />
              <span>No issues detected — taxonomy looks healthy.</span>
            </div>
          ) : (
            <div className="insights-grid">
              {insights.map(ins => (
                <InsightCard key={ins.id} insight={ins} onAction={handleInsightAction} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Intelligence panels row */}
      <div className="charts-grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
        <CompressionPanel compression={compression} />
        <RecoveryPanel recovery={recovery} />
        <MedoidPanel medoid={medoid} onOpenCluster={openCluster} />
      </div>

      {/* Charts row */}
      <div className="charts-grid" style={{ marginTop: 16 }}>
        <div className="chart-card">
          <div className="chart-card-title">Cluster Size Distribution</div>
          <div className="chart-card-body">
            {sizeDist ? <ClusterSizeHistogram data={sizeDist} /> : <div className="chart-skeleton" />}
          </div>
        </div>
        <div className="chart-card">
          <div className="chart-card-title">Clusters by Field</div>
          <div className="chart-card-body">
            {fieldDist ? <FieldDistributionChart data={fieldDist} /> : <div className="chart-skeleton" />}
          </div>
        </div>
      </div>

      {/* Bottom panels */}
      <div className="overview-lower-grid" style={{ marginTop: 16 }}>
        <div className="chart-card">
          <div className="chart-card-title">Largest Clusters</div>
          <div className="chart-card-body chart-card-body--list">
            {topClusters.length === 0 && <div className="chart-empty">Loading…</div>}
            {topClusters.slice(0, 12).map((c, i) => (
              <TopClusterRow key={c.id || i} cluster={c} maxSize={maxSize} onClick={openCluster} />
            ))}
          </div>
        </div>

        <div className="chart-card">
          <div className="chart-card-title">
            <Activity size={12} style={{ marginRight: 6 }} />
            Field Health
          </div>
          <div className="chart-card-body chart-card-body--list">
            {compression === null && <div className="chart-skeleton" />}
            {compression?.by_field?.map(f => {
              const fc = getFieldColor(f.field_name)
              const maxLC = Math.max(...(compression.by_field || []).map(x => x.label_count || 0), 1)
              const barW = f.label_count ? Math.max(4, (f.label_count / maxLC) * 100) : 4
              return (
                <div key={f.field_name} className="fh-row">
                  <span className="fh-dot" style={{ background: fc }} />
                  <span className="fh-name">{f.field_name}</span>
                  <div className="fh-bars">
                    <div className="fh-bar-track" title={`${fmt(f.label_count || 0)} items`}>
                      <div className="fh-bar-fill" style={{ width: `${barW}%`, background: fc + 'cc' }} />
                    </div>
                  </div>
                  <span className="fh-count">{fmt(f.cluster_count)}</span>
                </div>
              )
            })}
          </div>
        </div>

        <div className="chart-card chart-card--wide">
          <div className="chart-card-title">
            Top Review Priorities
            <span className="chart-card-subtitle"> — clusters needing attention</span>
          </div>
          <div className="chart-card-body chart-card-body--list">
            {priorities === null && <div className="chart-skeleton" />}
            {priorities?.length === 0 && (
              <div className="chart-empty">
                <CheckCircle size={14} style={{ color: '#4ec994', marginRight: 6 }} />
                No clusters flagged for review.
              </div>
            )}
            {priorities?.slice(0, 10).map(item => (
              <ReviewRow key={item.id} item={item} onClick={id => openCluster(id)} />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
