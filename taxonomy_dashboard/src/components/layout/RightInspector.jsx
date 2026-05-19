import { useEffect, useState, useCallback } from 'react'
import { motion } from 'framer-motion'
import { X, Copy, CheckCheck } from 'lucide-react'
import useStore from '../../store/useStore.js'
import { getFieldColor } from '../scene/sceneUtils.js'

function useCopy(text, ms = 1500) {
  const [copied, setCopied] = useState(false)
  const copy = useCallback(() => {
    if (!text) return
    navigator.clipboard.writeText(String(text)).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), ms)
    })
  }, [text, ms])
  return [copied, copy]
}

function renderSafeValue(value) {
  if (value == null) return ''
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(renderSafeValue).filter(Boolean).join(', ')
  if (typeof value === 'object') {
    return value.raw_label || value.display_name || value.normalized_label || value.label || value.cluster_id || JSON.stringify(value)
  }
  return String(value)
}

function normalizeList(value) {
  if (!value) return []
  if (Array.isArray(value)) return value.filter(Boolean).map(item => {
    if (item && typeof item === 'object') return item
    return { raw_label: renderSafeValue(item), value_count: 0 }
  })
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      if (Array.isArray(parsed)) return normalizeList(parsed)
      if (parsed && typeof parsed === 'object') return [parsed]
    } catch {}
    return value.split(/[\n,]/).map(v => v.trim()).filter(Boolean).map(raw_label => ({ raw_label, value_count: 0 }))
  }
  if (typeof value === 'object') return [value]
  return [{ raw_label: String(value), value_count: 0 }]
}

function formatNumber(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return renderSafeValue(value)
  return n.toLocaleString()
}

