import { useState } from 'react';
import './HexViewer.css';

export interface HexHighlight {
  start: number;
  end: number;
  color: string;
  label?: string;
}

interface HexViewerProps {
  data: string; // Hex string (uppercase, no spaces)
  highlights?: HexHighlight[];
  onByteHover?: (offset: number | null) => void;
  bytesPerLine?: number;
}

function HexViewer({ data, highlights = [], onByteHover, bytesPerLine = 16 }: HexViewerProps) {
  const [hoveredByte, setHoveredByte] = useState<number | null>(null);

  // Convert hex string to array of bytes (2 chars = 1 byte)
  const bytes: string[] = [];
  for (let i = 0; i < data.length; i += 2) {
    bytes.push(data.slice(i, i + 2));
  }

  const handleByteEnter = (offset: number) => {
    setHoveredByte(offset);
    onByteHover?.(offset);
  };

  const handleByteLeave = () => {
    setHoveredByte(null);
    onByteHover?.(null);
  };

  const getHighlightForByte = (offset: number): HexHighlight | undefined => {
    return highlights.find((h) => offset >= h.start && offset < h.end);
  };

  const renderLine = (lineBytes: string[], startOffset: number) => {
    return (
      <div key={startOffset} className="hex-line">
        <span className="hex-offset">{startOffset.toString(16).padStart(4, '0').toUpperCase()}:</span>
        <div className="hex-bytes">
          {lineBytes.map((byte, i) => {
            const offset = startOffset + i;
            const highlight = getHighlightForByte(offset);
            const isHovered = hoveredByte === offset;

            return (
              <span
                key={offset}
                className={`hex-byte ${highlight ? 'highlighted' : ''} ${isHovered ? 'hovered' : ''}`}
                style={highlight ? { backgroundColor: highlight.color } : undefined}
                onMouseEnter={() => handleByteEnter(offset)}
                onMouseLeave={handleByteLeave}
                title={highlight?.label}
              >
                {byte}
              </span>
            );
          })}
        </div>
        <div className="hex-ascii">
          {lineBytes.map((byte, i) => {
            const offset = startOffset + i;
            const charCode = parseInt(byte, 16);
            const char = charCode >= 32 && charCode <= 126 ? String.fromCharCode(charCode) : '.';
            const highlight = getHighlightForByte(offset);
            const isHovered = hoveredByte === offset;

            return (
              <span
                key={offset}
                className={`ascii-char ${highlight ? 'highlighted' : ''} ${isHovered ? 'hovered' : ''}`}
                style={highlight ? { backgroundColor: highlight.color } : undefined}
                onMouseEnter={() => handleByteEnter(offset)}
                onMouseLeave={handleByteLeave}
              >
                {char}
              </span>
            );
          })}
        </div>
      </div>
    );
  };

  // Split bytes into lines
  const lines: JSX.Element[] = [];
  for (let i = 0; i < bytes.length; i += bytesPerLine) {
    const lineBytes = bytes.slice(i, i + bytesPerLine);
    lines.push(renderLine(lineBytes, i));
  }

  return (
    <div className="hex-viewer">
      {lines.length > 0 ? lines : <div className="hex-empty">No data to display</div>}
    </div>
  );
}

export default HexViewer;
