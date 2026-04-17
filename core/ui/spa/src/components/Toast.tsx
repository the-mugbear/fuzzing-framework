import { useEffect } from 'react';
import './Toast.css';

export type ToastVariant = 'success' | 'error' | 'info';

interface ToastProps {
  message: string;
  variant?: ToastVariant;
  onClose?: () => void;
  autoDismissMs?: number;
}

function Toast({ message, variant = 'info', onClose, autoDismissMs }: ToastProps) {
  const dismissDelay = autoDismissMs ?? (variant === 'error' ? 8000 : 4000);

  useEffect(() => {
    if (!onClose) return;
    const timer = setTimeout(onClose, dismissDelay);
    return () => clearTimeout(timer);
  }, [onClose, dismissDelay]);

  return (
    <div className={`toast-banner toast-${variant}`} role="status" aria-live="polite">
      <span>{message}</span>
      {onClose && (
        <button type="button" onClick={onClose} aria-label="Dismiss notification">
          ✕
        </button>
      )}
    </div>
  );
}

export default Toast;
