import { ReactNode, useId, useState } from 'react';
import './Tooltip.css';

interface TooltipProps {
  content: ReactNode;
  position?: 'top' | 'bottom' | 'left' | 'right';
  children?: ReactNode;
}

function Tooltip({ content, position = 'top', children }: TooltipProps) {
  const [isVisible, setIsVisible] = useState(false);
  const tooltipId = useId();

  const show = () => setIsVisible(true);
  const hide = () => setTimeout(() => setIsVisible(false), 150);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { setIsVisible(false); }
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
