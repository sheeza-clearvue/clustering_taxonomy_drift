// ─ Deterministic hash helpers ─────────────────────────────────────────────────
export function hashStr(str) {
  let h = 0
  for (let i = 0; i < str.length; i++) {
    h = (Math.imul(31, h) + str.charCodeAt(i)) | 0
  }
  return h >>> 0
}

export function seededRand(seed) {
  const x = Math.sin(seed + 1) * 10000
  return x - Math.floor(x)
}

// ─ Field → color mapping (stable, deterministic) ──────────────────────────────
const FIELD_PALETTE = [
  '#00d4ff', '#a855f7', '#10b981', '#f97316',
  '#e879f9', '#3b82f6', '#f59e0b', '#06b6d4',
  '#8b5cf6', '#ec4899', '#14b8a6', '#84cc16',
]
const _fieldColorCache = {}
let _fieldIndex = 0

export function getFieldColor(fieldName) {
  if (!fieldName) return '#94a3b8'
  if (_fieldColorCache[fieldName]) return _fieldColorCache[fieldName]
  const color = FIELD_PALETTE[_fieldIndex % FIELD_PALETTE.length]
  _fieldColorCache[fieldName] = color
  _fieldIndex++
  return color
}

// ─ Spatial layout ─────────────────────────────────────────────────────────────
//
// Each taxonomy field forms its own "galaxy arm" at a large orbit radius.
// Clusters spread within the arm based on cluster_size and label_count.
// Anomalies are pushed to the outer periphery — they form isolated islands.
//
// Scale deliberately wide so the semantic universe feels massive and navigable.
//
export function clusterPosition(cluster, fieldIdx, numFields) {
  const id = cluster.cluster_id || String(cluster.id || '')
  const h1 = hashStr(id)
  const h2 = hashStr(id + '_x')
  const h3 = hashStr(id + '_y')

  // Field arm angle — evenly distributed around the full circle
  const armAngle  = (fieldIdx / Math.max(numFields, 1)) * Math.PI * 2
  // Each field arm sits at a distinct orbit radius (55–80 units from origin)
  const armRadius = 55 + seededRand(fieldIdx * 23 + 7) * 25

  // Semantic properties drive local spread within the arm
  const sizeLog  = Math.log(Math.max(cluster.cluster_size || 1, 1) + 1)
  const labelLog = Math.log(Math.max(cluster.label_count  || 1, 1) + 1)

  // Local scatter — larger clusters are denser (lower localR)
  const localAngle = seededRand(h1) * Math.PI * 2
  const localR     = sizeLog * 2.8 + seededRand(h2) * 14

  // Vertical spread — label-rich clusters float higher
  const localY = (seededRand(h3) - 0.5) * 38 + (labelLog - 2) * 2.2

  // Anomalies form isolated islands at the galaxy periphery
  const anomalyPush = cluster.is_true_anomaly_cluster ? 32 + seededRand(h1 * 3) * 20 : 0

  const r = armRadius + anomalyPush
  return [
    Math.cos(armAngle) * r + Math.cos(localAngle) * localR,
    localY,
    Math.sin(armAngle) * r + Math.sin(localAngle) * localR,
  ]
}

export function buildSpatialLayout(clusters) {
  const fieldNames  = [...new Set(clusters.map(c => c.field_name).filter(Boolean))]
  const fieldIdxMap = Object.fromEntries(fieldNames.map((f, i) => [f, i]))

  return clusters.map(c => ({
    ...c,
    _pos:   clusterPosition(c, fieldIdxMap[c.field_name] ?? 0, fieldNames.length),
    _color: c.is_true_anomaly_cluster ? '#ff3344' : getFieldColor(c.field_name),
    // Size: sqrt-scaled so large clusters are visibly bigger, cap at 2.6
    _size:  Math.max(0.15, Math.min(2.6, Math.sqrt(Math.max(c.cluster_size || 1, 1)) * 0.18)),
  }))
}
