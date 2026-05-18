import { useEffect, useState, useCallback } from 'react'
import { motion } from 'framer-motion'
import { X, Copy, CheckCheck, Tag, Layers, Sparkles, Activity, AlertTriangle, CheckCircle } from 'lucide-react'
import { useAppCtx } from '../context/AppContext.jsx'
import { fmt, fmtDate, truncate } from '../utils/format.js'
import { getFieldColor } from '../utils/colors.js'

// ── Helpers ───────────────────────────────────────────────────────────────────
function useCopy(text, ms = 1500) {
  const [copied, setCopied] = useState(false)
  const copy = useCallback(() => {
    if (!text) return
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), ms)
    })
  }, [text, ms])
  return [copied, copy]
}

// ── Section ───────────────────────────────────────────────────────────────────
function Section({ title, icon: Icon, children, muted }) {
  return (
    <div className={['dp-section', muted && 'dp-section--muted'].filter(Boolean).join(' ')}>
      <div className="dp-section-head">
        {Icon && <Icon size={12} />}
        <span>{title}</span>
      </div>
      {children}
    </div>
  )
}

// ── Stat grid ─────────────────────────────────────────────────────────────────
function StatGrid({ children }) {
  return <div className="dp-stat-grid">{children}</div>
}

function Stat({ label, value, accent, mono, full }) {
  if (!value && value !== 0) return null
  return (
    <div className={['dp-stat-cell', full && 'dp-stat-cell--full'].filter(Boolean).join(' ')}>
      <span className="dp-stat-label">{label}</span>
      <span className={['dp-stat-value', mono && 'mono', accent && `dp-accent-${accent}`].filter(Boolean).join(' ')}>
        {value}
      </span>
    </div>
  )
}

// ── Medoid label with copy ────────────────────────────────────────────────────
function MedoidLabel({ label }) {
  const [copied, copy] = useCopy(label)
  if (!label) return null
  return (
    <div className="dp-medoid-wrap">
      <span className="dp-medoid-label">{label}</span>
      <button className="dp-copy-btn" onClick={copy} title="Copy medoid label">
        {copied ? <CheckCheck size={12} style={{ color: '#4ec994' }} /> : <Copy size={12} />}
      </button>
    </div>
  )
}

// ── Score gauge ───────────────────────────────────────────────────────────────
function ScoreBar({ label, value, max, color }) {
  const pct = max ? Math.max(2, Math.round((value / max) * 100)) : 0
  return (
    <div className="dp-score-row">
      <span className="dp-score-label">{label}</span>
      <div className="dp-score-track">
        <div className="dp-score-fill" style={{ width: `${pct}%`, background: color || '#569cd6' }} />
      </div>
      <span className="dp-score-val">{fmt(value)}</span>
    </div>
  )
}

// ── Label bar ─────────────────────────────────────────────────────────────────
function LabelBar({ label, count, max, color }) {
  const pct = max ? Math.max(3, (count / max) * 100) : 3
  return (
    <div className="label-bar-row">
      <div className="label-bar-track">
        <div className="label-bar-fill" style={{ width: `${pct}%`, background: color + '99' || '#569cd699' }} />
      </div>
      <span className="label-bar-text" title={label}>{truncate(label, 34)}</span>
      <span className="label-bar-count">{fmt(count)}</span>
    </div>
  )
}

// ── Similar card ──────────────────────────────────────────────────────────────
function SimilarCard({ cluster, onClick, fieldColor }) {
  return (
    <button className="similar-card" onClick={() => onClick(cluster.id)}>
      <span className="similar-card-field" style={{ color: fieldColor }}>
        {cluster.field_name}
      </span>
      <span className="similar-card-name">
        {cluster.display_name || <span className="unnamed">unnamed</span>}
      </span>
      <div className="similar-card-meta">
        {cluster.cluster_size && <span>{fmt(cluster.cluster_size)} items</span>}
        {cluster.is_true_anomaly_cluster && <span className="similar-card-anom">anomaly</span>}
      </div>
    </button>
  )
}

