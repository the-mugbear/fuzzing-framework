import './StatusBadge.css';

interface Props {
  value: string;
}

const STATUS_LABELS: Record<string, string> = {
  running: 'Running',
  completed: 'Completed',
  idle: 'Idle',
  failed: 'Failed',
  paused: 'Paused',
};

function StatusBadge({ value }: Props) {
  const variant = value.toLowerCase();
  const label = STATUS_LABELS[variant] || value;
  return (
    <span className={`status-chip status-${variant}`} role="status" aria-label={`Status: ${label}`}>
      {label}
    </span>
  );
}

export default StatusBadge;
