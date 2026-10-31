import { useCallback, useEffect, useRef, useState } from 'react'
import { errMsg } from './util'

export interface Async<T> {
  data: T | null
  error: string | null
  loading: boolean
  reload: () => void
}

/** Fetch with optional polling. Polling stops when `done(data)` is true. */
export function useFetch<T>(fn: () => Promise<T>, deps: unknown[], opts?: { poll?: number; done?: (d: T) => boolean }): Async<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  const fnRef = useRef(fn)
  fnRef.current = fn
  const optsRef = useRef(opts)
  optsRef.current = opts

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    const run = async (first: boolean) => {
      if (first) setLoading(true)
      try {
        const d = await fnRef.current()
        if (cancelled) return
        setData(d)
        setError(null)
        const o = optsRef.current
        if (o?.poll && !(o.done && o.done(d))) timer = window.setTimeout(() => run(false), o.poll)
      } catch (e) {
        if (cancelled) return
        setError(errMsg(e))
        const o = optsRef.current
        if (o?.poll && !first) timer = window.setTimeout(() => run(false), o.poll * 2)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    run(true)
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, error, loading, reload }
}

/** Wraps an async action with pending/error state. */
export function useAction<A extends unknown[], R>(fn: (...a: A) => Promise<R>) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = useCallback(async (...a: A): Promise<R | undefined> => {
    setPending(true)
    setError(null)
    try {
      return await fn(...a)
    } catch (e) {
      setError(errMsg(e))
      return undefined
    } finally {
      setPending(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fn])
  return { run, pending, error }
}
