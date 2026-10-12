import { useEffect, useState } from 'react'

type Health = {
  status: string
  service: string
  version: string
  database: string
  redis: string
}

type State =
  { kind: 'loading' } | { kind: 'ok'; health: Health } | { kind: 'unreachable' }

export default function ApiStatus() {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/health/', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json() as Promise<Health>
      })
      .then((health) => setState({ kind: 'ok', health }))
      .catch(() => {
        if (!controller.signal.aborted) setState({ kind: 'unreachable' })
      })
    return () => controller.abort()
  }, [])

  if (state.kind === 'loading') return <p>Checking API status…</p>
  if (state.kind === 'unreachable') {
    return (
      <p role="status" className="status status-error">
        API status: unreachable
      </p>
    )
  }
  const { health } = state
  return (
    <div role="status" className="status status-ok">
      <p>API status: {health.status}</p>
      <p>
        {health.service} v{health.version} · database {health.database} · redis{' '}
        {health.redis}
      </p>
    </div>
  )
}
