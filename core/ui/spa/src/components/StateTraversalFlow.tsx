import './StateTraversalFlow.css';

interface TraversalSegment {
  to: string;
  count: number;
  percent: number;
  colorIndex: number;
}

interface TraversalRow {
  id: string;
  label: string;
  visits: number;
  totalOutgoing: number;
  segments: TraversalSegment[];
  otherCount: number;
  isCurrent: boolean;
}

interface TopPath {
  from: string;
  to: string;
  count: number;
}

interface StateTraversalFlowProps {
  rows: TraversalRow[];
  topPaths: TopPath[];
  maxCount: number;
  totalEdges: number;
}

function StateTraversalFlow({ rows, topPaths, maxCount, totalEdges }: StateTraversalFlowProps) {
  if (rows.length === 0) {
    return (
      <div className="traversal-flow">
        <div className="traversal-flow-header">
          <div>
            <p className="eyebrow">Traversal Flow</p>
            <h3>Session pathing signals</h3>
            <p>No state transitions have been recorded yet.</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <section className="traversal-flow">
      <div className="traversal-flow-header">
        <div>
          <p className="eyebrow">Traversal Flow</p>
          <h3>Session pathing signals</h3>
          <p>See the most active state exits and the paths exercised most often.</p>
        </div>
        <div className="traversal-flow-meta">
          <div>
            <span>Transitions tracked</span>
            <strong>{totalEdges}</strong>
          </div>
          <div>
            <span>Max count</span>
            <strong>{maxCount}</strong>
          </div>
        </div>
      </div>
      <div className="traversal-flow-grid">
        <div className="traversal-rows">
          {rows.map((row) => (
            <div key={row.id} className={`traversal-row ${row.isCurrent ? 'current' : ''}`}>
              <div className="traversal-state">
                <span className="state-label">{row.label}</span>
                {row.isCurrent && <span className="state-pill">current</span>}
              </div>
              <div className="traversal-meta">
                <div>
                  <span>Visits</span>
                  <strong>{row.visits}</strong>
                </div>
                <div>
                  <span>Outgoing</span>
                  <strong>{row.totalOutgoing}</strong>
                </div>
              </div>
              <div className="traversal-bar-wrapper">
                <div className="traversal-bar">
                  {row.segments.map((segment) => (
                    <div
                      key={`${row.id}-${segment.to}`}
                      className={`traversal-segment color-${segment.colorIndex}`}
                      style={{ width: `${segment.percent}%` }}
                      title={`${segment.to}: ${segment.count}`}
                    />
                  ))}
                  {row.otherCount > 0 && (
                    <div
                      className="traversal-segment other"
                      style={{
                        width: `${(row.otherCount / row.totalOutgoing) * 100}%`,
                      }}
                      title={`Other: ${row.otherCount}`}
                    />
                  )}
                </div>
                <div className="traversal-tags">
                  {row.segments.map((segment) => (
                    <span key={`${row.id}-${segment.to}-tag`} className={`traversal-tag color-${segment.colorIndex}`}>
                      {segment.to}  |  {segment.count}
                    </span>
                  ))}
                  {row.otherCount > 0 && (
                    <span className="traversal-tag other">Other  |  {row.otherCount}</span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
        <div className="traversal-summary">
          <h4>Top Paths</h4>
          <ul>
            {topPaths.map((path) => (
              <li key={`${path.from}-${path.to}`}>
                <span>{path.from} {'->'} {path.to}</span>
                <strong>{path.count}</strong>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

export default StateTraversalFlow;
