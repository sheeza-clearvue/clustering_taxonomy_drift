export function fmt(n) {
  if (n === null || n === undefined) return '—'
  return Number(n).toLocaleString()
}

export function pct(part, total) {
  if (!total || part === null || part === undefined) return ''
  return `${Math.round((part / total) * 100)}%`
}

export function fmtDate(dateStr) {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export function truncate(str, len = 40) {
  if (!str) return ''
  return str.length > len ? str.slice(0, len) + '…' : str
}
