import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ApiStatus from './ApiStatus'

const healthy = {
  status: 'ok',
  service: 'trendpilot-api',
  version: '0.1.0',
  database: 'ok',
  redis: 'ok',
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ApiStatus', () => {
  it('shows a loading state before the request resolves', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )
    render(<ApiStatus />)
    expect(screen.getByText(/checking/i)).toBeInTheDocument()
  })

  it('renders the ok state with service details', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => healthy }),
    )
    render(<ApiStatus />)
    expect(await screen.findByText('API status: ok')).toBeInTheDocument()
    expect(screen.getByText(/trendpilot-api/)).toBeInTheDocument()
    expect(screen.getByText(/v0\.1\.0/)).toBeInTheDocument()
  })

  it('renders the unreachable state when fetch rejects', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    render(<ApiStatus />)
    expect(await screen.findByText('API status: unreachable')).toBeInTheDocument()
  })

  it('renders the unreachable state on a non-2xx response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) }),
    )
    render(<ApiStatus />)
    expect(await screen.findByText('API status: unreachable')).toBeInTheDocument()
  })

  it('calls the health endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => healthy })
    vi.stubGlobal('fetch', fetchMock)
    render(<ApiStatus />)
    await screen.findByText('API status: ok')
    expect(fetchMock).toHaveBeenCalledWith('/api/health/', expect.anything())
  })
})
