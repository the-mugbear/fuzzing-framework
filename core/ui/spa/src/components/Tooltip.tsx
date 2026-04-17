import { ReactNode, useCallback, useEffect, useId, useRef, useState } from 'react';
import './Tooltip.css';

interface TooltipProps {
  content: ReactNode;
  position?: 'top' | 'bottom' | 'left' | 'right';
  children?: ReactNode;
}

function Tooltip({ content, position = 'top', children }: TooltipProps) {
  const [isVisible, setIsVisible] = useState(false);
  const tooltipId = useId();
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearHideTimer = useCallback(() => {
    if (hideTimer.current !== null) {
      clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
  }, []);

  const show = useCallback(() => { clearHideTimer(); setIsVisible(true); }, [clearHideTimer]);
  const hide = useCallback(() => {
    clearHideTimer();
    hideTimer.current = setTimeout(() => setIsVisible(false), 150);
  }, [clearHideTimer]);

  useEffect(() => clearHideTimer, [clearHideTimer]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { clearHideTimer(); setIsVisible(false); }
  };

  return (
    <span
      className="tooltip-wrapper"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      onKeyDown={handleKeyDown}
    >
      {children || (
        <button
          type="button"
          className="tooltip-trigger"
          aria-describedby={isVisible ? tooltipId : undefined}
          tabIndex={0}
          aria-label="More info"
        >
          i
        </button>
      )}
      {isVisible && (
        <span
          id={tooltipId}
          className={`tooltip-content position-${position}`}
          role="tooltip"
        >
          {content}
        </span>
      )}
    </span>
  );
}

export default Tooltip;
