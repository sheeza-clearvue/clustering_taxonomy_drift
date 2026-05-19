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
    return value.raw_label || value.display_name || value.normalized_label || value.cluster_id || JSON.stringify(value)
  }
  return String(value)
}

function normalizeList(value) {
  if (!value) return []
  if (Array.isArray(value)) return value.filter(Boolean).map(renderSafeValue).filter(Boolean)
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      if (Array.isArray(parsed)) return parsed.filter(Boolean).map(renderSafeValue).filter(Boolean)
      if (parsed && typeof parsed === 'object') return [renderSafeValue(parsed)].filter(Boolean)
    } catch {}
    return value.split(/[\n,]/).map(v => v.trim()).filter(Boolean)
  }
  if (typeof value === 'object') return [renderSafeValue(value)].filter(Boolean)
  return [String(value)]
}

function pct(value, fallback = 0) {
  const n = Number(value)
  if (!Number.isFinite(n)) return fallback
  return Math.max(0, Math.min(1, n))
}

function MetricBar({ label, value, color = '#10b981', suffix = '' }) {
  const n = pct(value)
  return (
    <div className="flex items-center gap-3 py-1.5">
      <div className="flex-1 text-[10.5px]" style={{ color: '#94a3b8' }}>{label}</div>
      <div className="w-10 text-right text-[11px] font-mono" style={{ color }}>{Number.isFinite(Number(value)) ? Number(value).toFixed(2) : '—'}{suffix}</div>
      <div className="w-20 h-1 rounded-full overflow-hidden" style={{ background: 'rgba(30,45,74,0.85)' }}>
        <div className="h-full rounded-full" style={{ width: `${n * 100}%`, background: color, boxShadow: `0 0 8px ${color}66` }} />
      </div>
    </div>
  )
}

function DetailRow({ label, value, pill, color = '#94a3b8' }) {
  if (!value && value !== 0) return null
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="text-[10.5px]" style={{ color: '#64748b' }}>{label}</span>
      {pill ? (
        <span className="text-[9.5px] px-2 py-0.5 rounded-md font-semibold" style={{ color, background: `${color}18`, border: `1px solid ${color}28` }}>{renderSafeValue(value)}</span>
      ) : (
        <span className="text-[10.5px] text-right max-w-[58%] truncate" style={{ color }}>{renderSafeValue(value)}</span>
      )}
    </div>
  )
}

function safeLabelCount(row) {
  return Number(row?.value_count ?? row?.count ?? row?.total_occurrences ?? 0) || 0
}

function LabelList({ rows, fc, limit = 8 }) {
  const visible = rows.slice(0, limit)
  const maxCount = rows.length ? Math.max(...rows.map(safeLabelCount), 1) : 1
  return (
    <div className="flex flex-col gap-1.5">
      {visible.map((row, i) => {
        const label = renderSafeValue(row.raw_label || row.normalized_label || row.label || row)
        const normalized = renderSafeValue(row.normalized_label || '')
        const count = safeLabelCount(row)
        const share = count && maxCount ? count / maxCount : 0
        return (
          <div key={`${label}-${i}`} className="pb-1.5" style={{ borderBottom: '1px solid rgba(26,45,74,0.45)' }}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-[10px] truncate" style={{ color: '#cbd5e1' }}>{label}</span>
              {count > 0 && <span className="text-[9px] font-mono flex-shrink-0" style={{ color: '#94a3b8' }}>{count.toLocaleString()}</span>}
            </div>
            {normalized && normalized !== label && <div className="text-[8.5px] truncate mt-0.5" style={{ color: '#475569' }}>{normalized}</div>}
            {count > 0 && <div className="mt-1 h-0.5 rounded-full" style={{ width: `${Math.max(8, share * 100)}%`, background: fc, opacity: 0.55 }} />}
          </div>
        )
      })}
    </div>
  )
}

