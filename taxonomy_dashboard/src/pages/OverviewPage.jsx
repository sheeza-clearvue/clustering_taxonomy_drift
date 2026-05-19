import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowRight, Brain, CheckCircle, GitMerge, Layers, Search, ShieldCheck, Sparkles, TrendingUp } from 'lucide-react'
import { useAppCtx } from '../context/AppContext.jsx'
import { fmt } from '../utils/format.js'
import { getFieldColor } from '../utils/colors.js'

function Panel({ title, subtitle, icon: Icon = Brain, children }) {
  return (
    <section className="chart-card" style={{ overflow: 'hidden' }}>
      <div className="chart-card-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Icon size={14} />
        <span>{title}</span>
        {subtitle && <span className="chart-card-subtitle">- {subtitle}</span>}
      </div>
      <div className="chart-card-body chart-card-body--list">{children}</div>
    </section>
  )
}

function InsightCard({ insight, onClick }) {
  const color = insight.severity === 'critical' ? '#ef4444' : insight.severity === 'warning' ? '#f59e0b' : '#00d4ff'
  return (
    <button
      className="insight-card"
      style={{ textAlign: 'left', background: `${color}0b`, borderColor: `${color}30` }}
      onClick={onClick}
    >
      <div className="ic-body">
        <div className="ic-header">
          <span className="ic-title">{insight.title}</span>
          <span className="ic-value" style={{ color }}>{insight.metric}</span>
        </div>
        <p className="ic-reason">{insight.explanation}</p>
        {insight.fields?.length > 0 && (
          <div className="ic-examples">
            {insight.fields.slice(0, 3).map(f => (
              <span key={f} className="ic-example-chip" style={{ color: getFieldColor(f), borderColor: `${getFieldColor(f)}33` }}>
                {f}
              </span>
            ))}
          </div>
        )}
      </div>
      <ArrowRight size={13} className="ic-arrow" />
    </button>
  )
}

function FieldStory({ field, maxLabels, maxAnomaly }) {
  const color = getFieldColor(field.field_name)
  const diversity = maxLabels ? (Number(field.label_count) || 0) / maxLabels : 0
  const anomalyPressure = maxAnomaly ? (Number(field.anomaly_clusters) || 0) / maxAnomaly : 0
  const tone = anomalyPressure > 0.65 ? 'highest anomaly pressure' : diversity > 0.65 ? 'broad semantic coverage' : 'stable repeated taxonomy behavior'
  return (
    <div className="review-row" style={{ cursor: 'default' }}>
      <div className="rr-bar" style={{ width: `${Math.max(5, diversity * 100)}%`, background: `${color}18` }} />
      <span className="rr-field" style={{ color }}>{field.field_name}</span>
      <span className="rr-name">
        {tone}. {fmt(field.cluster_count)} clusters compress {fmt(field.label_count || 0)} labels.
      </span>
      <div className="rr-right">
        <span className="rr-reason-chip">{field.compression_ratio ? `${field.compression_ratio}x compression` : 'compression n/a'}</span>
        {(field.anomaly_clusters || 0) > 0 && <span className="rr-reason-chip">{fmt(field.anomaly_clusters)} anomalies</span>}
      </div>
    </div>
  )
}

function ClusterPattern({ cluster, onOpen }) {
  const color = getFieldColor(cluster.field_name)
  return (
    <button className="top-cluster-row" style={{ textAlign: 'left' }} onClick={() => onOpen(cluster.id)}>
      <div className="tcr-bar" style={{ width: `${Math.min(100, Math.max(8, Math.log1p(cluster.cluster_size || 1) * 12))}%`, background: `${color}18` }} />
      <span className="tcr-field" style={{ color }}>{cluster.field_name}</span>
      <span className="tcr-name">{cluster.display_name || cluster.medoid_label || cluster.cluster_id}</span>
      <div className="tcr-right">
        <span className="tcr-size">{fmt(cluster.cluster_size)}</span>
        {cluster.medoid_label && <span className="rr-reason-chip">medoid</span>}
      </div>
    </button>
  )
}

