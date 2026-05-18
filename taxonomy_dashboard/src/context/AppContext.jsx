import { createContext, useContext, useState, useCallback, useEffect } from 'react'

const AppContext = createContext(null)

export function useAppCtx() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useAppCtx must be used inside AppProvider')
  return ctx
}

export function AppProvider({ children }) {
  const [activePage,         setActivePage]         = useState('overview')
  const [selectedClusterId,  setSelectedClusterId]  = useState(null)
  const [searchOpen,         setSearchOpen]         = useState(false)
  const [fields,             setFields]             = useState([])
  const [health,             setHealth]             = useState(null)

  const fetchHealth = useCallback(async () => {
    try {
      const res = await fetch('/api/health')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setHealth(await res.json())
    } catch (err) {
      console.error('health fetch:', err.message)
    }
  }, [])

  const fetchFields = useCallback(async () => {
    try {
      const res = await fetch('/api/fields')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setFields(await res.json())
    } catch (err) {
      console.error('fields fetch:', err.message)
    }
  }, [])

  useEffect(() => {
    fetchHealth()
    fetchFields()
  }, [fetchHealth, fetchFields])

  // Global keyboard shortcut: Cmd/Ctrl + K → open search
  useEffect(() => {
    function onKeyDown(e) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setSearchOpen(prev => !prev)
      }
      if (e.key === 'Escape') {
        setSearchOpen(false)
        setSelectedClusterId(null)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  function navigate(page) {
    setActivePage(page)
    setSelectedClusterId(null)
  }

  const value = {
    activePage, navigate,
    selectedClusterId, setSelectedClusterId,
    searchOpen, setSearchOpen,
    fields, health,
    refreshAll: () => { fetchHealth(); fetchFields() },
  }

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}
