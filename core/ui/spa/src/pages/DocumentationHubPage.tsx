import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
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
    title: 'Project README',
    description: 'High-level architecture, execution modes, and key repository paths.',
    path: 'README.md',
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
];

const DocumentationHubPage = () => {
  const [activeFilter, setActiveFilter] = useState<SectionFilter>('all');

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

  return (
    <div className="docs-hub">
      <header className="docs-hub-header">
        <p className="eyebrow">Documentation</p>
        <h1>Explore the Knowledge Base</h1>
        <p>
          Browse in-app guides or review the bundled references without leaving the console. Use the
          controls to focus on the content type you need-every card stays in-place so you can scan
          quickly without bouncing to raw Markdown.
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
            {repositoryDocs.map((doc) => (
              <article key={doc.title} className="docs-card">
                <p className="docs-card-eyebrow repo">Repository</p>
                <h3>{doc.title}</h3>
                <p>{doc.description}</p>
                <div className="docs-card-path">
                  <span>Path: </span>
                  <code>{doc.path}</code>
                </div>
              </article>
            ))}
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
            {developerReferences.map((doc) => (
              <article key={doc.title} className="docs-card">
                <p className="docs-card-eyebrow deep">Developer</p>
                <h3>{doc.title}</h3>
                <p>{doc.description}</p>
                <div className="docs-card-path">
                  <span>Path: </span>
                  <code>{doc.path}</code>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
};

export default DocumentationHubPage;