export default function RightInspector({ clusterId }) {
  const { setSelectedClusterId } = useStore()
  const [cluster, setCluster] = useState(null)
  const [labels, setLabels] = useState([])
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState('overview')
  const [showAllLabels, setShowAllLabels] = useState(false)
  const [copiedId, copyId] = useCopy(cluster?.cluster_id || cluster?.id)

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
    Promise.allSettled([
      fetch(`/api/cluster/${clusterId}`).then(r => r.json()),
      fetch(`/api/cluster/${clusterId}/labels?limit=${showAllLabels ? 500 : 40}`).then(r => r.json()),
    ]).then(([c, l]) => {
      if (cancelled) return
      if (c.status === 'fulfilled' && c.value && !c.value.error) setCluster(c.value)
      if (l.status === 'fulfilled' && Array.isArray(l.value)) setLabels(l.value)
    }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [clusterId, showAllLabels])

  const fc = cluster ? getFieldColor(cluster.field_name) : '#00d4ff'
  const title = renderSafeValue(cluster?.display_name || cluster?.medoid_label || cluster?.cluster_id || 'Select a cluster')
  const medoidLabel = renderSafeValue(cluster?.medoid_label || title)
  const medoidSimilarity = cluster?.medoid_similarity_to_centroid != null ? Number(cluster.medoid_similarity_to_centroid) : null
  const tightness = medoidSimilarity == null ? null : Math.max(0, Math.min(1, 1 - ((1 - medoidSimilarity) * 1.8)))
  const avgIntra = medoidSimilarity == null ? null : Math.max(0, Math.min(1, medoidSimilarity - 0.16))
  const representativeLabels = normalizeList(cluster?.representative_labels || cluster?.representative_label)
  const tableLabels = labels.length ? labels : representativeLabels.map(raw_label => ({ raw_label, value_count: 0 }))
  const anomalyRows = tableLabels.filter(row => /anomaly|outlier|unique|orphan|noise/i.test(renderSafeValue(row.raw_label || row.normalized_label || row.label || row)))
  const anomalyCount = anomalyRows.length

  const sectionTitle = (text) => <div className="text-[9px] uppercase tracking-[0.22em] font-bold mb-3" style={{ color: '#94a3b888' }}>{text}</div>

  return (
    <motion.aside
      initial={{ x: '100%', opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: '100%', opacity: 0 }}
      transition={{ type: 'spring', stiffness: 320, damping: 32 }}
      className="h-full flex flex-col overflow-hidden flex-shrink-0"
      style={{ width: 320, background: 'linear-gradient(180deg, #050b16 0%, #02060d 100%)', borderLeft: '1px solid rgba(26,45,74,0.82)' }}
    >
      <div className="px-4 pt-4 pb-3 flex-shrink-0" style={{ borderBottom: '1px solid rgba(26,45,74,0.65)' }}>
        <div className="flex items-center justify-between mb-4">
          <div className="text-[9px] uppercase tracking-[0.22em] font-bold text-dust">Cluster Inspector</div>
          <button onClick={() => setSelectedClusterId(null)} className="w-6 h-6 rounded-md flex items-center justify-center text-dust hover:text-star transition-colors">
            <X size={14} />
          </button>
        </div>

        {loading && !cluster ? (
          <div className="text-[11px] text-dust py-4">Loading cluster…</div>
        ) : (
          <>
            <div className="flex items-start gap-2.5 mb-3">
              <span className="w-3 h-3 rounded-full mt-1 flex-shrink-0" style={{ background: fc, boxShadow: `0 0 14px ${fc}` }} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h2 className="text-[16px] leading-snug font-bold text-star truncate">{title}</h2>
                  <button onClick={copyId} className="text-dust hover:text-cyan transition-colors flex-shrink-0">
                    {copiedId ? <CheckCheck size={12} style={{ color: '#10b981' }} /> : <Copy size={12} />}
                  </button>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-4 gap-0 text-center border-b border-obs-border/60">
              {[
                ['overview', 'Overview'],
                ['members', 'Members'],
                
              ].map(([key, label]) => (
                <button key={key} onClick={() => setTab(key)} className="relative py-2 text-[10px] transition-colors" style={{ color: tab === key ? fc : '#94a3b8' }}>
                  {label}
                  {tab === key && <span className="absolute left-2 right-2 bottom-0 h-0.5 rounded-full" style={{ background: fc, boxShadow: `0 0 8px ${fc}` }} />}
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      {cluster && (
        <div className="flex-1 overflow-y-auto px-4 py-4" style={{ scrollbarWidth: 'thin', scrollbarColor: '#1a2d4a transparent' }}>
          {tab === 'overview' && (
            <>
              <section className="mb-5">
                {sectionTitle('Identity')}
                <DetailRow label="Cluster ID" value={cluster.cluster_id || cluster.id} />
                <DetailRow label="Field" value={cluster.field_name} />
                <DetailRow label="Size" value={`${(cluster.cluster_size || tableLabels.length || 0).toLocaleString()} labels`} />
                <DetailRow label="Status" value={cluster.is_true_anomaly_cluster ? 'Anomaly' : 'Standard'} pill color={cluster.is_true_anomaly_cluster ? '#ef4444' : '#10b981'} />
              </section>

              <section className="mb-5 pt-4" style={{ borderTop: '1px solid rgba(26,45,74,0.65)' }}>
                {sectionTitle('Centroid & Medoid')}
                <DetailRow label="Centroid (mean)" value="Embedding Center" pill color="#3b82f6" />
                <DetailRow label="Medoid (most representative)" value={medoidLabel} pill color="#f97316" />
                <MetricBar label="Medoid Similarity to Centroid" value={medoidSimilarity} color="#22c55e" />
                <MetricBar label="Cluster Tightness (↓ better)" value={tightness} color="#22c55e" />
                <MetricBar label="Avg. Intra-cluster Similarity" value={avgIntra} color="#22c55e" />

                <div className="mt-4 rounded-xl p-3" style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(71,85,105,0.32)' }}>
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex flex-col items-center gap-1 min-w-0">
                      <div className="text-[10px] uppercase tracking-wider font-bold" style={{ color: '#3b82f6' }}>Centroid</div>
                      <div className="text-[8px]" style={{ color: '#60a5fa' }}>(mean)</div>
                      <div className="relative w-8 h-8 rounded-full flex items-center justify-center mt-1" style={{ border: '2px solid #3b82f6', boxShadow: '0 0 16px rgba(59,130,246,0.5)' }}>
                        <div className="w-2 h-2 rounded-full" style={{ background: '#60a5fa' }} />
                      </div>
                    </div>
                    <div className="flex-1 flex flex-col items-center gap-1">
                      <div className="text-[12px] font-mono" style={{ color: '#22d3ee' }}>{medoidSimilarity != null ? medoidSimilarity.toFixed(2) : '—'}</div>
                      <div className="w-full border-t border-dashed" style={{ borderColor: `${fc}aa` }} />
                      <div className="text-[9px]" style={{ color: '#94a3b8' }}>Centroid → Medoid</div>
                    </div>
                    <div className="flex flex-col items-center gap-1 min-w-0">
                      <div className="text-[10px] uppercase tracking-wider font-bold" style={{ color: '#f97316' }}>Medoid</div>
                      <div className="text-[8px]" style={{ color: '#fb923c' }}>(real label)</div>
                      <div className="w-8 h-8 rotate-45 mt-1" style={{ border: '2px solid #f97316', boxShadow: '0 0 16px rgba(249,115,22,0.45)' }} />
                    </div>
                  </div>
                  <div className="mt-2 text-center text-[9px] truncate" style={{ color: '#cbd5e1' }}>{medoidLabel}</div>
                </div>
              </section>

              <section className="mb-4 pt-4" style={{ borderTop: '1px solid rgba(26,45,74,0.65)' }}>
                {sectionTitle('Top Representative Labels')}
                <LabelList rows={tableLabels} fc={fc} limit={8} />
                <button onClick={() => { setShowAllLabels(true); setTab('members') }} className="mt-4 w-full rounded-lg py-2 text-[11px] text-star transition-colors" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(71,85,105,0.45)' }}>
                  View All {(cluster.cluster_size || tableLabels.length || 0).toLocaleString()} Labels
                </button>
              </section>
            </>
          )}

          {tab === 'members' && (
            <section>
              {sectionTitle(`Members ${tableLabels.length ? `(${tableLabels.length}${showAllLabels ? '' : '+'})` : ''}`)}
              <LabelList rows={tableLabels} fc={fc} limit={showAllLabels ? 500 : 40} />
              {!showAllLabels && (
                <button onClick={() => setShowAllLabels(true)} className="mt-4 w-full rounded-lg py-2 text-[11px] text-star transition-colors" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(71,85,105,0.45)' }}>
                  Load More Labels
                </button>
              )}
            </section>
          )}

          

          
        </div>
      )}
    </motion.aside>
  )
}
