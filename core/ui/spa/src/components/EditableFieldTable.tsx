import { useState, useEffect } from 'react';
import './EditableFieldTable.css';

export interface FieldValue {
  name: string;
  value: any;
  hex: string;
  type: string;
  offset: number;
  size: number;
  mutable?: boolean;
  computed?: boolean;
  size_of?: string | null;
}

interface EditableFieldTableProps {
  fields: FieldValue[];
  onFieldChange: (fieldName: string, newValue: any) => void;
  hoveredField: string | null;
  onFieldHover: (fieldName: string | null) => void;
}

function EditableFieldTable({
  fields,
  onFieldChange,
  hoveredField,
  onFieldHover,
}: EditableFieldTableProps) {
  const [editingField, setEditingField] = useState<string | null>(null);
  const [editValue, setEditValue] = useState<string>('');

  const handleEdit = (field: FieldValue) => {
    if (field.computed) return; // Don't allow editing computed fields
    setEditingField(field.name);
    setEditValue(String(field.value));
  };

  const handleSave = (field: FieldValue) => {
    let parsedValue: any = editValue;

    // Convert based on field type
    if (field.type.startsWith('uint') || field.type.startsWith('int')) {
      parsedValue = parseInt(editValue, 10);
      if (isNaN(parsedValue)) {
        alert(`Invalid number: ${editValue}`);
        return;
      }
    } else if (field.type === 'bytes') {
      // Keep as string, will be encoded by backend
      parsedValue = editValue;
    }

    onFieldChange(field.name, parsedValue);
    setEditingField(null);
  };

  const handleCancel = () => {
    setEditingField(null);
    setEditValue('');
  };

  const handleKeyDown = (e: React.KeyboardEvent, field: FieldValue) => {
    if (e.key === 'Enter') {
      handleSave(field);
    } else if (e.key === 'Escape') {
      handleCancel();
    }
  };

  return (
    <div className="editable-field-table">
      <table>
        <thead>
          <tr>
            <th>Field</th>
            <th>Type</th>
            <th>Value</th>
            <th>Hex</th>
            <th>Offset</th>
            <th>Size</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((field) => (
            <tr
              key={field.name}
              className={`${hoveredField === field.name ? 'hovered' : ''} ${
                field.computed ? 'computed' : ''
              } ${field.mutable === false ? 'immutable' : ''}`}
              onMouseEnter={() => onFieldHover(field.name)}
              onMouseLeave={() => onFieldHover(null)}
            >
              <td>
                <strong>{field.name}</strong>
                {field.computed && <span className="badge computed-badge">auto</span>}
                {field.mutable === false && <span className="badge immutable-badge">fixed</span>}
              </td>
              <td>
                <code className="type-code">{field.type}</code>
              </td>
              <td>
                {editingField === field.name ? (
                  <input
                    type="text"
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onKeyDown={(e) => handleKeyDown(e, field)}
                    onBlur={() => handleSave(field)}
                    autoFocus
                    className="field-edit-input"
                  />
                ) : (
                  <span className="field-value">{String(field.value)}</span>
                )}
              </td>
              <td>
                <code className="hex-value">{field.hex}</code>
              </td>
              <td>{field.offset}</td>
              <td>{field.size}</td>
              <td>
                {!field.computed && editingField !== field.name && (
                  <button
                    type="button"
                    onClick={() => handleEdit(field)}
                    className="edit-btn"
                    disabled={field.mutable === false}
                  >
                    Edit
                  </button>
                )}
                {editingField === field.name && (
                  <div className="edit-actions">
                    <button
                      type="button"
                      onClick={() => handleSave(field)}
                      className="save-btn"
                    >
                      ✓
                    </button>
                    <button type="button" onClick={handleCancel} className="cancel-btn">
                      ✕
                    </button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default EditableFieldTable;
