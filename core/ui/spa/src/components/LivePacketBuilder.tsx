import HexViewer, { HexHighlight } from './HexViewer';
import { FieldValue } from './EditableFieldTable';
import './LivePacketBuilder.css';

interface LivePacketBuilderProps {
  hexData: string;
  fields: FieldValue[];
  totalBytes: number;
  onByteHover: (offset: number | null) => void;
  building: boolean;
  error: string | null;
}

// Color palette for field highlighting (same as PacketParserPage)
const FIELD_COLORS = [
  '#3b82f680', // blue
  '#10b98180', // green
  '#8b5cf680', // purple
  '#f59e0b80', // orange
  '#ef444480', // red
  '#06b6d480', // cyan
  '#ec489980', // pink
];

function LivePacketBuilder({
  hexData,
  fields,
  totalBytes,
  onByteHover,
  building,
  error,
}: LivePacketBuilderProps) {
  // Generate highlights from fields
  const getHighlights = (): HexHighlight[] => {
    return fields.map((field, index) => ({
      start: field.offset,
      end: field.offset + field.size,
      color: FIELD_COLORS[index % FIELD_COLORS.length],
      label: `${field.name} (${field.type})`,
    }));
  };

  return (
    <div className="live-packet-builder">
      <div className="builder-header">
        <div>
          <h4>Live Packet Preview</h4>
          <p className="builder-meta">{totalBytes} bytes total</p>
        </div>
        {building && <span className="building-indicator">Building...</span>}
      </div>

      {error && (
        <div className="builder-error">
          <strong>Build Error:</strong> {error}
        </div>
      )}

      {hexData && !error && (
        <div className="hex-viewer-container">
          <HexViewer data={hexData} highlights={getHighlights()} onByteHover={onByteHover} />
        </div>
      )}

      {!hexData && !error && !building && (
        <div className="builder-placeholder">
          <p>Modify fields above to see the built packet</p>
        </div>
      )}
    </div>
  );
}

export default LivePacketBuilder;
