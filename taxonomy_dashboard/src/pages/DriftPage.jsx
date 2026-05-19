import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Calendar, GitBranch, Layers, Search, Sparkles, TrendingUp, Zap } from 'lucide-react'
import { useAppCtx } from '../context/AppContext.jsx'
import { fmt, fmtDate } from '../utils/format.js'
import { getFieldColor } from '../utils/colors.js'

function StoryPanel({ title, subtitle, icon: Icon = GitBranch, children }) {
  return (
    <section className="chart-card">
      <div className="chart-card-title" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <Icon size={14} />
        {title}
        {subtitle && <span className="chart-card-subtitle">- {subtitle}</span>}
      </div>
      <div className="chart-card-body chart-card-body--list">{children}</div>
    </section>
  )
}

function DriftInsight({ title, metric, text, fields = [], severity = 'info' }) {
  const color = severity === 'risk' ? '#ef4444' : severity === 'watch' ? '#f59e0b' : '#00d4ff'
  return (
    <div className="insight-card" style={{ background: `${color}0b`, borderColor: `${color}30` }}>
      <div className="ic-body">
        <div className="ic-header">
          <span className="ic-title">{title}</span>
          <span className="ic-value" style={{ color }}>{metric}</span>
        </div>
        <p className="ic-reason">{text}</p>
        {!!fields.length && (
          <div className="ic-examples">
            {fields.map(f => <span key={f} className="ic-example-chip" style={{ color: getFieldColor(f) }}>{f}</span>)}
          </div>
        )}
      </div>
    </div>
  )
}

function ClusterRow({ cluster, onOpen }) {
  const color = getFieldColor(cluster.field_name)
  const created = cluster.created_at ? fmtDate(cluster.created_at) : null
  return (
    <button className="emerging-row" style={{ textAlign: 'left' }} onClick={() => onOpen(cluster.id)}>
      <span className="emerging-icon" style={{ color }}><Zap size={12} /></span>
      <div className="emerging-main">
        <span className="emerging-name">{cluster.display_name || cluster.medoid_label || cluster.cluster_id}</span>
        <span className="emerging-field" style={{ color }}>{cluster.field_name}{created ? ` · ${created}` : ''}</span>
      </div>
      <div className="emerging-stats">
        <span className="emerging-size">{fmt(cluster.cluster_size)}</span>
        {cluster.is_true_anomaly_cluster && <span style={{ fontSize: 10, color: '#ef4444', fontWeight: 700 }}>anomaly</span>}
      </div>
    </button>
  )
}

function FieldDriftRow({ field, max }) {
  const color = getFieldColor(field.field_name)
  const width = max ? Math.max(4, (field.total_clusters / max) * 100) : 4
  return (
    <div className="field-drift-row">
      <span className="fdr-dot" style={{ background: color }} />
      <span className="fdr-name">{field.field_name}</span>
      <div className="fdr-bar-wrap">
        <div className="fdr-bar" style={{ width: `${width}%`, background: `${color}66` }} />
      </div>
      <span className="fdr-count">{fmt(field.total_clusters)}</span>
      {field.last_updated && <span className="fdr-anom">{fmtDate(field.last_updated)}</span>}
    </div>
  )
}

function TokenThemes({ clusters }) {
  const stop = new Set(['the', 'and', 'for', 'with', 'from', 'this', 'that', 'into', 'cluster', 'unknown', 'other'])
  const counts = {}
  clusters.forEach(c => {
    const text = `${c.display_name || ''} ${c.medoid_label || ''}`.toLowerCase()
    text.split(/[^a-z0-9]+/).filter(t => t.length > 3 && !stop.has(t)).forEach(t => { counts[t] = (counts[t] || 0) + 1 })
  })
  const themes = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 12)
  if (!themes.length) return <div className="state-empty">No repeated terminology available in the recent cluster sample.</div>
  return (
    <div className="ic-examples">
      {themes.map(([theme, count]) => <span key={theme} className="ic-example-chip">{theme} · {count}</span>)}
    </div>
  )
}

