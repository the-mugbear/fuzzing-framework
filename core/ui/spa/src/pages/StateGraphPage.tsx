import { useEffect, useState, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../services/api';
import StateCoverageTable from '../components/StateCoverageTable';
import StateTraversalFlow from '../components/StateTraversalFlow';
import './StateGraphPage.css';

interface Node {
  id: string;
  label: string;
  title: string;
  value: number;
  color: string;
  group: string;
  visits: number;
}

interface Edge {
  id: string;
  from: string;
  to: string;
  label: string;
  title: string;
  value: number;
  color: string;
  width: number;
  dashes: boolean;
  arrows: string;
}

interface GraphData {
  session_id: string;
  protocol: string;
  current_state: string | null;
  nodes: Node[];
  edges: Edge[];
  statistics: {
    total_states: number;
    visited_states: number;
    state_coverage_pct: number;
    total_transitions: number;
    taken_transitions: number;
    transition_coverage_pct: number;
    total_tests: number;
  };
}

function StateGraphPage() {
  const [searchParams] = useSearchParams();
  const sessionId = searchParams.get('session');
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const loadGraphData = async () => {
    if (!sessionId) {
      setError('No session ID provided');
      setLoading(false);
      return;
    }

    try {
      setIsRefreshing(true);
      const data = await api<GraphData>(`/api/sessions/${sessionId}/state_graph`);
      setGraphData(data);
      setError(null);
      setLastUpdated(new Date());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    loadGraphData();

    if (autoRefresh) {
      const interval = setInterval(loadGraphData, 5000);
      return () => clearInterval(interval);
    }
  }, [sessionId, autoRefresh]);

  // Prepare data for StateCoverageTable
  const stateTableData = useMemo(() => {
    if (!graphData) return [];

    // Build transition counts for each state
    const transitionCounts: Record<string, { total: number; taken: number }> = {};
    graphData.nodes.forEach(node => {
      transitionCounts[node.id] = { total: 0, taken: 0 };
    });

    graphData.edges.forEach(edge => {
      if (transitionCounts[edge.from]) {
        transitionCounts[edge.from].total++;
        if (!edge.dashes) {
          transitionCounts[edge.from].taken++;
        }
      }
    });

    return graphData.nodes.map(node => ({
      id: node.id,
      label: node.label,
      visits: node.visits,
      group: node.group,
      transitions_out: transitionCounts[node.id]?.total || 0,
      transitions_taken: transitionCounts[node.id]?.taken || 0,
      last_seen: node.visits > 0 ? 'Recently' : undefined
    }));
  }, [graphData]);

  const traversalFlowData = useMemo(() => {
    if (!graphData) {
      return { rows: [], topPaths: [], maxCount: 1, totalEdges: 0 };
    }

    const takenEdges = graphData.edges
      .filter(edge => !edge.dashes)
      .map(edge => ({
        from: edge.from,
        to: edge.to,
        count: edge.value || 0
      }))
      .filter(edge => edge.count > 0);

    const grouped = new Map<string, { from: string; to: string; count: number }[]>();
    takenEdges.forEach(edge => {
      if (!grouped.has(edge.from)) {
        grouped.set(edge.from, []);
      }
      grouped.get(edge.from)!.push(edge);
    });

    const rows = graphData.nodes
      .map(node => {
        const outgoing = grouped.get(node.id) || [];
        const totalOutgoing = outgoing.reduce((sum, edge) => sum + edge.count, 0);
        const sorted = [...outgoing].sort((a, b) => b.count - a.count);
        const topSegments = sorted.slice(0, 3);
        const topCount = topSegments.reduce((sum, edge) => sum + edge.count, 0);
        const otherCount = Math.max(0, totalOutgoing - topCount);

        return {
          id: node.id,
          label: node.label || node.id,
          visits: node.visits,
          totalOutgoing,
          segments: topSegments.map((edge, index) => ({
            to: edge.to,
            count: edge.count,
            percent: totalOutgoing ? (edge.count / totalOutgoing) * 100 : 0,
            colorIndex: index
          })),
          otherCount,
          isCurrent: node.id === graphData.current_state
        };
      })
      .filter(row => row.totalOutgoing > 0);

    const topPaths = [...takenEdges]
      .sort((a, b) => b.count - a.count)
      .slice(0, 6);

    const maxCount = Math.max(1, ...takenEdges.map(edge => edge.count));

    return { rows, topPaths, maxCount, totalEdges: takenEdges.length };
  }, [graphData]);

  const journeyData = useMemo(() => {
    if (!graphData) {
      return { cards: [], transitions: [] as Edge[] };
    }

    const takenEdges = graphData.edges.filter(edge => !edge.dashes && (edge.value || 0) > 0);

    const cards = graphData.nodes
      .map(node => {
        const outgoing = takenEdges.filter(edge => edge.from === node.id);
        const totalOutgoing = outgoing.reduce((sum, edge) => sum + (edge.value || 0), 0);
        const topOutgoing = [...outgoing]
          .sort((a, b) => (b.value || 0) - (a.value || 0))
          .slice(0, 3);

        return {
          id: node.id,
          label: node.label || node.id,
          visits: node.visits,
          totalOutgoing,
          topOutgoing,
          isCurrent: node.id === graphData.current_state
        };
      })
      .sort((a, b) => b.visits - a.visits);

    const transitions = [...takenEdges]
      .sort((a, b) => (b.value || 0) - (a.value || 0))
      .slice(0, 12);

    return { cards, transitions };
  }, [graphData]);

  if (!sessionId) {
    return (
      <div className="state-graph-page">
        <div className="error-message">No session ID provided. Please select a session.</div>
      </div>
    );
  }

  if (loading && !graphData) {
    return (
      <div className="state-graph-page">
        <div className="loading-message">Loading state graph...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="state-graph-page">
        <div className="error-message">
          Error loading state graph: {error}
          <button onClick={loadGraphData} style={{ marginLeft: '1rem' }}>Retry</button>
        </div>
      </div>
    );
  }

  if (!graphData) {
    return null;
  }

  return (
    <div className="state-graph-page">
      <div className="graph-header">
        <div className="graph-title">
          <p className="eyebrow">Stateful fuzzing</p>
          <h1>State Machine Visualization</h1>
          <div className="graph-subtitle-row">
            <p className="graph-subtitle">
              Session {graphData.session_id.slice(0, 8)}... · Protocol {graphData.protocol}
            </p>
            <div className="status-chips">
              <span className={`status-pill ${isRefreshing ? 'live' : ''}`}>
                {isRefreshing ? 'Refreshing…' : 'Synced'}
                {lastUpdated ? ` · ${lastUpdated.toLocaleTimeString()}` : ''}
              </span>
            </div>
          </div>
        </div>
        <div className="graph-controls">
          <div className="toggle-row">
            <label className="auto-refresh-toggle">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              Auto-refresh (5s)
            </label>
          </div>
          <div className="control-buttons">
            <button onClick={loadGraphData} className="refresh-btn" disabled={isRefreshing}>
              {isRefreshing ? 'Refreshing…' : 'Refresh Now'}
            </button>
          </div>
        </div>
      </div>

      <div className="graph-stats">
        <div className="stat-card">
          <div className="stat-label">State Coverage</div>
          <div className="stat-value">
            {graphData.statistics.visited_states} / {graphData.statistics.total_states}
          </div>
          <div className="stat-pct">{graphData.statistics.state_coverage_pct.toFixed(1)}%</div>
          <div className="stat-bar">
            <span style={{ width: `${graphData.statistics.state_coverage_pct}%` }} />
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Transition Coverage</div>
          <div className="stat-value">
            {graphData.statistics.taken_transitions} / {graphData.statistics.total_transitions}
          </div>
          <div className="stat-pct">{graphData.statistics.transition_coverage_pct.toFixed(1)}%</div>
          <div className="stat-bar">
            <span style={{ width: `${graphData.statistics.transition_coverage_pct}%` }} />
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Current State</div>
          <div className="stat-value current-state">
            {graphData.current_state || 'N/A'}
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Total Tests</div>
          <div className="stat-value">{graphData.statistics.total_tests.toLocaleString()}</div>
        </div>
      </div>

      <StateCoverageTable
        states={stateTableData}
        currentState={graphData.current_state}
      />

      <StateTraversalFlow
        rows={traversalFlowData.rows}
        topPaths={traversalFlowData.topPaths}
        maxCount={traversalFlowData.maxCount}
        totalEdges={traversalFlowData.totalEdges}
      />

      <section className="journey-map">
        <div className="journey-header">
          <div>
            <p className="eyebrow">Session Journey</p>
            <h3>State visit map</h3>
            <p>Compare visit intensity with the most used outgoing transitions per state.</p>
          </div>
          <div className="journey-summary">
            <div>
              <span>States tracked</span>
              <strong>{graphData.nodes.length}</strong>
            </div>
            <div>
              <span>Top transitions</span>
              <strong>{journeyData.transitions.length}</strong>
            </div>
          </div>
        </div>
        <div className="journey-grid">
          <div className="journey-states">
            {journeyData.cards.map((card) => (
              <div key={card.id} className={`journey-card ${card.isCurrent ? 'current' : ''}`}>
                <div className="journey-card-header">
                  <div>
                    <span className="journey-state">{card.label}</span>
                    {card.isCurrent && <span className="journey-pill">current</span>}
                  </div>
                  <span className="journey-visits">{card.visits} visits</span>
                </div>
                <div className="journey-outgoing">
                  <span>Outgoing taken</span>
                  <strong>{card.totalOutgoing}</strong>
                </div>
                <div className="journey-bars">
                  {card.topOutgoing.length === 0 && <span className="journey-empty">No taken transitions</span>}
                  {card.topOutgoing.map((edge) => {
                    const percent = card.totalOutgoing
                      ? Math.round(((edge.value || 0) / card.totalOutgoing) * 100)
                      : 0;
                    return (
                      <div key={`${card.id}-${edge.to}`} className="journey-bar-row">
                        <span className="journey-target">{edge.to}</span>
                        <div className="journey-bar">
                          <span style={{ width: `${percent}%` }} />
                        </div>
                        <span className="journey-count">{edge.value || 0}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
          <div className="journey-transitions">
            <h4>Most used transitions</h4>
            <ul>
              {journeyData.transitions.map((edge) => (
                <li key={edge.id}>
                  <span>{edge.from} {'->'} {edge.to}</span>
                  <strong>{edge.value || 0}</strong>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}

export default StateGraphPage;
