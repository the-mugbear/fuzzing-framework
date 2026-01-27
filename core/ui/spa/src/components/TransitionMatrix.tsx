import { useMemo } from 'react';
import './TransitionMatrix.css';

interface TransitionInfo {
  from: string;
  to: string;
  label: string;
  count: number;
  taken: boolean;
}

interface TransitionMatrixProps {
  states: string[];
  transitions: TransitionInfo[];
}

function TransitionMatrix({ states, transitions }: TransitionMatrixProps) {
  // Build matrix data
  const matrix = useMemo(() => {
    const data: Record<string, Record<string, { count: number; label: string; taken: boolean }>> = {};

    // Initialize matrix
    states.forEach((from) => {
      data[from] = {};
      states.forEach((to) => {
        data[from][to] = { count: 0, label: '', taken: false };
      });
    });

    // Populate with transition data
    transitions.forEach((transition) => {
      if (data[transition.from] && data[transition.from][transition.to]) {
        data[transition.from][transition.to] = {
          count: transition.count,
          label: transition.label,
          taken: transition.taken
        };
      }
    });

    return data;
  }, [states, transitions]);

  const maxCount = useMemo(() => {
    return Math.max(...transitions.map(t => t.count), 1);
  }, [transitions]);

  const getHeatColor = (count: number, taken: boolean) => {
    if (count === 0 || !taken) {
      return 'rgba(148, 163, 184, 0.1)'; // Gray for untaken
    }

    const intensity = Math.min(count / maxCount, 1);
    // Gradient from blue to green based on intensity
    const r = Math.round(59 + (34 - 59) * intensity);
    const g = Math.round(130 + (197 - 130) * intensity);
    const b = Math.round(246 + (94 - 246) * intensity);
    return `rgba(${r}, ${g}, ${b}, ${0.3 + intensity * 0.7})`;
  };

  const getCellContent = (from: string, to: string) => {
    if (from === to) return { display: '-', tooltip: 'Self-loop' };

    const cell = matrix[from]?.[to];
    if (!cell) return { display: '', tooltip: '' };

    if (cell.count === 0) {
      return {
        display: '',
        tooltip: `${from}  ->  ${to}: Never taken${cell.label ? ` (${cell.label})` : ''}`
      };
    }

    return {
      display: cell.count.toLocaleString(),
      tooltip: `${from}  ->  ${to}: ${cell.count.toLocaleString()} times${cell.label ? ` (${cell.label})` : ''}`
    };
  };

  if (states.length === 0) {
    return (
      <div className="transition-matrix-container">
        <div className="matrix-header">
          <h3>Transition Matrix</h3>
        </div>
        <div className="empty-matrix">No transitions to display</div>
      </div>
    );
  }

  return (
    <div className="transition-matrix-container">
      <div className="matrix-header">
        <h3>Transition Matrix</h3>
        <div className="matrix-legend">
          <span className="legend-item">
            <span className="legend-swatch" style={{ background: 'rgba(148, 163, 184, 0.1)' }}></span>
            Untaken
          </span>
          <span className="legend-item">
            <span className="legend-swatch" style={{ background: 'rgba(59, 130, 246, 0.5)' }}></span>
            Low usage
          </span>
          <span className="legend-item">
            <span className="legend-swatch" style={{ background: 'rgba(34, 197, 94, 0.9)' }}></span>
            High usage
          </span>
        </div>
      </div>

      <div className="matrix-scroll">
        <table className="transition-matrix">
          <thead>
            <tr>
              <th className="corner-cell">From \ To</th>
              {states.map((state) => (
                <th key={state} className="state-header">
                  <div className="state-label">{state}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {states.map((fromState) => (
              <tr key={fromState}>
                <th className="state-header row-header">
                  <div className="state-label">{fromState}</div>
                </th>
                {states.map((toState) => {
                  const cell = matrix[fromState]?.[toState];
                  const content = getCellContent(fromState, toState);
                  const bgColor = getHeatColor(cell?.count || 0, cell?.taken || false);

                  return (
                    <td
                      key={`${fromState}-${toState}`}
                      className={`matrix-cell ${cell?.count === 0 ? 'untaken' : 'taken'} ${fromState === toState ? 'diagonal' : ''}`}
                      style={{ background: bgColor }}
                      title={content.tooltip}
                    >
                      {content.display}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="matrix-note">
        <strong>How to read:</strong> Each cell shows the number of times a transition was taken from the row state to the column state.
        Hover over cells for details. Darker colors indicate higher usage.
      </div>
    </div>
  );
}

export default TransitionMatrix;
