import { useState, useCallback, useEffect } from 'react'
import { useAppCtx } from '../context/AppContext.jsx'
import Filters from '../components/Filters.jsx'
import ClusterTable from '../components/ClusterTable.jsx'
import { useDebounce } from '../hooks/useDebounce.js'

const DEFAULT_FILTERS = {
  field_name: '', search: '', anomaly: '', named: '', min_size: 1, limit: 100, offset: 0,
}

export default function ClustersPage() {
  const { fields, refreshAll } = useAppCtx()
  const [filters,  setFilters]  = useState(DEFAULT_FILTERS)
  const [clusters, setClusters] = useState([])
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  const debouncedSearch = useDebounce(filters.search, 280)

  const fetchClusters = useCallback(async (f) => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (f.field_name) params.set('field_name', f.field_name)
      if (f.search)     params.set('search',     f.search)
      if (f.anomaly)    params.set('anomaly',     f.anomaly)
      if (f.named)      params.set('named',       f.named)
      if (f.min_size && f.min_size > 1) params.set('min_size', f.min_size)
      params.set('limit', f.limit)
      params.set('offset', f.offset)
      const res = await fetch(`/api/clusters?${params}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setClusters(await res.json())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchClusters({ ...filters, search: debouncedSearch })
  }, [filters.field_name, filters.anomaly, filters.named, filters.min_size, filters.limit, filters.offset, debouncedSearch])

  function handleChange(patch) {
    setFilters(prev => ({ ...prev, ...patch, offset: 0 }))
  }

  function handleRefresh() {
    refreshAll()
    fetchClusters({ ...filters, search: debouncedSearch })
  }

  return (
    <div className="page-wrap page-wrap--full">
      <div className="page-header">
        <h1 className="page-title">Cluster Explorer</h1>
      </div>

      <Filters
        filters={filters}
        fields={fields}
        onChange={handleChange}
        onRefresh={handleRefresh}
      />

      <ClusterTable clusters={clusters} loading={loading} error={error} />
    </div>
  )
}