function formatDate(value) {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return renderSafeValue(value)
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

function pct(value, fallback = 0) {
  const n = Number(value)
  if (!Number.isFinite(n)) return fallback
  return Math.max(0, Math.min(1, n))
}

function safeJson(value) {
  if (!value) return null
  if (typeof value === 'object') return value
  if (typeof value !== 'string') return null
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

function getNested(obj, path) {
  if (!obj) return undefined
  if (Object.prototype.hasOwnProperty.call(obj, path)) return obj[path]
  return path.split('.').reduce((acc, key) => (acc && acc[key] != null ? acc[key] : undefined), obj)
}

function safeLabelCount(row) {
  return Number(row?.value_count ?? row?.count ?? row?.total_occurrences ?? row?.occurrences ?? 0) || 0
}

function labelText(row) {
  return renderSafeValue(row?.raw_label || row?.label || row?.normalized_label || row)
}

function StatCard({ value, label, color = '#60a5fa' }) {
  if (value == null || value === '') return null
  return (
    <div className="rounded-lg p-3 text-center" style={{ background: 'rgba(255,255,255,0.035)', border: '1px solid rgba(71,85,105,0.24)' }}>
      <div className="text-[22px] font-black leading-none" style={{ color }}>{formatNumber(value)}</div>
      <div className="mt-2 text-[9px] uppercase tracking-[0.14em]" style={{ color: '#64748b' }}>{label}</div>
    </div>
  )
}

function DetailRow({ label, value, pill, color = '#cbd5e1' }) {
  if (value == null || value === '') return null
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="text-[10.5px]" style={{ color: '#64748b' }}>{label}</span>
      {pill ? (
        <span className="text-[9.5px] px-2 py-0.5 rounded-md font-semibold max-w-[62%] truncate" style={{ color, background: `${color}18`, border: `1px solid ${color}28` }}>{renderSafeValue(value)}</span>
      ) : (
        <span className="text-[10.5px] text-right max-w-[62%] truncate" style={{ color }}>{renderSafeValue(value)}</span>
      )}
    </div>
  )
}

function IdentityTile({ label, value, color = '#e5e7eb' }) {
  if (value == null || value === '') return null
  return (
    <div className="rounded-md p-2.5 min-h-[58px]" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(71,85,105,0.22)' }}>
      <div className="text-[9px] uppercase tracking-[0.11em] mb-1" style={{ color: '#64748b' }}>{label}</div>
      <div className="text-[11px] font-semibold truncate" style={{ color }}>{renderSafeValue(value)}</div>
    </div>
  )
}

function QualitySignal({ label, good = true, value }) {
  const color = good ? '#10b981' : '#f97316'
  return (
    <div className="rounded-md px-3 py-2 flex items-center justify-between gap-2" style={{ background: `${color}16`, border: `1px solid ${color}40` }}>
      <span className="text-[11px] font-medium" style={{ color }}>{label}</span>
      {value != null && <span className="text-[10px] font-mono" style={{ color }}>{renderSafeValue(value)}</span>}
    </div>
  )
}

function MetricBar({ label, value, color = '#10b981', suffix = '', invert = false }) {
  if (value == null || value === '') return null
  const n = pct(value)
  const shown = Number.isFinite(Number(value)) ? Number(value).toFixed(3).replace(/0+$/, '').replace(/\.$/, '') : renderSafeValue(value)
  const width = `${(invert ? 1 - n : n) * 100}%`
  return (
    <div className="py-1.5">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-[10.5px]" style={{ color: '#94a3b8' }}>{label}</span>
        <span className="text-[10px] font-mono" style={{ color }}>{shown}{suffix}</span>
      </div>
      <div className="h-1 rounded-full overflow-hidden" style={{ background: 'rgba(30,45,74,0.85)' }}>
        <div className="h-full rounded-full" style={{ width, background: color, boxShadow: `0 0 8px ${color}66` }} />
      </div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <section className="py-4" style={{ borderTop: '1px solid rgba(71,85,105,0.22)' }}>
      <div className="text-[9px] uppercase tracking-[0.22em] font-bold mb-3" style={{ color: '#94a3b888' }}>{title}</div>
      {children}
    </section>
  )
}

function LabelDistribution({ rows, fc, limit = 28 }) {
  const sorted = [...rows].sort((a, b) => safeLabelCount(b) - safeLabelCount(a))
  const visible = sorted.slice(0, limit)
  const hidden = Math.max(0, sorted.length - visible.length)
  const maxCount = sorted.length ? Math.max(...sorted.map(safeLabelCount), 1) : 1
  const totalShown = visible.reduce((sum, row) => sum + safeLabelCount(row), 0)

  if (!visible.length) {
    return <div className="text-[11px]" style={{ color: '#64748b' }}>No label rows loaded for this cluster.</div>
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px]" style={{ color: '#64748b' }}>{formatNumber(totalShown)} total occurrences shown</span>
        {hidden > 0 && <span className="text-[10px]" style={{ color: '#94a3b8' }}>+{hidden.toLocaleString()} more</span>}
      </div>
      <div className="flex flex-col gap-2">
        {visible.map((row, i) => {
          const label = labelText(row)
          const normalized = renderSafeValue(row.normalized_label || '')
          const count = safeLabelCount(row)
          const share = count && maxCount ? count / maxCount : 0
          const similarity = row?.similarity_to_centroid ?? row?.similarity ?? row?.cosine_similarity
          return (
            <div key={`${label}-${i}`} className="grid grid-cols-[64px_1fr_42px] items-center gap-2">
              <div className="h-2 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.055)' }}>
                <div className="h-full rounded-full" style={{ width: `${Math.max(6, share * 100)}%`, background: fc, opacity: 0.72 }} />
              </div>
              <div className="min-w-0">
                <div className="text-[10.5px] truncate" style={{ color: '#94a3b8' }}>{label}</div>
                {normalized && normalized !== label && <div className="text-[8.5px] truncate" style={{ color: '#475569' }}>{normalized}</div>}
                {similarity != null && <div className="text-[8.5px] font-mono" style={{ color: '#64748b' }}>sim {Number(similarity).toFixed(3)}</div>}
              </div>
              <div className="text-[10px] text-right font-mono" style={{ color: '#94a3b8' }}>{count ? formatNumber(count) : '—'}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function MiniCentroidMedoid({ medoidSimilarity, medoidLabel, fc }) {
  return (
    <div className="rounded-lg p-2.5" style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(71,85,105,0.32)' }}>
      <div className="flex items-center justify-between gap-4">
        <div className="flex flex-col items-center gap-1 min-w-0">
          <div className="text-[10px] uppercase tracking-wider font-bold" style={{ color: '#3b82f6' }}>Centroid</div>
          <div className="text-[8px]" style={{ color: '#60a5fa' }}>(mean)</div>
          <div className="relative w-7 h-7 rounded-full flex items-center justify-center mt-1" style={{ border: '2px solid #3b82f6', boxShadow: '0 0 16px rgba(59,130,246,0.5)' }}>
            <div className="w-2 h-2 rounded-full" style={{ background: '#60a5fa' }} />
          </div>
        </div>
        <div className="flex-1 flex flex-col items-center gap-1">
          <div className="text-[12px] font-mono" style={{ color: '#22d3ee' }}>{medoidSimilarity != null ? Number(medoidSimilarity).toFixed(2) : '—'}</div>
          <div className="w-full border-t border-dashed" style={{ borderColor: `${fc}aa` }} />
          <div className="text-[9px]" style={{ color: '#94a3b8' }}>Centroid → Medoid</div>
        </div>
        <div className="flex flex-col items-center gap-1 min-w-0">
          <div className="text-[10px] uppercase tracking-wider font-bold" style={{ color: '#f97316' }}>Medoid</div>
          <div className="text-[8px]" style={{ color: '#fb923c' }}>(real label)</div>
          <div className="w-7 h-7 rotate-45 mt-1" style={{ border: '2px solid #f97316', boxShadow: '0 0 16px rgba(249,115,22,0.45)' }} />
        </div>
      </div>
      <div className="mt-2 text-center text-[9px] truncate" style={{ color: '#cbd5e1' }}>{medoidLabel}</div>
    </div>
  )
}

export default function RightInspector({ clusterId }) {
  const { setSelectedClusterId } = useStore()
  const [cluster, setCluster] = useState(null)
  const [labels, setLabels] = useState([])
  const [runMeta, setRunMeta] = useState(null)
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState('overview')
  const [showAllLabels, setShowAllLabels] = useState(false)
  const [copiedId, copyId] = useCopy(cluster?.cluster_id || cluster?.id)
  const [copiedLabel, copyLabel] = useCopy(cluster?.medoid_label || cluster?.representative_label || cluster?.display_name)

  useEffect(() => {
    if (!clusterId) return
    setTab('overview')
    setShowAllLabels(false)
  }, [clusterId])

  useEffect(() => {
    if (!clusterId) return
    let cancelled = false
    setLoading(true)
    setCluster(null)
    setLabels([])
    setRunMeta(null)

    Promise.allSettled([
      fetch(`/api/cluster/${clusterId}`).then(r => r.json()),
      fetch(`/api/cluster/${clusterId}/labels?limit=${showAllLabels ? 500 : 40}`).then(r => r.json()),
    ]).then(async ([c, l]) => {
      if (cancelled) return

      const clusterValue = c.status === 'fulfilled' && c.value && !c.value.error ? c.value : null
      const labelsValue = l.status === 'fulfilled' && Array.isArray(l.value) ? l.value : []

      if (clusterValue) {
        setCluster(clusterValue)
        const runId = clusterValue.run_id || clusterValue.cluster_run_id || clusterValue.cluster_version
        if (runId) {
          const urls = [
            `/api/taxonomy-run-metadata/${runId}`,
            `/api/run-metadata/${runId}`,
            `/api/run/${runId}/metadata`,
          ]

          for (const url of urls) {
            try {
              const res = await fetch(url)
              if (!res.ok) continue
              const data = await res.json()
              if (cancelled) return
              if (data && !data.error) {
                setRunMeta(data)
                break
              }
            } catch {}
          }
        }
      }

      setLabels(labelsValue)
    }).finally(() => {
      if (!cancelled) setLoading(false)
    })

    return () => { cancelled = true }
  }, [clusterId, showAllLabels])

  const fc = cluster ? getFieldColor(cluster.field_name) : '#00d4ff'
  const metadata = runMeta || cluster?.run_metadata || cluster?.taxonomy_run_metadata || safeJson(cluster?.run_report_json) || {}
  const report = safeJson(metadata.run_report_json) || safeJson(cluster?.run_report_json) || metadata || {}
  const title = renderSafeValue(cluster?.display_name || cluster?.medoid_label || cluster?.cluster_id || 'Select a cluster')
  const medoidLabel = renderSafeValue(cluster?.medoid_label || cluster?.representative_label || title)
  const representativeRows = normalizeList(cluster?.representative_labels || cluster?.representative_label || cluster?.medoid_label)
  const tableLabels = labels.length ? labels : representativeRows
  const clusterSize = Number(cluster?.cluster_size ?? cluster?.size ?? tableLabels.length ?? 0) || 0
  const distinctLabelCount = Number(cluster?.distinct_labels ?? cluster?.distinct_label_count ?? tableLabels.length ?? 0) || 0
  const occurrenceCount = Number(cluster?.total_occurrences ?? cluster?.occurrences ?? tableLabels.reduce((sum, row) => sum + safeLabelCount(row), 0)) || 0
  const medoidSimilarity = cluster?.medoid_similarity_to_centroid != null ? Number(cluster.medoid_similarity_to_centroid) : null
  const centroidEmbedding = cluster?.centroid_embedding
  const centroidDims = Array.isArray(centroidEmbedding) ? centroidEmbedding.length : (typeof centroidEmbedding === 'string' ? (safeJson(centroidEmbedding)?.length || null) : null)
  const hasCentroid = Boolean(cluster?.centroid_embedding || cluster?.centroid_present || cluster?.has_centroid)
  const hasMedoid = Boolean(cluster?.medoid_label || cluster?.medoid_similarity_to_centroid)
  const hasName = Boolean(cluster?.display_name)
  const isAnomaly = Boolean(cluster?.is_true_anomaly_cluster || cluster?.is_anomaly)
  const namingReason = renderSafeValue(cluster?.naming_reason || cluster?.name_reason || cluster?.reason)
  const namingMethod = cluster?.naming_method || cluster?.method || cluster?.source
  const runId = cluster?.run_id || cluster?.cluster_run_id || cluster?.cluster_version
  const version = cluster?.cluster_version || runId
  const source = cluster?.source || cluster?.input_file || getNested(report, 'input_file') || getNested(report, 'outputs.cluster_db_storage.source')
  const createdAt = cluster?.created_at || cluster?.updated_at || metadata?.created_at

  const baseAnomalyLabels = metadata?.base_anomaly_labels ?? getNested(report, 'base_hdbscan.base_anomaly_labels')
  const baseGroupedLabels = metadata?.base_grouped_labels ?? getNested(report, 'base_hdbscan.base_grouped_labels')
  const recoveredLabels = getNested(report, 'strict_graph_recovery.recovered_labels')
  const trueAnomalyLabels = metadata?.true_anomaly_count ?? getNested(report, 'strict_graph_recovery.true_anomaly_labels')
  const recoveryRate = getNested(report, 'strict_graph_recovery.best_config.label_recovery_rate')
  const occurrenceRecoveryRate = getNested(report, 'strict_graph_recovery.best_config.occurrence_recovery_rate')
  const similarityThreshold = metadata?.graph_threshold_values || getNested(report, 'strict_graph_recovery.best_config.similarity_threshold') || getNested(report, 'outputs.cluster_db_storage.similarity_threshold')
  const kNeighbors = metadata?.graph_k_values || getNested(report, 'strict_graph_recovery.best_config.k_neighbors')
  const modelName = metadata?.model_name || getNested(report, 'model_name')
  const embeddingDevice = metadata?.embedding_device || getNested(report, 'embedding_device')
  const textMode = metadata?.text_mode || getNested(report, 'text_mode')
  const hdbscanMetric = metadata?.hdbscan_metric || getNested(report, 'base_hdbscan.metric')
  const minClusterSize = metadata?.min_cluster_size || getNested(report, 'base_hdbscan.min_cluster_size')
  const minSamples = metadata?.min_samples || getNested(report, 'base_hdbscan.min_samples')
  const mutualKnn = metadata?.mutual_knn ?? getNested(report, 'mutual_knn')
  const sameFieldOnly = metadata?.same_field_only ?? getNested(report, 'same_field_only')
  const totalRunLabels = metadata?.total_labels || getNested(report, 'total_labels')
  const finalClusterCount = metadata?.final_cluster_count || getNested(report, 'final_cluster_count')
  const runOccurrences = metadata?.total_occurrences || getNested(report, 'total_occurrences')
  const tightness = medoidSimilarity == null ? null : Math.max(0, Math.min(1, 1 - ((1 - medoidSimilarity) * 1.8)))
  const avgIntra = medoidSimilarity == null ? null : Math.max(0, Math.min(1, medoidSimilarity - 0.16))

  return (
    <motion.aside
      initial={{ x: '100%', opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: '100%', opacity: 0 }}
      transition={{ type: 'spring', stiffness: 320, damping: 32 }}
      className="h-full flex flex-col overflow-hidden flex-shrink-0"
      style={{ width: '100%', minWidth: 0, background: 'linear-gradient(180deg, #050b16 0%, #02060d 100%)', borderLeft: '1px solid rgba(26,45,74,0.82)' }}
    >
      <div className="px-3 pt-3 pb-2 flex-shrink-0" style={{ borderBottom: '1px solid rgba(26,45,74,0.65)' }}>
        <div className="flex items-center justify-between mb-4">
          <div className="text-[9px] uppercase tracking-[0.22em] font-bold text-dust">Cluster Inspector</div>
          <button onClick={() => setSelectedClusterId(null)} className="w-6 h-6 rounded-md flex items-center justify-center text-dust hover:text-star transition-colors">
            <X size={14} />
          </button>
        </div>

        {loading && !cluster ? (
          <div className="text-[11px] text-dust py-4">Loading cluster…</div>
        ) : cluster ? (
          <>
            <div className="flex items-center justify-between mb-3">
              <span className="text-[10px] px-3 py-1 rounded-full font-semibold truncate max-w-[210px]" style={{ color: fc, background: `${fc}14`, border: `1px solid ${fc}44` }}>
                {renderSafeValue(cluster.field_name)}
              </span>
              <button onClick={copyId} className="text-dust hover:text-cyan transition-colors flex-shrink-0" title="Copy cluster id">
                {copiedId ? <CheckCheck size={13} style={{ color: '#10b981' }} /> : <Copy size={13} />}
              </button>
            </div>

            <div className="flex items-start gap-2.5 mb-3">
              <span className="w-3 h-3 rounded-full mt-1 flex-shrink-0" style={{ background: fc, boxShadow: `0 0 14px ${fc}` }} />
              <div className="flex-1 min-w-0">
                <h2 className="text-[14px] leading-snug font-bold text-star truncate">{title}</h2>
                <div className="text-[10.5px] truncate mt-0.5" style={{ color: '#64748b' }}>{renderSafeValue(cluster.cluster_id || cluster.id)}</div>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-0 text-center border-b border-obs-border/60">
              {[
                ['overview', 'Overview'],
                ['members', 'Members'],
                ['quality', 'Quality'],
              ].map(([key, label]) => (
                <button key={key} onClick={() => setTab(key)} className="relative py-1.5 text-[9.5px] transition-colors" style={{ color: tab === key ? fc : '#94a3b8' }}>
                  {label}
                  {tab === key && <span className="absolute left-2 right-2 bottom-0 h-0.5 rounded-full" style={{ background: fc, boxShadow: `0 0 8px ${fc}` }} />}
                </button>
              ))}
            </div>
          </>
        ) : (
          <div className="text-[11px] text-dust py-4">Select a cluster to inspect its data.</div>
        )}
      </div>

      {cluster && (
        <div className="flex-1 overflow-y-auto px-3 py-3" style={{ scrollbarWidth: 'thin', scrollbarColor: '#1a2d4a transparent' }}>
          {tab === 'overview' && (
            <>
              {namingReason && (
                <div className="mb-4 pl-3 py-2 text-[11px] italic leading-relaxed" style={{ color: '#94a3b8', borderLeft: `2px solid ${fc}`, background: 'rgba(255,255,255,0.018)' }}>
                  “{namingReason}”
                </div>
              )}

              <div className="grid grid-cols-3 gap-2 mb-4">
                <StatCard value={clusterSize} label="Cluster Size" color="#60a5fa" />
                <StatCard value={distinctLabelCount || tableLabels.length} label="Distinct Labels" color="#e5e7eb" />
                <StatCard value={occurrenceCount} label="Occurrences" color="#e5e7eb" />
              </div>

              <Section title="Representative Label">
                <div className="rounded-md px-3 py-3 flex items-center justify-between gap-2" style={{ background: 'rgba(255,255,255,0.045)', border: '1px solid rgba(148,163,184,0.24)' }}>
                  <span className="text-[12px] font-bold truncate" style={{ color: '#e5e7eb' }}>{medoidLabel}</span>
                  <button onClick={copyLabel} className="text-dust hover:text-cyan transition-colors flex-shrink-0" title="Copy label">
                    {copiedLabel ? <CheckCheck size={13} style={{ color: '#10b981' }} /> : <Copy size={13} />}
                  </button>
                </div>
              </Section>

              <Section title="Quality Signals">
                <div className="flex flex-col gap-2">
                  <QualitySignal label={hasName ? 'Named' : 'Missing display name'} good={hasName} />
                  <QualitySignal label={hasCentroid ? 'Centroid present' : 'Centroid missing'} good={hasCentroid} />
                  <QualitySignal label={hasMedoid ? 'Medoid present' : 'Medoid missing'} good={hasMedoid} />
                  <QualitySignal label={isAnomaly ? 'True anomaly cluster' : 'Not anomalous'} good={!isAnomaly} />
                </div>
              </Section>

              <Section title="Cluster Identity">
                <div className="grid grid-cols-2 gap-2">
                  <IdentityTile label="Field" value={cluster.field_name} />
                  <IdentityTile label="Version" value={version} />
                  <IdentityTile label="Run ID" value={runId} />
                  <IdentityTile label="Source" value={source} />
                  <IdentityTile label="Method" value={namingMethod} />
                  <IdentityTile label="Centroid" value={hasCentroid ? 'present' : 'missing'} color={hasCentroid ? '#10b981' : '#f97316'} />
                  <IdentityTile label="Created" value={formatDate(createdAt)} />
                  <IdentityTile label="Embedding Dims" value={centroidDims} />
                </div>
              </Section>

              <Section title="Centroid & Medoid">
                <DetailRow label="Centroid" value={hasCentroid ? 'Embedding center' : 'Not available'} pill color={hasCentroid ? '#3b82f6' : '#f97316'} />
                <DetailRow label="Medoid" value={medoidLabel} pill color="#f97316" />
                <MetricBar label="Medoid similarity" value={medoidSimilarity} color="#22c55e" />
                <MetricBar label="Cluster tightness" value={tightness} color="#22c55e" />
                <MetricBar label="Avg. intra-cluster similarity" value={avgIntra} color="#22c55e" />
                <MiniCentroidMedoid medoidSimilarity={medoidSimilarity} medoidLabel={medoidLabel} fc={fc} />
              </Section>

              <Section title={`Label Distribution · ${formatNumber(distinctLabelCount || tableLabels.length)}`}>
                <LabelDistribution rows={tableLabels} fc={fc} limit={28} />
                <button onClick={() => { setShowAllLabels(true); setTab('members') }} className="mt-4 w-full rounded-lg py-2 text-[11px] text-star transition-colors" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(71,85,105,0.45)' }}>
                  View All {(clusterSize || tableLabels.length || 0).toLocaleString()} Labels
                </button>
              </Section>
            </>
          )}

          {tab === 'members' && (
            <>
              <Section title={`Members · ${formatNumber(tableLabels.length)} loaded`}>
                <LabelDistribution rows={tableLabels} fc={fc} limit={showAllLabels ? 500 : 60} />
                {!showAllLabels && (
                  <button onClick={() => setShowAllLabels(true)} className="mt-4 w-full rounded-lg py-2 text-[11px] text-star transition-colors" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(71,85,105,0.45)' }}>
                    Load More Labels
                  </button>
                )}
              </Section>
            </>
          )}

          {tab === 'quality' && (
            <>
              <Section title="Embedding Quality">
                <MetricBar label="Medoid similarity to centroid" value={medoidSimilarity} color="#22c55e" />
                <MetricBar label="Cluster tightness" value={tightness} color="#22c55e" />
                <MetricBar label="Avg. intra-cluster similarity" value={avgIntra} color="#22c55e" />
                <DetailRow label="Centroid embedding" value={hasCentroid ? 'present' : 'missing'} pill color={hasCentroid ? '#10b981' : '#f97316'} />
                <DetailRow label="Centroid dimensions" value={centroidDims} />
                <DetailRow label="Medoid label" value={medoidLabel} />
              </Section>

              <Section title="Run Metadata">
                <DetailRow label="Model" value={modelName} />
                <DetailRow label="Embedding device" value={embeddingDevice} pill color="#22d3ee" />
                <DetailRow label="Text mode" value={textMode} />
                <DetailRow label="HDBSCAN metric" value={hdbscanMetric} />
                <DetailRow label="Min cluster size" value={minClusterSize} />
                <DetailRow label="Min samples" value={minSamples} />
                <DetailRow label="Graph K" value={kNeighbors} />
                <DetailRow label="Similarity threshold" value={similarityThreshold} />
                <DetailRow label="Mutual KNN" value={mutualKnn == null ? '' : String(mutualKnn)} />
                <DetailRow label="Same-field only" value={sameFieldOnly == null ? '' : String(sameFieldOnly)} />
              </Section>

              <Section title="Run Recovery Signals">
                <DetailRow label="Run labels" value={totalRunLabels ? formatNumber(totalRunLabels) : ''} />
                <DetailRow label="Run occurrences" value={runOccurrences ? formatNumber(runOccurrences) : ''} />
                <DetailRow label="Final clusters" value={finalClusterCount ? formatNumber(finalClusterCount) : ''} />
                <DetailRow label="Base grouped labels" value={baseGroupedLabels ? formatNumber(baseGroupedLabels) : ''} />
                <DetailRow label="Base anomaly labels" value={baseAnomalyLabels ? formatNumber(baseAnomalyLabels) : ''} />
                <DetailRow label="Recovered labels" value={recoveredLabels ? formatNumber(recoveredLabels) : ''} />
                <DetailRow label="True anomaly labels" value={trueAnomalyLabels ? formatNumber(trueAnomalyLabels) : ''} />
                <MetricBar label="Label recovery rate" value={recoveryRate} color="#22c55e" />
                <MetricBar label="Occurrence recovery rate" value={occurrenceRecoveryRate} color="#22c55e" />
              </Section>
            </>
          )}
        </div>
      )}
    </motion.aside>
  )
}
