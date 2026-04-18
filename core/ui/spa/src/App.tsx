import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import DashboardPage from './pages/DashboardPage';
import LogViewerPage from './pages/LogViewerPage';
import ProtocolEditorPage from './pages/ProtocolEditorPage';
import PacketWorkshopPage from './pages/PacketWorkshopPage';
import StateExplorerPage from './pages/StateExplorerPage';
import FindingsPage from './pages/FindingsPage';
import CorrelationPage from './pages/CorrelationPage';
import TargetsPage from './pages/TargetsPage';
import SystemLogsPage from './pages/SystemLogsPage';
import GettingStartedGuide from './pages/GettingStartedGuide';
import FuzzingGuide from './pages/FuzzingGuide';
import MutationGuide from './pages/MutationGuide';
import ProtocolAuthoringGuide from './pages/ProtocolAuthoringGuide';
import ProtocolGuide from './pages/ProtocolGuide';
import DocumentationHubPage from './pages/DocumentationHubPage';

function App() {
  return (
    <BrowserRouter basename="/ui">
      <Routes>
        {/* Standalone page — no sidebar, opens in own tab */}
        <Route path="/logs/:targetId" element={<LogViewerPage />} />

        <Route path="/" element={<Layout />}>
          {/* Campaigns */}
          <Route index element={<DashboardPage />} />
          <Route path="targets" element={<TargetsPage />} />
          <Route path="findings" element={<FindingsPage />} />

          {/* Protocol Lab */}
          <Route path="protocol-editor" element={<ProtocolEditorPage />} />
          <Route path="packet-workshop" element={<PacketWorkshopPage />} />
          <Route path="state-explorer" element={<StateExplorerPage />} />

          {/* System */}
          <Route path="correlation" element={<CorrelationPage />} />
          <Route path="system-logs" element={<SystemLogsPage />} />

          {/* Docs */}
          <Route path="guides" element={<DocumentationHubPage />} />
          <Route path="guides/getting-started" element={<GettingStartedGuide />} />
          <Route path="guides/fuzzing" element={<FuzzingGuide />} />
          <Route path="guides/mutation" element={<MutationGuide />} />
          <Route path="guides/protocol-authoring" element={<ProtocolAuthoringGuide />} />
          <Route path="guides/protocol" element={<ProtocolGuide />} />

          {/* Legacy redirects */}
          <Route path="protocol-studio" element={<Navigate to="/protocol-editor" replace />} />
          <Route path="plugin-debug" element={<Navigate to="/protocol-editor" replace />} />
          <Route path="packet-parser" element={<Navigate to="/packet-workshop" replace />} />
          <Route path="one-off" element={<Navigate to="/packet-workshop" replace />} />
          <Route path="mutation-workbench" element={<Navigate to="/packet-workshop" replace />} />
          <Route path="state-walker" element={<Navigate to="/state-explorer" replace />} />
          <Route path="state-graph" element={<Navigate to="/state-explorer" replace />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