// ── Quality indicators ────────────────────────────────────────────────────────
function QualitySection({ cluster, labels }) {
  const issues = []
  if (!cluster.display_name) issues.push({ type: 'warn', text: 'No display name assigned' })
  if (!cluster.has_centroid)  issues.push({ type: 'warn', text: 'Centroid embedding missing' })
  if (cluster.is_true_anomaly_cluster) issues.push({ type: 'critical', text: 'Flagged as anomaly' })
  if (cluster.cluster_size <= 2) issues.push({ type: 'info', text: 'Micro-cluster (size ≤ 2)' })
  if (labels.length <= 1 && cluster.cluster_size > 10) issues.push({ type: 'warn', text: 'Large cluster with very few distinct labels' })

  const ok = []
  if (cluster.display_name) ok.push('Named')
  if (cluster.has_centroid)  ok.push('Centroid present')
  if (!cluster.is_true_anomaly_cluster) ok.push('Not anomalous')

  if (issues.length === 0 && ok.length === 0) return null

  return (
    <Section title="Quality Signals" icon={Activity}>
      <div className="dp-quality-list">
        {issues.map((issue, i) => (
          <div key={i} className={`dp-quality-item dp-quality-item--${issue.type}`}>
            <AlertTriangle size={11} />
            <span>{issue.text}</span>
          </div>
        ))}
        {ok.map((text, i) => (
          <div key={`ok-${i}`} className="dp-quality-item dp-quality-item--ok">
            <CheckCircle size={11} />
            <span>{text}</span>
          </div>
        ))}
      </div>
    </Section>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function ClusterDetailPanel({ clusterId }) {
  const { setSelectedClusterId } = useAppCtx()
  const [cluster,  setCluster]  = useState(null)
  const [labels,   setLabels]   = useState([])
  const [similar,  setSimilar]  = useState([])
  const [loading,  setLoading]  = useState(false)

  useEffect(() => {
    if (!clusterId) return
    setCluster(null); setLabels([]); setSimilar([])
    setLoading(true)

    Promise.allSettled([
      fetch(`/api/cluster/${clusterId}`).then(r => r.json()),
      fetch(`/api/cluster/${clusterId}/labels?limit=40`).then(r => r.json()),
      fetch(`/api/cluster/${clusterId}/similar?limit=8`).then(r => r.json()),
    ]).then(([c, l, s]) => {
      if (c.status === 'fulfilled') setCluster(c.value)
      if (l.status === 'fulfilled' && Array.isArray(l.value)) setLabels(l.value)
      if (s.status === 'fulfilled' && Array.isArray(s.value)) setSimilar(s.value)
    }).finally(() => setLoading(false))
  }, [clusterId])

  const fieldColor  = cluster ? getFieldColor(cluster.field_name) : '#569cd6'
  const maxCount    = labels.length ? Math.max(...labels.map(l => Number(l.value_count) || 1)) : 1
  const totalOcc    = labels.reduce((s, l) => s + (Number(l.value_count) || 0), 0)

  return (
    <motion.aside
      className="detail-panel"
      initial={{ x: '100%', opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: '100%', opacity: 0 }}
      transition={{ type: 'spring', stiffness: 320, damping: 32 }}
    >
      {/* Header */}
      <div className="dp-header" style={{ borderBottomColor: fieldColor + '33' }}>
        <div className="dp-header-badges">
          <span
            className="dp-field-badge"
            style={{ background: fieldColor + '18', color: fieldColor, borderColor: fieldColor + '44' }}
          >
            {cluster?.field_name || '…'}
          </span>
          {cluster?.is_true_anomaly_cluster && (
            <span className="dp-anom-badge">
              <AlertTriangle size={10} /> Anomaly
            </span>
          )}
          {cluster?.active === false && (
            <span className="dp-inactive-badge">Inactive</span>
          )}
        </div>
        <button className="dp-close" onClick={() => setSelectedClusterId(null)}>
          <X size={15} />
        </button>
      </div>

      {loading && !cluster && (
        <div className="dp-loading">
          <div className="dp-loading-spinner" />
          Loading cluster…
        </div>
      )}

      {cluster && (
        <div className="dp-scroll">

          {/* Cluster name hero */}
          <div className="dp-hero">
            <div className="dp-hero-name">
              {cluster.display_name || <span className="unnamed">Unnamed Cluster</span>}
            </div>
            <div className="dp-hero-id" title={cluster.cluster_id}>{cluster.cluster_id}</div>
            {cluster.naming_reason && (
              <div className="dp-hero-reason">"{cluster.naming_reason}"</div>
            )}
          </div>

          {/* Key metrics row */}
          <div className="dp-metrics-row">
            <div className="dp-metric-big">
              <span className="dp-metric-big-val" style={{ color: fieldColor }}>{fmt(cluster.cluster_size)}</span>
              <span className="dp-metric-big-label">Cluster Size</span>
            </div>
            <div className="dp-metric-sep" />
            <div className="dp-metric-big">
              <span className="dp-metric-big-val">{fmt(labels.length)}</span>
              <span className="dp-metric-big-label">Distinct Labels</span>
            </div>
            <div className="dp-metric-sep" />
            <div className="dp-metric-big">
              <span className="dp-metric-big-val">{fmt(cluster.total_occurrences)}</span>
              <span className="dp-metric-big-label">Occurrences</span>
            </div>
          </div>

          {/* Medoid label */}
          {cluster.medoid_label && (
            <div className="dp-section">
              <div className="dp-section-head"><Tag size={12} /><span>Representative Label</span></div>
              <MedoidLabel label={cluster.medoid_label} />
            </div>
          )}

          {/* Quality signals */}
          <QualitySection cluster={cluster} labels={labels} />

          {/* Identity details */}
          <Section title="Cluster Identity" icon={Activity}>
            <StatGrid>
              <Stat label="Field"       value={cluster.field_name} />
              <Stat label="Version"     value={cluster.cluster_version} />
              <Stat label="Run ID"      value={truncate(cluster.run_id, 20)} mono />
              <Stat label="Source"      value={cluster.cluster_source} />
              <Stat label="Method"      value={cluster.naming_method} />
              <Stat label="Threshold"   value={cluster.similarity_threshold != null ? Number(cluster.similarity_threshold).toFixed(3) : null} mono />
              <Stat label="Centroid"    value={cluster.has_centroid ? '✓ present' : '✗ missing'} accent={cluster.has_centroid ? 'green' : 'red'} />
              <Stat label="Created"     value={fmtDate(cluster.created_at)} />
            </StatGrid>
          </Section>

          {/* Label frequency bars */}
          <Section title={`Label Distribution${labels.length ? ` · ${labels.length}` : ''}`} icon={Layers}>
            {labels.length === 0 && <div className="dp-hint">No labels available.</div>}
            {totalOcc > 0 && (
              <div className="dp-label-summary">
                <span>{fmt(totalOcc)} total occurrences shown</span>
                {cluster.cluster_size > labels.length && (
                  <span className="dp-label-summary-more">
                    +{fmt(cluster.cluster_size - labels.length)} more
                  </span>
                )}
              </div>
            )}
            <div className="label-bars">
              {labels.map((l, i) => (
                <LabelBar
                  key={i}
                  label={l.raw_label}
                  count={Number(l.value_count) || 1}
                  max={maxCount}
                  color={fieldColor}
                />
              ))}
            </div>
          </Section>

          {/* Similar clusters */}
          <Section title="Other Clusters in Field" icon={Sparkles}>
            {similar.length === 0 && <div className="dp-hint">No other clusters found.</div>}
            <div className="similar-grid">
              {similar.map(s => (
                <SimilarCard
                  key={s.id}
                  cluster={s}
                  fieldColor={getFieldColor(s.field_name)}
                  onClick={id => setSelectedClusterId(id)}
                />
              ))}
            </div>
          </Section>

        </div>
      )}
    </motion.aside>
  )
}
