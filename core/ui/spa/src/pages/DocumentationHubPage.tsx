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
    path: 'QUICKSTART.md',
  },
  {
    title: 'Fuzzing Guide',
    description: 'Campaign planning, corpus hygiene, and recovery checklists.',
    path: 'docs/FUZZING_GUIDE.md',
  },
  {
    title: 'Protocol Testing',
    description: 'Step-by-step instructions for exercising plugins and validating blocks.',
    path: 'docs/PROTOCOL_TESTING.md',
  },
  {
    title: 'OpenAPI Explorer',
    description: 'Interactive API docs generated from the FastAPI schema (Swagger UI).',
    path: 'docs/',
  },
];

const developerReferences: RepoDoc[] = [
  {
    title: 'Architecture Overview',
    description: 'Layer-by-layer breakdown of the orchestrator, engine, and plugins.',
    path: 'docs/developer/01_overview.md',
  },
  {
    title: 'Test Case Generation',
    description: 'How seed corpora feed the mutation engine and scheduling loop.',
    path: 'docs/developer/02_test_case_generation_and_mutation.md',
  },
  {
    title: 'Protocol Parsing & Plugins',
    description: 'Tips for capturing grammars, declarative behaviors, and validators.',
    path: 'docs/developer/03_protocol_parsing_and_plugins.md',
  },
  {
    title: 'Stateful Fuzzing',
    description: 'Details on state walkers, transitions, and replay debugging.',
    path: 'docs/developer/04_stateful_fuzzing.md',
  },
  {
    title: 'Corpus & Agents',
    description: 'Distributed execution, agent telemetry, and crash artifact handling.',
    path: 'docs/developer/05_corpus_and_agents.md',
  },
  {
    title: 'Advanced Logic',
    description: 'Automatic sizing, response handling, and declarative operations.',
    path: 'docs/developer/06_advanced_logic.md',
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
          controls to focus on the content type you need—every card stays in-place so you can scan
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
                  Open guide ↗
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
