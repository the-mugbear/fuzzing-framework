import { useState } from 'react';
import './StateCoverageTable.css';

interface StateInfo {
  id: string;
  label: string;
  visits: number;
  group: string;
  transitions_out: number;
  transitions_taken: number;
  last_seen?: string;
}

interface StateCoverageTableProps {
  states: StateInfo[];
  currentState: string | null;
}

type SortField = 'name' | 'visits' | 'coverage';
type SortDirection = 'asc' | 'desc';

function StateCoverageTable({ states, currentState }: StateCoverageTableProps) {
  const [sortField, setSortField] = useState<SortField>('visits');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [expandedState, setExpandedState] = useState<string | null>(null);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  const sortedStates = [...states].sort((a, b) => {
    let aVal: number | string;
    let bVal: number | string;

    switch (sortField) {
      case 'name':
        aVal = a.label;
        bVal = b.label;
        break;
      case 'visits':
        aVal = a.visits;
        bVal = b.visits;
        break;
      case 'coverage':
        aVal = a.transitions_out > 0 ? (a.transitions_taken / a.transitions_out) : 0;
        bVal = b.transitions_out > 0 ? (b.transitions_taken / b.transitions_out) : 0;
        break;
    }

    if (typeof aVal === 'string' && typeof bVal === 'string') {
      return sortDirection === 'asc'
        ? aVal.localeCompare(bVal)
        : bVal.localeCompare(aVal);
    }

    return sortDirection === 'asc'
      ? (aVal as number) - (bVal as number)
      : (bVal as number) - (aVal as number);
  });

  const getStateIcon = (state: StateInfo) => {
    if (state.id === currentState) return '●';
    if (state.visits > 0) return '●';
    return '○';
  };

  const getStateClass = (state: StateInfo) => {
    if (state.id === currentState) return 'state-current';
    if (state.visits > 0) return 'state-visited';
    return 'state-unvisited';
  };

  const getCoveragePercent = (state: StateInfo) => {
    if (state.transitions_out === 0) return 100;
    return Math.round((state.transitions_taken / state.transitions_out) * 100);
  };

  return (
    <div className="state-coverage-table-container">
      <div className="table-header">
        <h3>State Coverage</h3>
        <div className="table-summary">
          {states.filter(s => s.visits > 0).length} of {states.length} states visited
        </div>
      </div>

      <table className="state-coverage-table">
        <thead>
          <tr>
            <th className="col-icon"></th>
            <th
              className={`col-name sortable ${sortField === 'name' ? 'sorted' : ''}`}
              onClick={() => handleSort('name')}
            >
              State Name {sortField === 'name' && (sortDirection === 'asc' ? '↑' : '↓')}
            </th>
            <th
              className={`col-visits sortable ${sortField === 'visits' ? 'sorted' : ''}`}
              onClick={() => handleSort('visits')}
            >
              Visits {sortField === 'visits' && (sortDirection === 'asc' ? '↑' : '↓')}
            </th>
            <th className="col-last-seen">Last Seen</th>
            <th className="col-transitions">Transitions Out</th>
            <th
              className={`col-coverage sortable ${sortField === 'coverage' ? 'sorted' : ''}`}
              onClick={() => handleSort('coverage')}
            >
              Coverage {sortField === 'coverage' && (sortDirection === 'asc' ? '↑' : '↓')}
            </th>
          </tr>
        </thead>
        <tbody>
          {sortedStates.map((state) => {
            const coveragePercent = getCoveragePercent(state);
            const isExpanded = expandedState === state.id;

            return (
              <tr
                key={state.id}
                className={`${getStateClass(state)} ${isExpanded ? 'expanded' : ''}`}
                onClick={() => setExpandedState(isExpanded ? null : state.id)}
              >
                <td className="col-icon">
                  <span className={`state-icon ${getStateClass(state)}`}>
                    {getStateIcon(state)}
                  </span>
                </td>
                <td className="col-name">
                  <strong>{state.label}</strong>
                  {state.id === currentState && (
                    <span className="current-badge">Current</span>
                  )}
                </td>
                <td className="col-visits">{state.visits.toLocaleString()}</td>
                <td className="col-last-seen">
                  {state.visits > 0 ? (state.last_seen || 'Recently') : 'Never'}
                </td>
                <td className="col-transitions">
                  <span className={state.transitions_taken === state.transitions_out ? 'complete' : ''}>
                    {state.transitions_taken} of {state.transitions_out}
                  </span>
                </td>
                <td className="col-coverage">
                  <div className="coverage-cell">
                    <span className={`coverage-percent ${coveragePercent === 100 ? 'complete' : ''}`}>
                      {coveragePercent}%
                    </span>
                    <div className="coverage-bar">
                      <div
                        className="coverage-fill"
                        style={{ width: `${coveragePercent}%` }}
                      ></div>
                    </div>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {sortedStates.length === 0 && (
        <div className="empty-table">No states found</div>
      )}
    </div>
  );
}

export default StateCoverageTable;
