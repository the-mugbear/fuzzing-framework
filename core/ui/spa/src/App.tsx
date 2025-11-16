import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import DashboardPage from './pages/DashboardPage';
import PluginDebuggerPage from './pages/PluginDebuggerPage';
import PacketParserPage from './pages/PacketParserPage';
import MutationWorkbenchPage from './pages/MutationWorkbenchPage';
import StateWalkerPage from './pages/StateWalkerPage';
import OneOffTestPage from './pages/OneOffTestPage';
import CorrelationPage from './pages/CorrelationPage';
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
        <Route path="/" element={<Layout />}>
          <Route index element={<DashboardPage />} />
          <Route path="plugin-debug" element={<PluginDebuggerPage />} />
          <Route path="packet-parser" element={<PacketParserPage />} />
          <Route path="mutation-workbench" element={<MutationWorkbenchPage />} />
          <Route path="state-walker" element={<StateWalkerPage />} />
          <Route path="one-off" element={<OneOffTestPage />} />
          <Route path="correlation" element={<CorrelationPage />} />
          <Route path="guides" element={<DocumentationHubPage />} />
          <Route path="guides/getting-started" element={<GettingStartedGuide />} />
          <Route path="guides/fuzzing" element={<FuzzingGuide />} />
          <Route path="guides/mutation" element={<MutationGuide />} />
          <Route path="guides/protocol-authoring" element={<ProtocolAuthoringGuide />} />
          <Route path="guides/protocol" element={<ProtocolGuide />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
