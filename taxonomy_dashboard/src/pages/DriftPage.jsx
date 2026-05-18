import { useEffect, useState } from 'react'
import { TrendingUp, Zap, Calendar, Layers, AlertTriangle } from 'lucide-react'
import { useAppCtx } from '../context/AppContext.jsx'
import { fmt, fmtDate } from '../utils/format.js'
import { getFieldColor } from '../utils/colors.js'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
  LineChart, Line, CartesianGrid, Legend,
} from 'recharts'

function NewestClusterRow({ cluster, onClick }) {
  const color = getFieldColor(cluster.field_name)
  return (
    <div className="emerging-row" onClick={() => onClick(cluster.id)}>
      <span className="emerging-icon" style={{ color: '#569cd6' }}><Zap size={12} /></span>
      <div className="emerging-main">
        <span className="emerging-name">
          {cluster.display_name || <span className="unnamed">unnamed</span>}
        </span>
        <span className="emerging-field" style={{ color }}>{cluster.field_name}</span>
      </div>
      <div className="emerging-stats">
        {cluster.cluster_size != null && (
          <span className="emerging-size">{fmt(cluster.cluster_size)}</span>
        )}
        {cluster.is_true_anomaly_cluster && (
          <span style={{ fontSize: 10, color: 'var(--red)', fontWeight: 700 }}>anomaly</span>
        )}
      </div>
    </div>
  )
}

function FieldBar({ field, maxClusters }) {
  const color = getFieldColor(field.field_name)
  const barW  = maxClusters > 0 ? Math.max(3, (field.total_clusters / maxClusters) * 100) : 3
  const anomPct = field.total_clusters > 0 && field.anomaly_count
    ? Math.round((field.anomaly_count / field.total_clusters) * 100)
    : 0
  return (
    <div className="field-drift-row">
      <span className="fdr-dot" style={{ background: color }} />
      <span className="fdr-name">{field.field_name}</span>
      <div className="fdr-bar-wrap">
        <div className="fdr-bar" style={{ width: `${barW}%`, background: color + '66' }} />
      </div>
      <span className="fdr-count">{fmt(field.total_clusters)}</span>
      {anomPct > 0 && <span className="fdr-anom">{anomPct}% anom</span>}
    </div>
  )
}

const TOOLTIP_STYLE = {
  backgroundColor: '#252526',
  border: '1px solid #3e3e42',
  borderRadius: 6,
  color: '#ccc',
  fontSize: 12,
}

