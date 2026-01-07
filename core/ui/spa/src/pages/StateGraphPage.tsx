import cytoscape, { Core, ElementDefinition } from 'cytoscape';
import elk from 'cytoscape-elk';
import { useEffect, useRef, useState, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../services/api';
import StateCoverageTable from '../components/StateCoverageTable';
import TransitionMatrix from '../components/TransitionMatrix';
import './StateGraphPage.css';

cytoscape.use(elk);

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
  const [showGraph, setShowGraph] = useState(false);
  const networkRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

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

  // Prepare data for TransitionMatrix
  const transitionMatrixData = useMemo(() => {
    if (!graphData || !graphData.nodes || !graphData.edges) {
      console.log('[StateGraphPage] Transition Matrix: No graph data', graphData);
      return { states: [], transitions: [] };
    }

    const states = graphData.nodes.map(n => n.id);
    const transitions = graphData.edges.map(edge => ({
      from: edge.from,
      to: edge.to,
      label: edge.label || '',
      count: edge.value || 0,
      taken: !edge.dashes
    }));

    console.log('[StateGraphPage] Transition Matrix Data:', {
      states,
      transitions,
      statesCount: states.length,
      transitionsCount: transitions.length
    });

    return { states, transitions };
  }, [graphData]);

  // Group edges by source-target pair for better rendering
  const groupedEdges = useMemo(() => {
    if (!graphData) return new Map<string, Edge[]>();

    const groups = new Map<string, Edge[]>();
    graphData.edges.forEach(edge => {
      const key = `${edge.from}->${edge.to}`;
      if (!groups.has(key)) {
        groups.set(key, []);
      }
      groups.get(key)!.push(edge);
    });

    return groups;
  }, [graphData]);

  useEffect(() => {
    if (!graphData || !networkRef.current || !showGraph) return;

    const container = networkRef.current;

    // Prepare node elements
    const nodeElements: ElementDefinition[] = graphData.nodes.map((node) => {
      const visitSize = Math.min(80, 32 + Math.log2(node.visits + 1) * 14);
      return {
        data: {
          id: node.id,
          label: node.label || node.id,
          visits: node.visits,
          group: node.group
        },
        classes: `state ${node.group || ''}`.trim(),
        style: {
          width: visitSize,
          height: visitSize
        }
      };
    });

    // Prepare edge elements with better self-loop handling
    const edgeElements: ElementDefinition[] = Array.from(groupedEdges.entries()).flatMap(([key, edges]) => {
      const isLoop = edges[0].from === edges[0].to;

      return edges.map((edge, index) => {
        // Calculate offset for multiple edges between same nodes
        const totalEdges = edges.length;
        const offset = index - (totalEdges - 1) / 2;

        // For self-loops, distribute around the node using loop-direction
        // This spreads multiple self-loops at different angles
        let loopDirection = -90; // Default upward
        let loopSweep = 60;      // Arc sweep angle

        if (isLoop && totalEdges > 1) {
          // Distribute loops evenly around the node
          const angleStep = 120 / Math.max(totalEdges - 1, 1);
          loopDirection = -150 + (index * angleStep); // Spread from -150° to -30°
          loopSweep = Math.min(60, 120 / totalEdges); // Smaller sweep for more loops
        }

        return {
          data: {
            id: edge.id,
            source: edge.from,
            target: edge.to,
            label: edge.label,
            value: edge.value,
            dashes: edge.dashes,
            offset: offset,
            isLoop: isLoop,
            loopDirection: loopDirection,
            loopSweep: loopSweep,
            edgeIndex: index,
            totalEdges: totalEdges
          },
          classes: `transition ${edge.dashes ? 'untaken' : 'taken'} ${isLoop ? 'loop' : ''}`.trim()
        };
      });
    });

    const elements = [...nodeElements, ...edgeElements];

    const styles: any[] = [
      {
        selector: 'node',
        style: {
          'background-color': '#1f2937',
          'border-color': '#334155',
          'border-width': 3,
          label: 'data(label)',
          color: '#e2e8f0',
          'text-outline-color': '#0f172a',
          'text-outline-width': 3,
          'font-size': 14,
          'font-weight': 600,
          'text-wrap': 'wrap',
          'text-max-width': '140px',
          'text-halign': 'center',
          'text-valign': 'center',
          'shadow-blur': 16,
          'shadow-color': 'rgba(0,0,0,0.4)',
          'shadow-offset-x': 0,
          'shadow-offset-y': 4,
          'padding': 12
        }
      },
      {
        selector: 'node.current',
        style: {
          'background-color': '#22c55e',
          'border-color': '#bbf7d0',
          'border-width': 4,
          'text-outline-color': '#064e3b',
          'shadow-blur': 20,
          'shadow-color': 'rgba(34,197,94,0.5)',
          'shadow-offset-y': 6
        }
      },
      {
        selector: 'node.visited',
        style: {
          'background-color': '#3b82f6',
          'border-color': '#bfdbfe'
        }
      },
      {
        selector: 'node.unvisited',
        style: {
          'background-color': '#64748b',
          'border-color': '#cbd5e1',
          opacity: 0.6
        }
      },
      {
        selector: 'edge',
        style: {
          'curve-style': function(ele: any) {
            if (ele.data('isLoop')) {
              return 'loop';
            } else if (ele.data('totalEdges') > 1) {
              return 'unbundled-bezier';
            } else {
              return 'bezier';
            }
          },
          'loop-direction': function(ele: any) {
            return `${ele.data('loopDirection') || -90}deg`;
          },
          'loop-sweep': function(ele: any) {
            return `${ele.data('loopSweep') || 60}deg`;
          },
          'control-point-distances': function(ele: any) {
            if (!ele.data('isLoop')) {
              const offset = ele.data('offset') || 0;
              return [offset * 80];
            }
            return undefined;
          },
          'control-point-weights': function(ele: any) {
            if (!ele.data('isLoop')) {
              return [0.5];
            }
            return undefined;
          },
          'line-color': '#64748b',
          'target-arrow-color': '#64748b',
          'target-arrow-shape': 'triangle',
          'arrow-scale': 1.2,
          width: function(ele: any) {
            const value = ele.data('value') || 0;
            return Math.max(2, Math.min(8, 2 + Math.log2(value + 1) * 1.5));
          },
          label: 'data(label)',
          'font-size': 11,
          'font-weight': 600,
          color: '#cbd5e1',
          'text-background-color': '#0f172a',
          'text-background-opacity': 0.9,
          'text-background-padding': 4,
          'text-background-shape': 'roundrectangle',
          'text-border-width': 1,
          'text-border-color': '#334155',
          'text-border-opacity': 0.5,
          'text-rotation': 'autorotate',
          'text-margin-y': function(ele: any) {
            const offset = ele.data('offset') || 0;
            return offset * -15;
          },
          'edge-distances': 'node-position'
        }
      },
      {
        selector: 'edge.taken',
        style: {
          'line-color': '#38bdf8',
          'target-arrow-color': '#38bdf8',
          opacity: 0.9
        }
      },
      {
        selector: 'edge.untaken',
        style: {
          'line-style': 'dashed',
          'line-dash-pattern': [10, 5],
          'line-color': '#475569',
          'target-arrow-color': '#475569',
          opacity: 0.5
        }
      },
      {
        selector: 'edge.loop',
        style: {
          'text-margin-y': -25,
          'text-rotation': 0
        }
      },
      {
        selector: ':selected',
        style: {
          'border-width': 5,
          'border-color': '#fbbf24',
          'line-color': '#fbbf24',
          'target-arrow-color': '#fbbf24',
          'z-index': 999
        }
      }
    ];

    const layoutOptions: any = {
      name: 'elk',
      nodeDimensionsIncludeLabels: true,
      fit: true,
      animate: true,
      animationDuration: 500,
      animationEasing: 'ease-out',
      padding: 50,
      elk: {
        algorithm: 'layered',
        'elk.direction': 'RIGHT',
        'elk.layered.spacing.nodeNodeBetweenLayers': '100',
        'elk.spacing.nodeNode': '80',
        'elk.layered.nodePlacement.strategy': 'SIMPLE',
        'elk.layered.crossingMinimization.semiInteractive': 'true',
        'separateConnectedComponents': 'false'
      }
    };

    if (!cyRef.current) {
      // Create new instance
      cyRef.current = cytoscape({
        container,
        elements,
        style: styles,
        wheelSensitivity: 0.15,
        boxSelectionEnabled: true,
        autoungrabify: false,
        minZoom: 0.3,
        maxZoom: 3
      });

      // Apply layout
      const layout = cyRef.current.layout(layoutOptions);
      layout.run();

      // Add interaction handlers
      cyRef.current.on('tap', 'node', function(evt) {
        const node = evt.target;
        console.log('Node clicked:', node.data());
      });

      cyRef.current.on('tap', 'edge', function(evt) {
        const edge = evt.target;
        console.log('Edge clicked:', edge.data());
      });

    } else {
      // Update existing instance
      const cy = cyRef.current;

      // Check if graph structure changed (node/edge count)
      const currentNodeCount = cy.nodes().length;
      const currentEdgeCount = cy.edges().length;
      const newNodeCount = nodeElements.length;
      const newEdgeCount = edgeElements.length;

      const structureChanged =
        currentNodeCount !== newNodeCount ||
        currentEdgeCount !== newEdgeCount;

      cy.batch(() => {
        cy.elements().remove();
        cy.add(elements);
      });

      // Only re-layout if structure changed, otherwise just update styling
      if (structureChanged) {
        const layout = cy.layout(layoutOptions);
        layout.run();
      } else {
        // Just update styles without animation to prevent stutter
        cy.style(styles);
      }
    }
  }, [graphData, showGraph]);

  useEffect(() => {
    return () => {
      cyRef.current?.destroy();
      cyRef.current = null;
    };
  }, []);

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

  const handleFit = () => {
    if (cyRef.current) {
      cyRef.current.fit(undefined, 50);
      cyRef.current.center();
    }
  };

  const handleZoomIn = () => {
    if (cyRef.current) {
      cyRef.current.zoom(cyRef.current.zoom() * 1.2);
      cyRef.current.center();
    }
  };

  const handleZoomOut = () => {
    if (cyRef.current) {
      cyRef.current.zoom(cyRef.current.zoom() * 0.8);
      cyRef.current.center();
    }
  };

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

      <TransitionMatrix
        states={transitionMatrixData.states}
        transitions={transitionMatrixData.transitions}
      />

      <div className="graph-section">
        <div className="graph-section-header">
          <h3>Interactive Graph Visualization</h3>
          <button
            onClick={() => setShowGraph(!showGraph)}
            className="toggle-graph-btn"
          >
            {showGraph ? '▼ Hide Graph' : '▶ Show Graph'}
          </button>
        </div>

        {showGraph && (
          <>
            <div className="graph-legend">
              <h4>Legend</h4>
              <div className="legend-items">
                <div className="legend-item">
                  <span className="legend-color" style={{ backgroundColor: '#22c55e' }}></span>
                  <span>Current State</span>
                </div>
                <div className="legend-item">
                  <span className="legend-color" style={{ backgroundColor: '#3b82f6' }}></span>
                  <span>Visited State</span>
                </div>
                <div className="legend-item">
                  <span className="legend-color" style={{ backgroundColor: '#64748b' }}></span>
                  <span>Unvisited State</span>
                </div>
                <div className="legend-item">
                  <span className="legend-line" style={{ borderColor: '#38bdf8', borderStyle: 'solid' }}></span>
                  <span>Taken Transition</span>
                </div>
                <div className="legend-item">
                  <span className="legend-line" style={{ borderColor: '#475569', borderStyle: 'dashed' }}></span>
                  <span>Untaken Transition</span>
                </div>
              </div>
              <p className="legend-note">
                • Node size = visit count (larger = more visits)<br />
                • Edge thickness = transition usage (thicker = more used)<br />
                • Multiple edges between states are separated for clarity<br />
                • Drag nodes to rearrange · Use mouse wheel to zoom · Click to select
              </p>
            </div>

            <div className="graph-container">
              <div className="graph-zoom-controls">
                <button onClick={handleZoomIn} className="zoom-btn" title="Zoom In">
                  +
                </button>
                <button onClick={handleZoomOut} className="zoom-btn" title="Zoom Out">
                  −
                </button>
                <button onClick={handleFit} className="zoom-btn" title="Fit to Screen">
                  ⊡
                </button>
              </div>
              <div ref={networkRef} className="network-graph"></div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default StateGraphPage;
