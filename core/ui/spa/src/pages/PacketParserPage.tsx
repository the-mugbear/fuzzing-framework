import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import HexViewer, { HexHighlight } from '../components/HexViewer';
import ParsedFieldsView, { FieldInfo } from '../components/ParsedFieldsView';
import { api } from '../services/api';
import './PacketParserPage.css';

const FIELD_COLORS = ['#3b82f680', '#10b98180', '#8b5cf680', '#f59e0b80', '#ef444480', '#06b6d480', '#ec489980'];

interface ParseResponse {
  success: boolean;
  fields: FieldInfo[];
  raw_hex: string;
  total_bytes: number;
  warnings: string[];
  error?: string;
}

interface PreviewSeedResponse {
  previews: Array<{
    hex_dump: string;
  }>;
}

function PacketParserPage() {
  const [searchParams] = useSearchParams();
  const findingId = searchParams.get('finding');

  const [protocols, setProtocols] = useState<string[]>([]);
  const [protocolsLoading, setProtocolsLoading] = useState(true);
  const [selectedProtocol, setSelectedProtocol] = useState('');
  const [hexInput, setHexInput] = useState('');
  const [parseResult, setParseResult] = useState<ParseResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hoveredField, setHoveredField] = useState<string | null>(null);
  const [findingInfo, setFindingInfo] = useState<any>(null);

  useEffect(() => {
    api<string[]>('/api/plugins')
      .then((names) => {
        setProtocols(names);
        if (names.length) {
          setSelectedProtocol((prev) => prev || names[0]);
        }
        setProtocolsLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setProtocolsLoading(false);
      });
  }, []);

  // Load finding data if finding parameter is present
  useEffect(() => {
    if (!findingId) return;

    const loadFinding = async () => {
      try {
        setLoading(true);
        setError(null);

        // Fetch finding with binary data
        const finding = await api<any>(`/api/corpus/findings/${findingId}?include_data=true`);
        setFindingInfo(finding.report);

        // Set protocol if available in the crash report
        if (finding.report?.protocol) {
          setSelectedProtocol(finding.report.protocol);
        }

        // Set hex input from reproducer data
        if (finding.reproducer_hex) {
          // Format hex with spaces for readability
          const spacedHex = finding.reproducer_hex.match(/.{1,2}/g)?.join(' ') ?? finding.reproducer_hex;
          setHexInput(spacedHex);
        }

        setLoading(false);
      } catch (err) {
        setError(`Failed to load finding: ${(err as Error).message}`);
        setLoading(false);
      }
    };

    loadFinding();
  }, [findingId]);

  const handleParse = async (e: FormEvent) => {
    e.preventDefault();
    if (!selectedProtocol || !hexInput.trim()) {
      setError('Please select a protocol and enter hex data');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const result = await api<ParseResponse>('/api/tools/parse', {
        method: 'POST',
        body: JSON.stringify({
          protocol: selectedProtocol,
          hex_data: hexInput,
        }),
      });
      setParseResult(result);
      if (!result.success && result.error) {
        setError(result.error);
      }
    } catch (err) {
      setError((err as Error).message);
      setParseResult(null);
    } finally {
      setLoading(false);
    }
  };

  const handleLoadExample = async () => {
    const fallbackProtocol =
      selectedProtocol ||
      (protocols.includes('simple_tcp') ? 'simple_tcp' : protocols[0] || '');

    if (!fallbackProtocol) {
      setError('No protocol available for examples');
      return;
    }

    try {
      setError(null);
      const preview = await api<PreviewSeedResponse>(`/api/plugins/${fallbackProtocol}/preview`, {
        method: 'POST',
        body: JSON.stringify({ mode: 'seeds', count: 1 }),
      });
      const example = preview.previews[0];
      if (!example) {
        throw new Error('No seeds available for this protocol');
      }
      const spacedHex = example.hex_dump.match(/.{1,2}/g)?.join(' ') ?? example.hex_dump;
      if (!selectedProtocol) {
        setSelectedProtocol(fallbackProtocol);
      }
      setHexInput(spacedHex);
      setParseResult(null);
    } catch (err) {
      setError(`Failed to load example: ${(err as Error).message}`);
    }
  };

  const highlights = useMemo<HexHighlight[]>(() => {
    if (!parseResult?.success || !parseResult.fields) return [];
    return parseResult.fields.map((field, index) => ({
      start: field.offset,
      end: field.offset + field.size,
      color: FIELD_COLORS[index % FIELD_COLORS.length],
      label: `${field.name} (${field.type})`,
    }));
  }, [parseResult]);

  const handleFieldHover = (fieldName: string | null) => setHoveredField(fieldName);

  const handleByteHover = (offset: number | null) => {
    if (offset === null) {
      setHoveredField(null);
      return;
    }
    const field = parseResult?.fields.find((f) => offset >= f.offset && offset < f.offset + f.size);
    setHoveredField(field?.name || null);
  };

  return (
    <div className="packet-parser-page">
      <div className="parser-header">
        <div>
          <p className="eyebrow">Protocol Development</p>
          <h2>Packet Parser</h2>
          <p>Decode binary packets using protocol definitions. Hover over fields to highlight bytes.</p>
        </div>
      </div>

      {error && (
        <div className="error-banner">
          <strong>Error:</strong> {error}
        </div>
      )}

      {findingInfo && (
        <div className="finding-banner">
          <h3>🔍 Viewing Crash Finding</h3>
          <div className="finding-details">
            <div className="detail-item">
              <strong>Finding ID:</strong> {findingInfo.id}
            </div>
            <div className="detail-item">
              <strong>Result:</strong> {findingInfo.result}
            </div>
            {findingInfo.severity && (
              <div className="detail-item">
                <strong>Severity:</strong> {findingInfo.severity}
              </div>
            )}
            {findingInfo.signal && (
              <div className="detail-item">
                <strong>Signal:</strong> {findingInfo.signal}
              </div>
            )}
            {findingInfo.exit_code !== undefined && (
              <div className="detail-item">
                <strong>Exit Code:</strong> {findingInfo.exit_code}
              </div>
            )}
          </div>
          <p className="finding-note">
            The packet below caused this crash. Parse it to see the decoded structure and mutated fields.
          </p>
        </div>
      )}

      <div className="parser-form card">
        <form onSubmit={handleParse}>
          <div className="form-row">
            <div className="form-group">
              <label htmlFor="protocol">Protocol</label>
              <select
                id="protocol"
                value={selectedProtocol}
                onChange={(e) => setSelectedProtocol(e.target.value)}
                disabled={loading || protocolsLoading}
              >
                <option value="">{protocolsLoading ? 'Loading…' : 'Select protocol…'}</option>
                {protocols.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="hexInput">
              Hex Data
              <span className="label-hint">(spaces and newlines will be ignored)</span>
            </label>
            <textarea
              id="hexInput"
              value={hexInput}
              onChange={(e) => setHexInput(e.target.value)}
              placeholder="53 54 43 50 00 00 00 05 01 48 45 4C 4C 4F"
              rows={4}
              disabled={loading}
              className="hex-input"
            />
          </div>

          <div className="form-actions">
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? 'Parsing…' : 'Parse Packet'}
            </button>
            <button type="button" className="btn btn-secondary" onClick={handleLoadExample}>
              Load Example
            </button>
          </div>
        </form>
      </div>

      {parseResult && parseResult.success && (
        <div className="parser-results">
          <div className="result-section">
            <h3>Parsed Fields</h3>
            <div className="card">
              <ParsedFieldsView
                fields={parseResult.fields}
                hoveredField={hoveredField}
                onFieldHover={handleFieldHover}
              />
            </div>
          </div>

          <div className="result-section">
            <h3>Hex Viewer</h3>
            <div className="card">
              <HexViewer data={parseResult.raw_hex} highlights={highlights} onByteHover={handleByteHover} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default PacketParserPage;
