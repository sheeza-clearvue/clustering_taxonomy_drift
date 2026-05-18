import {
  LayoutDashboard, Database, Boxes,
  AlertTriangle, TrendingUp, Search, Activity,
} from 'lucide-react'
import { useAppCtx } from '../context/AppContext.jsx'
import { fmt } from '../utils/format.js'

const NAV_ITEMS = [
  { id: 'overview',       label: 'Overview',         sub: 'System health',     Icon: LayoutDashboard },
  { id: 'clusters',       label: 'Cluster Explorer', sub: 'Browse & search',   Icon: Database        },
  { id: 'semantic-space', label: 'Semantic Space',   sub: 'Topology graph',    Icon: Boxes           },
  { id: 'anomalies',      label: 'Anomalies',        sub: 'Investigate',       Icon: AlertTriangle   },
  { id: 'drift',          label: 'Drift & Patterns', sub: 'Evolution over time',Icon: TrendingUp      },
]

export default function Sidebar() {
  const { activePage, navigate, health, setSearchOpen } = useAppCtx()

  const anomCount = health?.anomaly_clusters || 0
  const namePct   = health?.total_clusters
    ? Math.round((health.named_clusters / health.total_clusters) * 100)
    : null

  return (
    <aside className="sidebar">
      {/* Brand */}
      <div className="sidebar-brand">
        <div className="sb-logo-mark">
          <Activity size={16} strokeWidth={1.5} />
        </div>
        <div className="sb-brand-text">
          <span className="sb-brand-name">Taxonomy</span>
          <span className="sb-brand-sub">Intelligence</span>
        </div>
      </div>

      {/* Search */}
      <div className="sidebar-search-wrap">
        <button className="sidebar-search-btn" onClick={() => setSearchOpen(true)}>
          <Search size={12} className="ssb-icon" />
          <span className="ssb-label">Search clusters…</span>
          <kbd className="ssb-kbd">⌘K</kbd>
        </button>
      </div>

      {/* Nav */}
      <nav className="sidebar-nav">
        <div className="snav-section-label">Navigation</div>
        {NAV_ITEMS.map(({ id, label, sub, Icon }) => {
          const isActive = activePage === id
          const badge = id === 'anomalies' && anomCount > 0 ? anomCount : null
          return (
            <button
              key={id}
              className={['nav-item', isActive && 'active'].filter(Boolean).join(' ')}
              onClick={() => navigate(id)}
            >
              <span className="nav-icon-wrap">
                <Icon size={15} />
              </span>
              <span className="nav-text">
                <span className="nav-label">{label}</span>
                <span className="nav-sub">{sub}</span>
              </span>
              {badge && <span className="nav-badge">{badge > 99 ? '99+' : badge}</span>}
            </button>
          )
        })}
      </nav>

      {/* Health summary */}
      {health && (
        <div className="sidebar-health">
          <div className="sh-header">
            <span className="sh-title">System</span>
            <span className={['sh-status-dot', anomCount > 0 ? 'sh-status-dot--warn' : 'sh-status-dot--ok'].join(' ')} />
          </div>
          <div className="sh-metrics">
            <div className="sh-metric">
              <span className="sh-metric-val">{fmt(health.total_clusters)}</span>
              <span className="sh-metric-label">Clusters</span>
            </div>
            <div className="sh-metric">
              <span className="sh-metric-val" style={{ color: namePct >= 80 ? '#4ec994' : namePct >= 50 ? '#dcdcaa' : '#f44747' }}>
                {namePct !== null ? `${namePct}%` : '—'}
              </span>
              <span className="sh-metric-label">Named</span>
            </div>
            <div className="sh-metric">
              <span className="sh-metric-val" style={{ color: anomCount > 0 ? '#f44747' : '#4ec994' }}>
                {fmt(anomCount || 0)}
              </span>
              <span className="sh-metric-label">Anomalies</span>
            </div>
            <div className="sh-metric">
              <span className="sh-metric-val">{fmt(health.fields_count)}</span>
              <span className="sh-metric-label">Fields</span>
            </div>
          </div>
        </div>
      )}
    </aside>
  )
}
