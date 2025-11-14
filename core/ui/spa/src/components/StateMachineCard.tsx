import './StateMachineCard.css';

interface Transition {
  from_state: string;
  to_state: string;
  message_type?: string;
  trigger?: string;
  expected_response?: string;
}

interface StateMachineInfo {
  has_state_model: boolean;
  states?: string[];
  initial_state?: string;
  transitions?: Transition[];
  message_type_to_command?: Record<string, number>;
}

interface Props {
  info?: StateMachineInfo;
}

function StateMachineCard({ info }: Props) {
  if (!info || !info.has_state_model) {
    return null;
  }

  return (
    <div className="state-machine-card">
      <div className="state-header">
        <p className="eyebrow">State Machine</p>
        <h3>Valid States & Transitions</h3>
        <p>Initial state: {info.initial_state || info.states?.[0] || 'N/A'}</p>
      </div>
      <div className="state-grid">
        {info.states?.map((state) => (
          <div key={state} className="state-pill">
            {state}
          </div>
        ))}
      </div>
      <table className="transition-table">
        <thead>
          <tr>
            <th>From</th>
            <th>Message</th>
            <th>To</th>
            <th>Expected Response</th>
          </tr>
        </thead>
        <tbody>
          {info.transitions?.map((transition, idx) => (
            <tr key={`${transition.from_state}-${transition.to_state}-${idx}`}>
              <td>{transition.from_state}</td>
              <td>{transition.message_type || transition.trigger || '—'}</td>
              <td>{transition.to_state}</td>
              <td>{transition.expected_response || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default StateMachineCard;