export default function DriftPage() {
  const { setSelectedClusterId, navigate } = useAppCtx()
  const [data, setData] = useState(null)
  const [anomalies, setAnomalies] = useState(null)
  const [priorities, setPriorities] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    Promise.allSettled([
      fetch('/api/drift-summary').then(r => r.json()),
      fetch('/api/anomaly-intelligence').then(r => r.json()),
      fetch('/api/review-priorities').then(r => r.json()),
    ]).then(([drift, anomaly, priority]) => {
      if (drift.status === 'fulfilled') setData(drift.value)
      if (anomaly.status === 'fulfilled') setAnomalies(anomaly.value)
      if (priority.status === 'fulfilled' && Array.isArray(priority.value)) setPriorities(priority.value)
      if (drift.status === 'rejected') setError(drift.reason?.message || 'Unable to load drift data')
    }).finally(() => setLoading(false))
  }, [])

  const newestClusters = data?.newest_clusters || []
  const fieldStats = data?.field_stats || []
  const anomalyFields = anomalies?.summary?.by_field || []
  const maxClusters = Math.max(...fieldStats.map(f => Number(f.total_clusters) || 0), 1)

  const driftInsights = useMemo(() => {
    const out = []
    const newestAnomalies = newestClusters.filter(c => c.is_true_anomaly_cluster)
    if (newestClusters.length) {
      out.push({
        title: 'What changed recently',
        metric: fmt(newestClusters.length),
        text: `${fmt(newestClusters.length)} clusters are newest in the registry sample. These represent the freshest taxonomy surfaces available from current run metadata.`,
        fields: [...new Set(newestClusters.slice(0, 5).map(c => c.field_name))],
      })
    }
    if (newestAnomalies.length) {
      out.push({
        title: 'Recent change contains anomaly risk',
        metric: fmt(newestAnomalies.length),
        text: `${fmt(newestAnomalies.length)} of the newest clusters are anomalous, meaning recent language includes concepts not yet fully integrated into stable taxonomy neighborhoods.`,
        fields: [...new Set(newestAnomalies.map(c => c.field_name))],
        severity: 'risk',
      })
    }
    const hot = [...anomalyFields].sort((a, b) => (b.anomaly_clusters || 0) - (a.anomaly_clusters || 0))[0]
    if (hot) {
      out.push({
        title: `${hot.field_name} is the primary instability zone`,
        metric: fmt(hot.anomaly_clusters),
        text: `${hot.field_name} contributes the largest anomaly load. This is where taxonomy evolution, review, or recoverability scoring will have the most impact.`,
        fields: [hot.field_name],
        severity: 'watch',
      })
    }
    if (priorities.length) {
      out.push({
        title: 'Drift creates review work',
        metric: fmt(priorities.length),
        text: `${priorities.length} review-priority clusters are flagged by naming, anomaly, or compression signals. These are likely instability zones rather than random cleanup tasks.`,
        fields: [...new Set(priorities.slice(0, 5).map(p => p.field_name))],
        severity: 'watch',
      })
    }
    return out
  }, [newestClusters, anomalyFields, priorities])

  function openCluster(id) {
    navigate('clusters')
    setSelectedClusterId(id)
  }

  return (
    <div className="page-wrap">
      <div className="page-header">
        <div>
          <h1 className="page-title">Semantic Drift Intelligence</h1>
          <p className="page-subtitle">Where taxonomy language is changing, fragmenting, and creating review pressure.</p>
        </div>
      </div>

      {error && <div className="state-error">⚠ {error}</div>}
      {loading && <div className="state-loading">Reading semantic drift signals...</div>}

      {!loading && !error && (
        <>
          <StoryPanel title="Drift Narrative" subtitle="what changed recently" icon={Sparkles}>
            <div className="insights-grid">
              {driftInsights.map((insight, i) => <DriftInsight key={i} {...insight} />)}
              {!driftInsights.length && <div className="state-empty">No drift narrative can be generated from the available metadata yet.</div>}
            </div>
          </StoryPanel>

          <div className="drift-two-col">
            <StoryPanel title="Emerging Cluster Candidates" subtitle="fresh semantic regions" icon={Zap}>
              {newestClusters.slice(0, 12).map(c => <ClusterRow key={c.id} cluster={c} onOpen={openCluster} />)}
              {!newestClusters.length && <div className="state-empty">No recent cluster sample returned.</div>}
            </StoryPanel>

            <StoryPanel title="Fields With Rising Pressure" subtitle="where instability concentrates" icon={AlertTriangle}>
              {[...anomalyFields].sort((a, b) => (b.anomaly_clusters || 0) - (a.anomaly_clusters || 0)).slice(0, 10).map(f => (
                <div key={f.field_name} className="field-drift-row">
                  <span className="fdr-dot" style={{ background: getFieldColor(f.field_name) }} />
                  <span className="fdr-name">{f.field_name}</span>
                  <div className="fdr-bar-wrap">
                    <div className="fdr-bar" style={{ width: `${Math.max(4, (f.anomaly_clusters / Math.max(1, anomalyFields[0]?.anomaly_clusters || 1)) * 100)}%`, background: '#ef444466' }} />
                  </div>
                  <span className="fdr-count">{fmt(f.anomaly_clusters)}</span>
                  <span className="fdr-anom">{fmt(f.anomaly_occurrences)} occ.</span>
                </div>
              ))}
              {!anomalyFields.length && <div className="state-empty">Anomaly pressure by field is not available.</div>}
            </StoryPanel>
          </div>

          <StoryPanel title="New Recurring Terminology" subtitle="language themes in newest clusters" icon={Search}>
            <p className="ic-reason">These terms repeat inside the newest cluster sample and can indicate new operational language or taxonomy drift. Counts are derived from display names and medoid labels only.</p>
            <TokenThemes clusters={newestClusters} />
          </StoryPanel>

          <div className="charts-grid" style={{ marginTop: 16 }}>
            <StoryPanel title="Semantic Fragmentation Surface" subtitle="cluster volume by field" icon={Layers}>
              {fieldStats.map(f => <FieldDriftRow key={f.field_name} field={f} max={maxClusters} />)}
            </StoryPanel>

            <StoryPanel title="Cluster Instability Zones" subtitle="highest review priority" icon={TrendingUp}>
              {priorities.slice(0, 10).map(p => (
                <button key={p.id} className="review-row" onClick={() => openCluster(p.id)}>
                  <span className="rr-field" style={{ color: getFieldColor(p.field_name) }}>{p.field_name}</span>
                  <span className="rr-name">{p.display_name || p.medoid_label || p.cluster_id}</span>
                  <div className="rr-right">
                    {p.reasons?.slice(0, 2).map(r => <span key={r} className="rr-reason-chip">{r.replace(/_/g, ' ')}</span>)}
                  </div>
                </button>
              ))}
              {!priorities.length && <div className="state-empty">No instability priorities returned.</div>}
            </StoryPanel>
          </div>

          {!data?.run_timeline?.length && (
            <div className="drift-no-history">
              <strong>Run-to-run drift history is not computed yet.</strong> This page is currently using newest cluster timestamps, anomaly pressure, and review signals as the available drift evidence.
            </div>
          )}
        </>
      )}
    </div>
  )
}
