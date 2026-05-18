import { useState, useCallback, useEffect, useRef } from 'react'

export function useApi(initialUrl = null, initialParams = {}) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)
  const abortRef = useRef(null)

  const fetch_ = useCallback(async (url, params = {}) => {
    if (!url) return
    if (abortRef.current) abortRef.current.abort()
    abortRef.current = new AbortController()

    setLoading(true)
    setError(null)
    try {
      const qs = Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== null && v !== '')
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
        .join('&')
      const res = await window.fetch(qs ? `${url}?${qs}` : url, { signal: abortRef.current.signal })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.error || `HTTP ${res.status}`)
      }
      setData(await res.json())
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  // Auto-fetch on mount when initialUrl is provided
  useEffect(() => {
    if (initialUrl) fetch_(initialUrl, initialParams)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { data, loading, error, fetch: fetch_, setData }
}

// Convenience wrapper for a single GET endpoint with params
export function useFetch(url, params = {}, deps = []) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    if (!url) return
    const ctl = new AbortController()
    setLoading(true)
    setError(null)
    const qs = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join('&')
    window.fetch(qs ? `${url}?${qs}` : url, { signal: ctl.signal })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setData)
      .catch(err => { if (err.name !== 'AbortError') setError(err.message) })
      .finally(() => setLoading(false))
    return () => ctl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, ...deps])

  return { data, loading, error }
}
