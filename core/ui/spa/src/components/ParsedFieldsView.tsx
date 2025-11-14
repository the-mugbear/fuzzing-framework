import './ParsedFieldsView.css';

export interface FieldInfo {
  name: string;
  value: string;
  type: string;
  offset: number;
  size: number;
  mutable: boolean;
  description?: string;
  hex_value: string;
}

interface ParsedFieldsViewProps {
  fields: FieldInfo[];
  hoveredField?: string | null;
  onFieldHover?: (fieldName: string | null) => void;
}

function ParsedFieldsView({ fields, hoveredField, onFieldHover }: ParsedFieldsViewProps) {
  const getTypeColor = (type: string): string => {
    if (type === 'bytes') return '#3b82f6';
    if (type.startsWith('uint')) return '#10b981';
    if (type.startsWith('int')) return '#8b5cf6';
    if (type === 'string') return '#f59e0b';
    return '#6b7280';
  };

  return (
    <div className="parsed-fields-view">
      {fields.length === 0 ? (
        <div className="fields-empty">No fields parsed</div>
      ) : (
        <table className="fields-table">
          <thead>
            <tr>
              <th>Field</th>
              <th>Value</th>
              <th>Type</th>
              <th>Offset</th>
              <th>Size</th>
              <th>Hex</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((field) => (
              <tr
                key={field.name}
                className={`field-row ${hoveredField === field.name ? 'hovered' : ''} ${
                  !field.mutable ? 'immutable' : ''
                }`}
                onMouseEnter={() => onFieldHover?.(field.name)}
                onMouseLeave={() => onFieldHover?.(null)}
                title={field.description}
              >
                <td className="field-name">
                  {field.name}
                  {!field.mutable && <span className="immutable-badge">fixed</span>}
                </td>
                <td className="field-value">{field.value}</td>
                <td className="field-type">
                  <span className="type-badge" style={{ backgroundColor: getTypeColor(field.type) }}>
                    {field.type}
                  </span>
                </td>
                <td className="field-offset">0x{field.offset.toString(16).toUpperCase()}</td>
                <td className="field-size">{field.size} byte{field.size !== 1 ? 's' : ''}</td>
                <td className="field-hex">
                  <code>{field.hex_value}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default ParsedFieldsView;
