import { useEffect, useState } from 'react'
import { Route, Routes } from 'react-router-dom'
import { setApiKey } from './api/client'
import Layout from './components/Layout'
import Overview from './pages/Overview'
import IncidentPage from './pages/Incident'
import InvestigationPage from './pages/Investigation'
import RemediationPage from './pages/Remediation'
import { Empty } from './components/Common'

function KeyPrompt({ onDone }: { onDone: () => void }) {
  const [key, setKey] = useState('')
  return (
    <div role="dialog" aria-modal="true" aria-label="API key required"
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', display: 'grid', placeItems: 'center', zIndex: 50 }}>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          setApiKey(key.trim())
          onDone()
        }}
        style={{ background: 'var(--panel, #161b22)', padding: 24, borderRadius: 8, width: 380, display: 'grid', gap: 12 }}
      >
        <strong>API key required</strong>
        <span style={{ opacity: 0.8, fontSize: 13 }}>
          This TraceMind server needs a key (TRACEMIND_API_KEY). It is kept in this tab's session storage only.
        </span>
        <input type="password" autoFocus value={key} onChange={(e) => setKey(e.target.value)} aria-label="API key" />
        <button type="submit" disabled={!key.trim()}>Continue</button>
      </form>
    </div>
  )
}

export default function App() {
  const [needKey, setNeedKey] = useState(false)
  useEffect(() => {
    const h = () => setNeedKey(true)
    window.addEventListener('tm-unauthorized', h)
    return () => window.removeEventListener('tm-unauthorized', h)
  }, [])
  return (
    <Layout>
      {needKey && <KeyPrompt onDone={() => window.location.reload()} />}
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/incidents/:id" element={<IncidentPage />} />
        <Route path="/investigations/:id" element={<InvestigationPage />} />
        <Route path="/remediations/:id" element={<RemediationPage />} />
        <Route path="*" element={<Empty title="Page not found" hint="That route does not exist." />} />
      </Routes>
    </Layout>
  )
}
