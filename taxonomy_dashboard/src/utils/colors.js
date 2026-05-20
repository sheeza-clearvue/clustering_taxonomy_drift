const ADDITIONAL_TAGS_FIELD_COLOR = '#2ff3e0'

const PALETTE = [
  '#569cd6', '#4ec9b0', '#c586c0', '#dcdcaa',
  '#ce9178', '#9cdcfe', '#6a9955', '#d7ba7d',
  '#4fc1ff', '#b5cea8', '#f14c4c', '#e5c07b',
]
const FIXED_FIELD_COLORS = {
  additional_tags: ADDITIONAL_TAGS_FIELD_COLOR,
}

const _cache = new Map()

export function getFieldColor(fieldName) {
  if (FIXED_FIELD_COLORS[fieldName]) return FIXED_FIELD_COLORS[fieldName]
  if (_cache.has(fieldName)) return _cache.get(fieldName)
  const idx = _cache.size % PALETTE.length
  _cache.set(fieldName, PALETTE[idx])
  return PALETTE[idx]
}

export function getAnomalyTypeColor(type) {
  const map = {
    noise:             '#858585',
    threshold_failure: '#dcdcaa',
    emerging:          '#c586c0',
    semantic_outlier:  '#f44747',
  }
  return map[type] || '#569cd6'
}

export function getAnomalyTypeLabel(type) {
  const map = {
    noise:             'Noise',
    threshold_failure: 'Threshold Failure',
    emerging:          'Emerging Pattern',
    semantic_outlier:  'Semantic Outlier',
  }
  return map[type] || type
}

export { PALETTE }
