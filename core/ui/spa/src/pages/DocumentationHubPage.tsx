import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import Modal from '../components/Modal';
import { api } from '../services/api';
import './DocumentationHubPage.css';

interface InternalGuide {
  title: string;
  description: string;
  to: string;
}

interface RepoDoc {
  title: string;
  description: string;
  path: string;
}

interface DocContent {
  path: string;
  content: string;
  title: string | null;
}

type SectionFilter = 'all' | 'interactive' | 'repository' | 'developer';

const interactiveGuides: InternalGuide[] = [
  {
    title: 'Getting Started',
    description: 'Bootstrap the orchestrator, agent, and sample target in a few minutes.',
    to: '/guides/getting-started',
  },
  {
    title: 'Fuzzing Campaigns',
    description: 'Understand scheduling knobs, telemetry, and how to keep agents healthy.',
    to: '/guides/fuzzing',
  },
  {
    title: 'Mutation Strategies',
    description: 'Experiment with bitflips, arithmetic tweaks, and dictionary assists.',
    to: '/guides/mutation',
  },
  {
    title: 'Protocol Overview',
    description: 'Inspect protocol definitions and state machines exposed to the UI.',
    to: '/guides/protocol',
  },
  {
    title: 'Authoring Plugins',
    description: 'Model declarative fields, attach behaviors, and publish new surfaces.',
    to: '/guides/protocol-authoring',
  },
];

const repositoryDocs: RepoDoc[] = [
  {
    title: 'Documentation Index',
    description: 'Single landing page linking every README, guide, and developer note.',
    path: 'docs/README.md',
  },
  {
    title: 'Quickstart',
    description: 'Run the stack via Docker or local tooling with copy/paste commands.',
    path: 'docs/QUICKSTART.md',
  },
  {
    title: 'User Guide',
    description: 'End-to-end usage workflow, UI walkthroughs, and troubleshooting tips.',
    path: 'docs/USER_GUIDE.md',
  },
  {
    title: 'Protocol Plugin Guide',
    description: 'Create, test, and validate protocol plugins with real targets.',
    path: 'docs/PROTOCOL_PLUGIN_GUIDE.md',
  },
  {
    title: 'Orchestrated Sessions',
    description: 'Multi-protocol orchestration, heartbeats, and session context.',
    path: 'docs/ORCHESTRATED_SESSIONS_GUIDE.md',
  },
  {
    title: 'Mutation Strategies',
    description: 'Mutation algorithms, strengths, and coverage tradeoffs.',
    path: 'docs/MUTATION_STRATEGIES.md',
  },
  {
    title: 'State Coverage Guide',
    description: 'State graph metrics, coverage signals, and debugging tips.',
    path: 'docs/STATE_COVERAGE_GUIDE.md',
  },
  {
    title: 'Template Quick Reference',
    description: 'Protocol template snippets, helper patterns, and field cheat sheets.',
    path: 'docs/TEMPLATE_QUICK_REFERENCE.md',
  },
  {
    title: 'Protocol Server Templates',
    description: 'Reference servers and harness patterns for quick target bring-up.',
    path: 'docs/PROTOCOL_SERVER_TEMPLATES.md',
  },
  {
    title: 'Changelog',
    description: 'Record of all changes, bug fixes, and new features.',
    path: 'CHANGELOG.md',
  },
];

const developerReferences: RepoDoc[] = [
  {
    title: 'Architecture Overview',
    description: 'Layer-by-layer breakdown of the orchestrator, engine, and plugins.',
    path: 'docs/developer/01_architectural_overview.md',
  },
  {
    title: 'Mutation Engine',
    description: 'How seed corpora feed the mutation engine and scheduling loop.',
    path: 'docs/developer/02_mutation_engine.md',
  },
  {
    title: 'Stateful Fuzzing',
    description: 'Tips for state tracking, transitions, and replayable flows.',
    path: 'docs/developer/03_stateful_fuzzing.md',
  },
  {
    title: 'Data Management',
    description: 'Corpus storage, finding lifecycles, and data retention practices.',
    path: 'docs/developer/04_data_management.md',
  },
  {
    title: 'Agent & Core Communication',
    description: 'Distributed execution, agent telemetry, and crash artifact handling.',
    path: 'docs/developer/05_agent_and_core_communication.md',
  },
  {
    title: 'First Debug Session',
    description: 'Walkthrough of a debugging session with core logs and replay.',
    path: 'docs/developer/06_first_debug_session.md',
  },
  {
    title: 'Orchestration Architecture',
    description: 'Deep dive into multi-protocol support and session context.',
    path: 'docs/developer/ORCHESTRATED_SESSIONS_ARCHITECTURE.md',
  },
];

