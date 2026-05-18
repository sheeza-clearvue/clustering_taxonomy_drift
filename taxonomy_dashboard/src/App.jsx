import { lazy, Suspense } from 'react'
import { AnimatePresence } from 'framer-motion'
import { AppProvider, useAppCtx } from './context/AppContext.jsx'
import Sidebar from './components/Sidebar.jsx'
import GlobalSearch from './components/GlobalSearch.jsx'
import ClusterDetailPanel from './components/ClusterDetailPanel.jsx'

const OverviewPage      = lazy(() => import('./pages/OverviewPage.jsx'))
const ClustersPage      = lazy(() => import('./pages/ClustersPage.jsx'))
const SemanticSpacePage = lazy(() => import('./pages/SemanticSpacePage.jsx'))
const AnomaliesPage     = lazy(() => import('./pages/AnomaliesPage.jsx'))
const DriftPage         = lazy(() => import('./pages/DriftPage.jsx'))

function PageSuspense({ children }) {
  return (
    <Suspense fallback={<div className="page-loading">Loading…</div>}>
      {children}
    </Suspense>
  )
}

function AppShell() {
  const { activePage, selectedClusterId, searchOpen } = useAppCtx()

  return (
    <div className="app-layout">
      <Sidebar />

      <div className="app-body">
        <main className="main-content">
          <PageSuspense>
            {activePage === 'overview'       && <OverviewPage />}
            {activePage === 'clusters'       && <ClustersPage />}
            {activePage === 'semantic-space' && <SemanticSpacePage />}
            {activePage === 'anomalies'      && <AnomaliesPage />}
            {activePage === 'drift'          && <DriftPage />}
          </PageSuspense>
        </main>

        <AnimatePresence>
          {selectedClusterId && <ClusterDetailPanel key="detail" clusterId={selectedClusterId} />}
        </AnimatePresence>
      </div>

      <AnimatePresence>
        {searchOpen && <GlobalSearch key="search" />}
      </AnimatePresence>
    </div>
  )
}

export default function App() {
  return (
    <AppProvider>
      <AppShell />
    </AppProvider>
  )
}
