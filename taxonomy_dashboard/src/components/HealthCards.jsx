import { fmt, pct } from '../utils/format.js'

function MetricCard({ label, value, sub, accent, icon, pulse }) {
  return (
    <div className={['hcard', accent && `hcard--${accent}`, pulse && 'hcard--pulse'].filter(Boolean).join(' ')}>
      {icon && <span className="hcard-icon">{icon}</span>}
      <div className="hcard-body">
        <div className="hcard-value">{value ?? '—'}</div>
        <div className="hcard-label">{label}</div>
        {sub && <div className="hcard-sub">{sub}</div>}
      </div>
    </div>
  )
}

export default function HealthCards({ health }) {
  if (!health) {
    return (
      <div className="hcards-grid">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="hcard skeleton" />
        ))}
      </div>
    )
  }

  const namePct   = pct(health.named_clusters,   health.total_clusters)
  const anomPct   = pct(health.anomaly_clusters, health.total_clusters)
  const unnamePct = pct(health.unnamed_clusters, health.total_clusters)

  return (
    <div className="hcards-grid">
      <MetricCard label="Total Clusters"  value={fmt(health.total_clusters)}  accent="blue"   icon="⊞" />
      <MetricCard label="Named"           value={fmt(health.named_clusters)}   accent="green"  sub={namePct}   icon="✓" />
      <MetricCard label="Unnamed"         value={fmt(health.unnamed_clusters)} accent="yellow" sub={unnamePct} icon="○" />
      <MetricCard
        label="Anomalies"
        value={health.anomaly_clusters !== null ? fmt(health.anomaly_clusters) : 'N/A'}
        accent="red"
        sub={anomPct}
        icon="⚠"
        pulse={health.anomaly_clusters > 0}
      />
      <MetricCard label="Label Rows"   value={fmt(health.total_label_rows)} icon="⊡" />
      <MetricCard label="Fields"       value={fmt(health.fields_count)}     icon="◫" />
      {health.duplicate_names > 0 && (
        <MetricCard label="Duplicate Names" value={fmt(health.duplicate_names)} accent="orange" icon="⚡" />
      )}
      {health.centroid_missing_count !== null && (
        <MetricCard
          label="Missing Centroids"
          value={fmt(health.centroid_missing_count)}
          accent={health.centroid_missing_count > 0 ? 'yellow' : 'green'}
          icon="◎"
        />
      )}
    </div>
  )
}