export default function DriftPage() {
  const { setSelectedClusterId } = useAppCtx()
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetch('/api/drift-summary')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(d => setData(d))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  // Server returns: { run_timeline, newest_clusters, field_stats }
  const runTimeline    = data?.run_timeline    || []
  const newestClusters = data?.newest_clusters || []
  const fieldStats     = data?.field_stats     || []

  const hasRunHistory = runTimeline.length > 0

  // Aggregate run timeline by date for chart
  const timelineByDate = {}
  for (const r of runTimeline) {
    if (!timelineByDate[r.run_date]) timelineByDate[r.run_date] = { date: r.run_date, count: 0 }
    timelineByDate[r.run_date].count += r.run_count || 0
  }
  const timelineChart = Object.values(timelineByDate)
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(-30)

  const maxClusters = Math.max(...fieldStats.map(f => f.total_clusters || 0), 1)
  const totalAnomalies = newestClusters.filter(c => c.is_true_anomaly_cluster).length

  return (
    <div className="page-wrap">
      <div className="page-header">
        <div>
          <h1 className="page-title">Drift &amp; Emerging Patterns</h1>
          <p className="page-subtitle">
            {hasRunHistory
              ? 'Track taxonomy evolution across clustering runs'
              : 'Static snapshot — cluster distribution and emerging signals'}
          </p>
        </div>
        <div className="drift-summary-badges">
          <span className="dsb-item">
            <span className="dsb-label">Fields</span>
            {fieldStats.length}
          </span>
          <span className="dsb-item">
            <Layers size={11} />
            {fmt(fieldStats.reduce((s, f) => s + (f.total_clusters || 0), 0))} clusters
          </span>
          {totalAnomalies > 0 && (
            <span className="dsb-item dsb-item--warn">
              <AlertTriangle size={11} /> {totalAnomalies} new anomalies
            </span>
          )}
        </div>
      </div>

      {error && <div className="state-error">⚠ {error}</div>}
      {loading && <div className="state-loading">Loading drift data…</div>}

      {!loading && !error && data && (
        <>
          {/* No run history notice */}
          {!hasRunHistory && (
            <div className="drift-no-history">
              <strong>No clustering run history found.</strong> Showing static snapshot from current cluster data.
              <br />
              Run history requires a <code>taxonomy_cluster_runs</code> table.
            </div>
          )}

          {/* Run timeline chart — only when history exists */}
          {hasRunHistory && timelineChart.length > 1 && (
            <div className="chart-card" style={{ marginBottom: 20 }}>
              <div className="chart-card-title">Clustering Activity (last 30 days)</div>
              <div className="chart-card-body" style={{ height: 180 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={timelineChart} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                    <CartesianGrid stroke="#2d2d30" strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={{ fill: '#858585', fontSize: 10 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: '#858585', fontSize: 10 }} axisLine={false} tickLine={false} width={36} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: '#ffffff0a' }} />
                    <Bar dataKey="count" name="Run Count" radius={[3, 3, 0, 0]}>
                      {timelineChart.map((_, i) => (
                        <Cell key={i} fill="#569cd6" />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Main two-col layout */}
          <div className="drift-two-col">
            {/* Newest / recently added clusters */}
            <div>
              <div className="drift-section-title">
                <Calendar size={13} style={{ marginRight: 6 }} />
                Recently Added Clusters
              </div>
              {newestClusters.length === 0
                ? <div className="state-empty">No cluster data available.</div>
                : (
                  <div className="emerging-list">
                    {newestClusters.slice(0, 10).map((c, i) => (
                      <NewestClusterRow
                        key={c.id || i}
                        cluster={c}
                        onClick={id => setSelectedClusterId(id)}
                      />
                    ))}
                  </div>
                )
              }
            </div>

            {/* Anomalies in new clusters */}
            <div>
              <div className="drift-section-title">
                <Zap size={13} style={{ marginRight: 6 }} />
                Anomalies in Recent Clusters
              </div>
              {newestClusters.filter(c => c.is_true_anomaly_cluster).length === 0
                ? <div className="state-empty" style={{ color: '#4ec994' }}>
                    No anomalies in the most recent clusters.
                  </div>
                : (
                  <div className="emerging-list">
                    {newestClusters.filter(c => c.is_true_anomaly_cluster).slice(0, 10).map((c, i) => (
                      <NewestClusterRow
                        key={c.id || i}
                        cluster={c}
                        onClick={id => setSelectedClusterId(id)}
                      />
                    ))}
                  </div>
                )
              }
            </div>
          </div>

          {/* Field distribution */}
          {fieldStats.length > 0 && (
            <div className="chart-card" style={{ marginTop: 4 }}>
              <div className="chart-card-title">
                <TrendingUp size={12} style={{ marginRight: 6 }} />
                Cluster Distribution by Field
              </div>
              <div className="chart-card-body chart-card-body--list">
                <div className="field-drift-list">
                  {fieldStats.map((f, i) => (
                    <FieldBar key={f.field_name || i} field={f} maxClusters={maxClusters} />
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Field size bar chart */}
          {fieldStats.length > 1 && (
            <div className="chart-card" style={{ marginTop: 16 }}>
              <div className="chart-card-title">Total Items by Field</div>
              <div className="chart-card-body" style={{ height: 160 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={fieldStats.map(f => ({ name: f.field_name, clusters: f.total_clusters, items: Number(f.total_labels) || 0 }))}
                    margin={{ top: 4, right: 8, left: 0, bottom: 4 }}
                    layout="vertical"
                  >
                    <XAxis type="number" tick={{ fill: '#858585', fontSize: 10 }} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="name" tick={{ fill: '#858585', fontSize: 10 }} axisLine={false} tickLine={false} width={110} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: '#ffffff08' }} />
                    <Legend wrapperStyle={{ fontSize: 11, color: '#858585' }} />
                    <Bar dataKey="clusters" name="Clusters" fill="#569cd6" radius={[0, 3, 3, 0]} />
                    {fieldStats.some(f => f.total_labels) && (
                      <Bar dataKey="items" name="Items" fill="#4ec9b088" radius={[0, 3, 3, 0]} />
                    )}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
