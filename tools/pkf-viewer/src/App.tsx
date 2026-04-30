import { useEffect, useMemo, useState } from 'react';
import { fetchPalette, fetchPkf, fetchPkfs, fetchSummary, previewUrl } from './api';
import { allDimensions, allKinds, allP3DFamilies, matchesPkfFilters, recordDimension } from './filtering';
import type { PaletteColor, PkfDetail, PkfListItem, PkfRecord, Summary } from './types';

function formatBytes(value: number): string {
  if (value >= 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${value} B`;
}

function recordLabel(record: PkfRecord): string {
  const dimension = recordDimension(record);
  if (record.payload.p3d_label) {
    return `${record.payload.kind}: ${record.payload.p3d_label}`;
  }
  return dimension ? `${record.payload.kind} ${dimension}` : record.payload.kind;
}

function p3dFloatSummary(record: PkfRecord): string | null {
  const finite = record.payload.p3d_float32_finite_sample_count;
  const plausible = record.payload.p3d_float32_plausible_sample_count;
  if (finite === null || plausible === null) {
    return null;
  }
  return `${plausible}/${finite} plausible float32 words in first 4 KB`;
}

function duplicateSummary(record: PkfRecord): string | null {
  const count = record.payload.duplicate_payload_count;
  if (count === null || count < 2) {
    return null;
  }
  return `same payload appears ${count} times`;
}

function p3dChunkSummary(record: PkfRecord): string {
  const payload = record.payload;
  if (payload.p3d_chunk128_loader_iterations === null) {
    return 'n/a';
  }
  const trailing = payload.p3d_chunk128_trailing_bytes ?? 0;
  return `${payload.p3d_chunk128_loader_iterations} loader-sized chunks; ${payload.p3d_chunk128_floor_count ?? 0} full, ${trailing} trailing bytes`;
}

function PaletteSwatch({
  pkfId,
  record,
}: {
  pkfId: number;
  record: PkfRecord;
}) {
  const [colors, setColors] = useState<PaletteColor[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchPalette(pkfId, record.table_index, record.slot_index)
      .then((nextColors) => {
        if (active) {
          setColors(nextColors);
          setError(null);
        }
      })
      .catch((err: Error) => {
        if (active) {
          setError(err.message);
        }
      });
    return () => {
      active = false;
    };
  }, [pkfId, record.table_index, record.slot_index]);

  if (error) {
    return <div className="preview preview-empty">Palette unavailable</div>;
  }

  return (
    <div className="palette-grid" aria-label="Palette colors">
      {colors.slice(0, 128).map((color) => (
        <span
          key={color.index}
          className="palette-chip"
          title={`#${color.index} rgb(${color.r}, ${color.g}, ${color.b})`}
          style={{ backgroundColor: `rgb(${color.r}, ${color.g}, ${color.b})` }}
        />
      ))}
    </div>
  );
}

function RecordPreview({
  pkfId,
  record,
}: {
  pkfId: number;
  record: PkfRecord;
}) {
  if (record.payload.kind === 'BMP' || record.payload.kind === 'GIF') {
    return (
      <div className="preview">
        <img
          alt={`${record.payload.kind} preview at ${record.payload_offset_hex}`}
          src={previewUrl(pkfId, record.table_index, record.slot_index)}
          loading="lazy"
        />
      </div>
    );
  }
  if (record.payload.kind === 'RIFF/PAL') {
    return <PaletteSwatch pkfId={pkfId} record={record} />;
  }
  if (record.payload.kind === 'P3D-like binary') {
    const floatSummary = p3dFloatSummary(record);
    return (
      <div className="preview p3d-preview">
        <strong>{record.payload.p3d_label ?? 'P3D'}</strong>
        <span>{record.payload.p3d_family ?? record.payload.p3d_magic_class ?? 'binary model data'}</span>
        {floatSummary && <small>{floatSummary}</small>}
      </div>
    );
  }
  return <div className="preview preview-empty">{record.payload.kind}</div>;
}

