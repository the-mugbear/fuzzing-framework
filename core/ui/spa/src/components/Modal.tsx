import { ReactNode } from 'react';
import './Modal.css';

interface ModalProps {
  title?: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  className?: string;
}

function Modal({ title, open, onClose, children, className }: ModalProps) {
  if (!open) {
    return null;
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className={`modal-dialog${className ? ` ${className}` : ''}`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <h3>{title}</h3>
          <button type="button" className="modal-close-btn" onClick={onClose}>
            X
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export default Modal;
