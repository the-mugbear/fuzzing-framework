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
  href: string;
}

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
    href: '/docs/README.md',
  },
  {
    title: 'Project README',
    description: 'High-level architecture, execution modes, and key repository paths.',
    href: '/README.md',
  },
  {
    title: 'Quickstart',
    description: 'Run the stack via Docker or local tooling with copy/paste commands.',
    href: '/QUICKSTART.md',
  },
  {
    title: 'Fuzzing Guide',
    description: 'Campaign planning, corpus hygiene, and recovery checklists.',
    href: '/docs/FUZZING_GUIDE.md',
  },
  {
    title: 'Protocol Testing',
    description: 'Step-by-step instructions for exercising plugins and validating blocks.',
    href: '/docs/PROTOCOL_TESTING.md',
  },
  {
    title: 'OpenAPI Explorer',
    description: 'Interactive API docs generated from the FastAPI schema (Swagger UI).',
    href: '/docs',
  },
];

const developerReferences: RepoDoc[] = [
  {
    title: 'Architecture Overview',
    description: 'Layer-by-layer breakdown of the orchestrator, engine, and plugins.',
    href: '/docs/developer/01_overview.md',
  },
  {
    title: 'Test Case Generation',
    description: 'How seed corpora feed the mutation engine and scheduling loop.',
    href: '/docs/developer/02_test_case_generation_and_mutation.md',
  },
  {
    title: 'Protocol Parsing & Plugins',
    description: 'Tips for capturing grammars, declarative behaviors, and validators.',
    href: '/docs/developer/03_protocol_parsing_and_plugins.md',
  },
  {
    title: 'Stateful Fuzzing',
    description: 'Details on state walkers, transitions, and replay debugging.',
    href: '/docs/developer/04_stateful_fuzzing.md',
  },
  {
    title: 'Corpus & Agents',
    description: 'Distributed execution, agent telemetry, and crash artifact handling.',
    href: '/docs/developer/05_corpus_and_agents.md',
  },
  {
    title: 'Advanced Logic',
    description: 'Automatic sizing, response handling, and declarative operations.',
    href: '/docs/developer/06_advanced_logic.md',
  },
];

const DocumentationHubPage = () => {
  return (
    <div className="docs-hub">
      <header className="docs-hub-header">
        <p className="eyebrow">Documentation</p>
        <h1>Explore the Knowledge Base</h1>
        <p>
          Browse in-app guides for quick answers or jump to the Markdown sources that ship with the
          repository. Everything below opens in a new tab so you can keep your current workflow in
          place.
        </p>
      </header>

      <section>
        <div className="docs-hub-section-header">
          <h2>Interactive Guides</h2>
          <p>Delivered inside the console with context-aware walkthroughs.</p>
        </div>
        <div className="docs-grid">
          {interactiveGuides.map((guide) => (
            <article key={guide.title} className="docs-card">
              <p className="docs-card-eyebrow">In-app</p>
              <h3>{guide.title}</h3>
              <p>{guide.description}</p>
              <Link className="docs-card-link" to={guide.to}>
                Open guide ↗
              </Link>
            </article>
          ))}
        </div>
      </section>

      <section>
        <div className="docs-hub-section-header">
          <h2>Repository Docs</h2>
          <p>Markdown references bundled with the source tree.</p>
        </div>
        <div className="docs-grid">
          {repositoryDocs.map((doc) => (
            <article key={doc.title} className="docs-card">
              <p className="docs-card-eyebrow">Markdown</p>
              <h3>{doc.title}</h3>
              <p>{doc.description}</p>
              <a className="docs-card-link" href={doc.href} target="_blank" rel="noreferrer">
                Open document ↗
              </a>
            </article>
          ))}
        </div>
      </section>

      <section>
        <div className="docs-hub-section-header">
          <h2>Deep Dives</h2>
          <p>Developer notes covering the internals of the fuzzer runtime.</p>
        </div>
        <div className="docs-grid">
          {developerReferences.map((doc) => (
            <article key={doc.title} className="docs-card">
              <p className="docs-card-eyebrow">Developer</p>
              <h3>{doc.title}</h3>
              <p>{doc.description}</p>
              <a className="docs-card-link" href={doc.href} target="_blank" rel="noreferrer">
                Open document ↗
              </a>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
};

export default DocumentationHubPage;