function P3DProfile({ record }: { record: PkfRecord }) {
  const payload = record.payload;
  if (payload.kind !== 'P3D-like binary') {
    return null;
  }

  return (
    <section className="p3d-profile">
      <p className="eyebrow">P3D Profile</p>
      <dl>
        <div>
          <dt>Class</dt>
          <dd>{payload.p3d_magic_class ?? 'unknown P3D variant'}</dd>
        </div>
        <div>
          <dt>Family</dt>
          <dd>{payload.p3d_family ?? 'unknown'}</dd>
        </div>
        <div>
          <dt>Size Bucket</dt>
          <dd>{payload.p3d_size_bucket ?? 'unknown'}</dd>
        </div>
        <div>
          <dt>Record Stream</dt>
          <dd>starts at byte {payload.p3d_record_start_offset ?? 'unknown'}</dd>
        </div>
        <div>
          <dt>Label</dt>
          <dd>{payload.p3d_label ?? 'none found'}</dd>
        </div>
        <div>
          <dt>Magic</dt>
          <dd>
            {payload.p3d_magic_hex ?? 'unknown'}
            {payload.p3d_marker_field_count !== null && `; decoded marker count ${payload.p3d_marker_field_count}`}
          </dd>
        </div>
        <div>
          <dt>Optional Header</dt>
          <dd>
            {payload.p3d_optional_header_flag === null
              ? 'not present'
              : `flag ${payload.p3d_optional_header_flag}; dwords ${payload.p3d_optional_header_dwords_hex?.join(' ') ?? 'none'}; floats ${payload.p3d_optional_header_floats?.map((value) => value.toFixed(4)).join(', ') ?? 'none'}`}
          </dd>
        </div>
        <div>
          <dt>First DWords</dt>
          <dd>{payload.p3d_first_dwords_hex?.join(' ') ?? 'n/a'}</dd>
        </div>
        <div>
          <dt>0x80 Chunks</dt>
          <dd>{p3dChunkSummary(record)}</dd>
        </div>
        <div>
          <dt>Inner Marker</dt>
          <dd>
            {payload.p3d_first_inner_marker_hex
              ? `${payload.p3d_first_inner_marker_hex}; decoded field count ${payload.p3d_first_inner_marker_field_count ?? 'unknown'}`
              : 'not enough data after first 0x80 object header'}
          </dd>
        </div>
        <div>
          <dt>Chunk Names</dt>
          <dd>
            {payload.p3d_chunk_name_samples?.length
              ? payload.p3d_chunk_name_samples
                .map((sample) => `#${sample.index} ${sample.offset_hex} ${sample.name}`)
                .join(' | ')
              : 'none detected in first complete chunks'}
          </dd>
        </div>
        <div>
          <dt>ASCII Runs</dt>
          <dd>
            {payload.p3d_printable_runs?.join(' | ') || 'none in first 256 bytes'}
            {payload.p3d_first_ascii_offset !== null && `; first @ ${payload.p3d_first_ascii_offset}`}
            {payload.p3d_ascii_run_count !== null && `; runs ${payload.p3d_ascii_run_count}`}
            {payload.p3d_longest_ascii_run_length !== null && `; max ${payload.p3d_longest_ascii_run_length}`}
          </dd>
        </div>
        <div>
          <dt>Float32 Scan</dt>
          <dd>{p3dFloatSummary(record) ?? 'n/a'}</dd>
        </div>
        <div>
          <dt>Zero Blocks</dt>
          <dd>{payload.p3d_zero16_block_count ?? 'n/a'} aligned 16-byte zero blocks</dd>
        </div>
        <div>
          <dt>Duplicates</dt>
          <dd>{duplicateSummary(record) ?? 'unique in loaded corpus'}</dd>
        </div>
      </dl>
    </section>
  );
}

function DetailPanel({
  selected,
  record,
}: {
  selected: PkfListItem | null;
  record: PkfRecord | null;
}) {
  if (!selected || !record) {
    return (
      <aside className="detail-panel">
        <p>Select a record to inspect its offsets, hash, descriptor bytes, and preview data.</p>
      </aside>
    );
  }

  return (
    <aside className="detail-panel">
      <p className="eyebrow">Selected Record</p>
      <h2>{selected.relative_path}</h2>
      <dl>
        <div>
          <dt>Table / Slot</dt>
          <dd>{record.table_index} / {record.slot_index}</dd>
        </div>
        <div>
          <dt>Kind</dt>
          <dd>{recordLabel(record)}</dd>
        </div>
        <div>
          <dt>Payload</dt>
          <dd>{record.payload_offset_hex} - {record.end_offset_hex} ({formatBytes(record.length)})</dd>
        </div>
        <div>
          <dt>Field</dt>
          <dd>{record.field_offset_hex}</dd>
        </div>
        <div>
          <dt>SHA-256</dt>
          <dd>{record.payload.sha256_16}</dd>
        </div>
        <div>
          <dt>Prefix</dt>
          <dd>{record.payload.prefix_hex}</dd>
        </div>
        <div>
          <dt>Descriptor</dt>
          <dd>{record.descriptor_hex ?? record.descriptor_status}</dd>
        </div>
      </dl>
      <P3DProfile record={record} />
    </aside>
  );
}

