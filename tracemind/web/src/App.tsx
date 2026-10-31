import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Overview from './pages/Overview'
import IncidentPage from './pages/Incident'
import InvestigationPage from './pages/Investigation'
import RemediationPage from './pages/Remediation'
import { Empty } from './components/Common'

export default function App() {
  return (
    <Layout>
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
