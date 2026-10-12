import ApiStatus from './ApiStatus'

export default function App() {
  return (
    <main
      style={{ fontFamily: 'system-ui, sans-serif', maxWidth: 640, margin: '4rem auto' }}
    >
      <h1>TrendPilot AI</h1>
      <p>Forecasting and anomaly detection for small businesses.</p>
      <ApiStatus />
    </main>
  )
}
