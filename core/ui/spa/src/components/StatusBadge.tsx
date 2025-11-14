import './StatusBadge.css';

interface Props {
  value: string;
}

const normalize = (status: string) => status.toLowerCase();

function StatusBadge({ value }: Props) {
  const variant = normalize(value);
  return <span className={`status-chip status-${variant}`}>{value}</span>;
}

export default StatusBadge;
