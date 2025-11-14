import './Toast.css';

export type ToastVariant = 'success' | 'error' | 'info';

interface ToastProps {
  message: string;
  variant?: ToastVariant;
  onClose?: () => void;
}

function Toast({ message, variant = 'info', onClose }: ToastProps) {
  return (
    <div className={`toast-banner toast-${variant}`} role="status">
      <span>{message}</span>
      {onClose && (
        <button type="button" onClick={onClose}>
          ×
        </button>
      )}
    </div>
  );
}

export default Toast;