export default function OverviewPage() {
  const { health, navigate, setSelectedClusterId } = useAppCtx()
  const [data, setData] = useState({
    compression: null,
    anomalies: null,
    medoid: null,
    drift: null,
    priorities: [],
    clusters: [],
  })

  useEffect(() => {
    Promise.allSettled([
      fetch('/api/semantic-compression').then(r => r.json()),
      fetch('/api/anomaly-intelligence').then(r => r.json()),
      fetch('/api/medoid-intelligence').then(r => r.json()),
      fetch('/api/drift-summary').then(r => r.json()),
      fetch('/api/review-priorities').then(r => r.json()),
      fetch('/api/clusters?limit=80').then(r => r.json()),
    ]).then(([compression, anomalies, medoid, drift, priorities, clusters]) => {
      setData({
        compression: compression.status === 'fulfilled' ? compression.value : null,
        anomalies: anomalies.status === 'fulfilled' ? anomalies.value : null,
        medoid: medoid.status === 'fulfilled' ? medoid.value : null,
        drift: drift.status === 'fulfilled' ? drift.value : null,
        priorities: priorities.status === 'fulfilled' && Array.isArray(priorities.value) ? priorities.value : [],
        clusters: clusters.status === 'fulfilled' && Array.isArray(clusters.value) ? clusters.value : [],
      })
    })
  }, [])

  const insights = useMemo(() => {
    const out = []
    const raw = data.compression?.raw_label_count || health?.total_label_rows
    const clusters = data.compression?.total_clusters || health?.total_clusters
    if (raw && clusters) {
      out.push({
        title: 'Raw taxonomy language has been consolidated into semantic groups',
        explanation: `${fmt(raw)} raw label rows now resolve into ${fmt(clusters)} cluster records, turning fragmented call language into inspectable semantic neighborhoods.`,
        metric: data.compression?.compression_ratio ? `${data.compression.compression_ratio}x` : fmt(clusters),
        fields: data.compression?.by_field?.slice(0, 2).map(f => f.field_name) || [],
        severity: 'info',
        action: 'observatory',
      })
    }
    const byField = data.anomalies?.summary?.by_field || []
    if (byField.length) {
      const top = [...byField].sort((a, b) => (b.anomaly_clusters || 0) - (a.anomaly_clusters || 0)).slice(0, 2)
      const total = byField.reduce((s, f) => s + Number(f.anomaly_clusters || 0), 0)
      const share = total ? top.reduce((s, f) => s + Number(f.anomaly_clusters || 0), 0) / total : 0
      out.push({
        title: 'Anomaly pressure is concentrated, not evenly distributed',
        explanation: `${top.map(f => f.field_name).join(' and ')} account for ${(share * 100).toFixed(0)}% of anomaly clusters. Review effort should start there before broad taxonomy changes.`,
        metric: `${(share * 100).toFixed(0)}%`,
        fields: top.map(f => f.field_name),
        severity: share > 0.45 ? 'warning' : 'info',
        action: 'anomalies',
      })
    }
    const best = data.compression?.by_field?.slice().sort((a, b) => (b.compression_ratio || 0) - (a.compression_ratio || 0))[0]
    if (best) {
      out.push({
        title: `${best.field_name} shows the strongest semantic consolidation`,
        explanation: `${fmt(best.label_count || 0)} labels compress into ${fmt(best.cluster_count)} groups, indicating repeated operational language with strong taxonomy structure.`,
        metric: best.compression_ratio ? `${best.compression_ratio}x` : fmt(best.cluster_count),
        fields: [best.field_name],
        severity: 'info',
        action: 'clusters',
      })
    }
    if (data.priorities?.length) {
      out.push({
        title: 'Review work is concentrated in a small set of cluster neighborhoods',
        explanation: `${data.priorities.length} clusters are flagged by anomaly, naming, or compression signals. These are the highest-leverage cleanup targets.`,
        metric: fmt(data.priorities.length),
        fields: [...new Set(data.priorities.slice(0, 5).map(p => p.field_name))],
        severity: 'warning',
        action: 'clusters',
      })
    }
    return out
  }, [data, health])

  const raw = data.compression?.raw_label_count || health?.total_label_rows || 0
  const clusterCount = data.compression?.total_clusters || health?.total_clusters || 0
  const reduction = raw ? Math.max(0, 1 - clusterCount / raw) : null
  const fields = data.compression?.by_field || []
  const anomalyByField = data.anomalies?.summary?.by_field || []
  const fieldsWithAnomaly = fields.map(f => ({ ...f, anomaly_clusters: anomalyByField.find(a => a.field_name === f.field_name)?.anomaly_clusters || 0 }))
  const maxLabels = Math.max(...fieldsWithAnomaly.map(f => Number(f.label_count) || 0), 1)
  const maxAnomaly = Math.max(...fieldsWithAnomaly.map(f => Number(f.anomaly_clusters) || 0), 1)
  const topPatterns = [...data.clusters].sort((a, b) => (b.total_occurrences || b.cluster_size || 0) - (a.total_occurrences || a.cluster_size || 0)).slice(0, 8)

  function go(action) {
    if (action === 'observatory') navigate('observatory')
    if (action === 'anomalies') navigate('anomalies')
    if (action === 'clusters') navigate('clusters')
  }

  function openCluster(id) {
    navigate('clusters')
    setSelectedClusterId(id)
  }

  return (
    <div className="page-wrap">
      <div className="page-header">
        <div>
          <h1 className="page-title">Semantic Intelligence Center</h1>
          <p className="page-subtitle">What changed, what matters, where risk lives, and what to review next.</p>
        </div>
      </div>

      <Panel title="Key Taxonomy Insights" subtitle="executive readout" icon={Sparkles}>
        <div className="insights-grid">
          {insights.map((insight, i) => <InsightCard key={i} insight={insight} onClick={() => go(insight.action)} />)}
          {!insights.length && <div className="state-loading">Generating semantic readout from available taxonomy data...</div>}
        </div>
      </Panel>

      <div className="charts-grid" style={{ marginTop: 16 }}>
        <Panel title="Before vs After Taxonomy" subtitle="business value proof" icon={GitMerge}>
          <div className="intel-stat-row">
            <div>
              <div className="intel-stat-num" style={{ color: '#a855f7' }}>{fmt(raw)}</div>
              <div className="intel-stat-sub">raw fragmented label rows before clustering</div>
            </div>
            <ArrowRight size={18} style={{ color: '#334155' }} />
            <div>
              <div className="intel-stat-num" style={{ color: '#10b981' }}>{fmt(clusterCount)}</div>
              <div className="intel-stat-sub">semantic clusters after consolidation</div>
            </div>
          </div>
          <div className="intel-bar-track" style={{ marginTop: 12 }}>
            <div className="intel-bar-fill" style={{ width: `${reduction != null ? reduction * 100 : 0}%`, background: 'linear-gradient(90deg,#a855f7,#10b981)' }} />
          </div>
          <p className="ic-reason">{reduction != null ? `${(reduction * 100).toFixed(1)}% redundancy removed. This is the core operational value: repeated language becomes searchable, measurable taxonomy structure.` : 'Compression details are not available yet.'}</p>
        </Panel>

        <Panel title="Quality Signals" subtitle="actionable cleanup targets" icon={ShieldCheck}>
          {data.priorities.slice(0, 7).map(item => (
            <button key={item.id} className="review-row" onClick={() => openCluster(item.id)}>
              <span className="rr-field" style={{ color: getFieldColor(item.field_name) }}>{item.field_name}</span>
              <span className="rr-name">{item.display_name || item.medoid_label || item.cluster_id}</span>
              <div className="rr-right">
                {item.reasons?.slice(0, 2).map(r => <span key={r} className="rr-reason-chip">{r.replace(/_/g, ' ')}</span>)}
              </div>
            </button>
          ))}
          {!data.priorities.length && <div className="insights-empty"><CheckCircle size={14} /> No review priorities returned.</div>}
        </Panel>
      </div>

      <Panel title="Field Intelligence" subtitle="semantic behavior by taxonomy surface" icon={Layers}>
        {fieldsWithAnomaly.map(field => <FieldStory key={field.field_name} field={field} maxLabels={maxLabels} maxAnomaly={maxAnomaly} />)}
      </Panel>

      <Panel title="Operational Pattern Discovery" subtitle="high-frequency business language" icon={Search}>
        {topPatterns.map(c => <ClusterPattern key={c.id} cluster={c} onOpen={openCluster} />)}
        {!topPatterns.length && <div className="state-empty">No cluster examples available.</div>}
      </Panel>

      <Panel title="Semantic Health Brain" subtitle="coverage, cohesion, and risk" icon={TrendingUp}>
        <div className="insights-grid">
          <InsightCard
            insight={{
              title: 'Centroid coverage',
              explanation: health?.centroid_missing_count === 0 ? 'All clusters report centroid coverage, so similarity-based workflows have the required embedding anchors.' : `${fmt(health?.centroid_missing_count || 0)} clusters are missing centroids, which weakens nearest-neighbor and recoverability workflows.`,
              metric: health?.centroid_missing_count === 0 ? 'complete' : fmt(health?.centroid_missing_count || 0),
              fields: [],
              severity: health?.centroid_missing_count === 0 ? 'info' : 'warning',
            }}
          />
          <InsightCard
            insight={{
              title: 'Medoid coverage',
              explanation: data.medoid?.coverage_rate != null ? `${(data.medoid.coverage_rate * 100).toFixed(1)}% of clusters have medoid labels, giving the taxonomy human-readable semantic anchors.` : 'Medoid coverage was not returned by the backend.',
              metric: data.medoid?.coverage_rate != null ? `${(data.medoid.coverage_rate * 100).toFixed(0)}%` : 'n/a',
              fields: [],
              severity: 'info',
            }}
          />
        </div>
      </Panel>
    </div>
  )
}