const DocumentationHubPage = () => {
  const [activeFilter, setActiveFilter] = useState<SectionFilter>('all');
  const [selectedDoc, setSelectedDoc] = useState<RepoDoc | null>(null);
  const [docContent, setDocContent] = useState<DocContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filterOptions = useMemo(
    () => [
      { label: 'All content', value: 'all' as SectionFilter },
      { label: 'Interactive guides', value: 'interactive' as SectionFilter },
      { label: 'Repository docs', value: 'repository' as SectionFilter },
      { label: 'Deep dives', value: 'developer' as SectionFilter },
    ],
    [],
  );

  const shouldShow = (section: SectionFilter) =>
    activeFilter === 'all' || activeFilter === section;

  const fetchDoc = useCallback(async (doc: RepoDoc) => {
    setSelectedDoc(doc);
    setLoading(true);
    setError(null);
    try {
      const response = await api<DocContent>(`/api/docs/${doc.path}`);
      setDocContent(response);
    } catch (err) {
      setError((err as Error).message);
      setDocContent(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const closeModal = useCallback(() => {
    setSelectedDoc(null);
    setDocContent(null);
    setError(null);
  }, []);

  // Handle keyboard escape
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && selectedDoc) {
        closeModal();
      }
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [selectedDoc, closeModal]);

  const renderDocCard = (doc: RepoDoc, type: 'repo' | 'deep') => (
    <article key={doc.title} className="docs-card">
      <p className={`docs-card-eyebrow ${type}`}>
        {type === 'repo' ? 'Repository' : 'Developer'}
      </p>
      <h3>{doc.title}</h3>
      <p>{doc.description}</p>
      <button
        type="button"
        className="docs-card-link"
        onClick={() => fetchDoc(doc)}
      >
        Read documentation
      </button>
    </article>
  );

  return (
    <div className="docs-hub">
      <header className="docs-hub-header">
        <p className="eyebrow">Documentation</p>
        <h1>Explore the Knowledge Base</h1>
        <p>
          Browse in-app guides or review the bundled references without leaving the console. Use the
          controls to focus on the content type you need—every card stays in-place so you can scan
          quickly.
        </p>

        <div className="docs-controls">
          <div className="filter-group" role="group" aria-label="Filter documentation sections">
            {filterOptions.map((option) => (
              <button
                key={option.value}
                className={`filter-pill ${activeFilter === option.value ? 'active' : ''}`}
                type="button"
                onClick={() => setActiveFilter(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="legend">
            <span className="legend-item">
              <span className="legend-dot inapp" />
              In-app guide
            </span>
            <span className="legend-item">
              <span className="legend-dot repo" />
              Repo reference
            </span>
            <span className="legend-item">
              <span className="legend-dot deep" />
              Deep dive
            </span>
          </div>
        </div>
      </header>

      {shouldShow('interactive') && (
        <section>
          <div className="docs-hub-section-header">
            <h2>Interactive Guides</h2>
            <p>Delivered inside the console with context-aware walkthroughs.</p>
          </div>
          <div className="docs-grid">
            {interactiveGuides.map((guide) => (
              <article key={guide.title} className="docs-card">
                <p className="docs-card-eyebrow inapp">In-app</p>
                <h3>{guide.title}</h3>
                <p>{guide.description}</p>
                <Link className="docs-card-link" to={guide.to}>
                  Open guide
                </Link>
              </article>
            ))}
          </div>
        </section>
      )}

      {shouldShow('repository') && (
        <section>
          <div className="docs-hub-section-header">
            <h2>Repository Docs</h2>
            <p>Markdown references bundled with the source tree.</p>
          </div>
          <div className="docs-grid">
            {repositoryDocs.map((doc) => renderDocCard(doc, 'repo'))}
          </div>
        </section>
      )}

      {shouldShow('developer') && (
        <section>
          <div className="docs-hub-section-header">
            <h2>Deep Dives</h2>
            <p>Developer notes covering the internals of the fuzzer runtime.</p>
          </div>
          <div className="docs-grid">
            {developerReferences.map((doc) => renderDocCard(doc, 'deep'))}
          </div>
        </section>
      )}

      {/* Documentation Modal */}
      <Modal
        open={Boolean(selectedDoc)}
        onClose={closeModal}
        title={docContent?.title || selectedDoc?.title || 'Documentation'}
        className="modal-wide docs-modal"
      >
        <div className="docs-modal-content">
          {loading && <p className="docs-loading">Loading documentation...</p>}
          {error && <p className="docs-error">Failed to load: {error}</p>}
          {docContent && !loading && (
            <div className="markdown-body">
              <ReactMarkdown>{docContent.content}</ReactMarkdown>
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
};

export default DocumentationHubPage;
