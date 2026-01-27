import { ReactNode, useState } from 'react';
import './Tooltip.css';

interface TooltipProps {
  content: ReactNode;
  position?: 'top' | 'bottom' | 'left' | 'right';
  children?: ReactNode;
}

function Tooltip({ content, position = 'top', children }: TooltipProps) {
  const [isVisible, setIsVisible] = useState(false);

  const handleMouseEnter = () => setIsVisible(true);
  const handleMouseLeave = () => {
    // Small delay to allow moving mouse to tooltip
    setTimeout(() => setIsVisible(false), 150);
  };

  return (
    <span
      className="tooltip-wrapper"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {children || (
        <span className="tooltip-trigger">i</span>
      )}
      {isVisible && (
        <span className={`tooltip-content position-${position}`}>
          {content}
        </span>
      )}
    </span>
  );
}

export default Tooltip;