export function App() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [pkfs, setPkfs] = useState<PkfListItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<PkfDetail | null>(null);
  const [selectedRecord, setSelectedRecord] = useState<PkfRecord | null>(null);
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('');
  const [dimension, setDimension] = useState('');
  const [p3dFamily, setP3dFamily] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([fetchSummary(), fetchPkfs()])
      .then(([nextSummary, nextPkfs]) => {
        if (!active) return;
        setSummary(nextSummary);
        setPkfs(nextPkfs);
        setSelectedId(nextPkfs[0]?.id ?? null);
      })
      .catch((err: Error) => {
        if (active) setError(err.message);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (selectedId === null) {
      setDetail(null);
      return;
    }
    let active = true;
    fetchPkf(selectedId)
      .then((nextDetail) => {
        if (!active) return;
        setDetail(nextDetail);
        setSelectedRecord(nextDetail.tables[0]?.records[0] ?? null);
      })
      .catch((err: Error) => {
        if (active) setError(err.message);
      });
    return () => {
      active = false;
    };
  }, [selectedId]);

  const kinds = useMemo(() => allKinds(pkfs), [pkfs]);
  const dimensions = useMemo(() => allDimensions(pkfs), [pkfs]);
  const p3dFamilies = useMemo(() => allP3DFamilies(pkfs), [pkfs]);
  const filteredPkfs = useMemo(
    () => pkfs.filter((item) => matchesPkfFilters(item, { query, kind, dimension, p3dFamily })),
    [pkfs, query, kind, dimension, p3dFamily],
  );
  const selectedListItem = pkfs.find((item) => item.id === selectedId) ?? null;

  return (
    <main className="shell">
      <section className="hero">
        <div>
          <p className="eyebrow">PM99 SIMULDAT</p>
          <h1>PKF Viewer</h1>
          <p>
            Browse table-indexed PM99 match assets, stream image previews from local PKFs,
            and inspect the bytes without extracting files.
          </p>
        </div>
        <div className="stat-card">
          <span>{summary?.pkf_count ?? 0}</span>
          <p>PKFs scanned from {summary?.root ?? 'loading...'}</p>
        </div>
      </section>

      {error && <div className="error-banner">{error}</div>}
      {summary?.error && <div className="error-banner">{summary.error}</div>}

      <section className="workspace">
        <aside className="sidebar">
          <div className="filters">
            <input
              aria-label="Filter PKF path"
              placeholder="Filter paths..."
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <select aria-label="Filter kind" value={kind} onChange={(event) => setKind(event.target.value)}>
              <option value="">All kinds</option>
              {kinds.map((nextKind) => <option key={nextKind}>{nextKind}</option>)}
            </select>
            <select
              aria-label="Filter dimensions"
              value={dimension}
              onChange={(event) => setDimension(event.target.value)}
            >
              <option value="">All dimensions</option>
              {dimensions.map((nextDimension) => <option key={nextDimension}>{nextDimension}</option>)}
            </select>
            <select
              aria-label="Filter P3D family"
              value={p3dFamily}
              onChange={(event) => setP3dFamily(event.target.value)}
            >
              <option value="">All P3D families</option>
              {p3dFamilies.map((nextFamily) => <option key={nextFamily}>{nextFamily}</option>)}
            </select>
          </div>

          <div className="pkf-list">
            {filteredPkfs.map((item) => (
              <button
                key={item.id}
                className={item.id === selectedId ? 'pkf-item active' : 'pkf-item'}
                onClick={() => setSelectedId(item.id)}
              >
                <strong>{item.relative_path}</strong>
                <span>{item.selected_entry_count} records, {formatBytes(item.size)}</span>
              </button>
            ))}
          </div>
        </aside>

        <section className="record-area">
          {detail ? (
            <>
              <header className="file-header">
                <div>
                  <p className="eyebrow">Open PKF</p>
                  <h2>{detail.relative_path}</h2>
                </div>
                <div className="file-meta">
                  <span>{detail.selected_table_count} tables</span>
                  <span>{detail.selected_entry_count} records</span>
                  <span>{(detail.indexed_payload_coverage_ratio * 100).toFixed(2)}% indexed</span>
                </div>
              </header>

              <div className="tables">
                {detail.tables.map((table) => (
                  <section key={table.table_index} className="table-section">
                    <h3>Table {table.table_index} <span>{table.entry_count} records</span></h3>
                    <div className="record-grid">
                      {table.records.map((record) => (
                        <button
                          key={`${record.table_index}-${record.slot_index}`}
                          className={record === selectedRecord ? 'record-card active' : 'record-card'}
                          onClick={() => setSelectedRecord(record)}
                        >
                          <RecordPreview pkfId={detail === null ? 0 : selectedId ?? 0} record={record} />
                          <span>{recordLabel(record)}</span>
                          <small>{record.payload_offset_hex} / {record.length_hex}</small>
                        </button>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            </>
          ) : (
            <div className="empty-state">Loading PKF metadata...</div>
          )}
        </section>

        <DetailPanel selected={selectedListItem} record={selectedRecord} />
      </section>
    </main>
  );
}
