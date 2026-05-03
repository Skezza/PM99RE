import { useEffect, useMemo, useState } from 'react';
import { fetchMenuAtlas, fetchPalette, fetchPkf, fetchPkfs, fetchSummary, previewUrl } from './api';
import {
  allDimensions,
  allKinds,
  allP3DFamilies,
  firstRecordMatchingFilters,
  matchesPkfFilters,
  matchesRecordFilters,
  recordDimension,
} from './filtering';
import type { PaletteColor, PkfDetail, PkfListItem, PkfRecord, Summary } from './types';
import type { MenuAsset, MenuAtlas } from './types';

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

function assetGroupId(path: string): string {
  return `asset-group-${path.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
}

function assetDimension(asset: MenuAsset): string {
  if (asset.width === null || asset.height === null) {
    return asset.kind;
  }
  return asset.bpp === null
    ? `${asset.width}x${asset.height}`
    : `${asset.width}x${asset.height}x${asset.bpp}`;
}

function isLowInformationAsset(asset: MenuAsset): boolean {
  return asset.visual_quality === 'low-information';
}

function assetQualityLabel(asset: MenuAsset): string {
  if (asset.visual_quality === 'low-information') {
    return 'Mask / blank-like';
  }
  if (asset.visual_quality === 'dark-control') {
    return 'Dark control';
  }
  if (asset.visual_quality === 'unknown') {
    return 'Unscored image';
  }
  return 'Visible artwork';
}

function assetStats(asset: MenuAsset): string | null {
  if (
    asset.mean_luminance === null
    || asset.near_black_ratio === null
    || asset.unique_color_count === null
  ) {
    return null;
  }
  return `luma ${asset.mean_luminance.toFixed(1)} · black ${(asset.near_black_ratio * 100).toFixed(1)}% · ${asset.unique_color_count} colors`;
}

function MenuAssetCard({
  asset,
  onOpen,
}: {
  asset: MenuAsset;
  onOpen: (asset: MenuAsset) => void;
}) {
  const stats = assetStats(asset);
  return (
    <button className={`atlas-card ${asset.visual_quality}`} onClick={() => onOpen(asset)}>
      <div className={asset.width === 640 && asset.height === 480 ? 'atlas-preview atlas-preview-wide' : 'atlas-preview'}>
        <img
          alt={`${asset.pkf_path} table ${asset.table_index} slot ${asset.slot_index}`}
          src={previewUrl(asset.pkf_id, asset.table_index, asset.slot_index)}
          loading="lazy"
        />
      </div>
      <strong>{asset.label}</strong>
      <span className={`asset-quality ${asset.visual_quality}`}>{assetQualityLabel(asset)}</span>
      <span>{asset.role}</span>
      <code>{asset.pkf_path}</code>
      <code>table {asset.table_index}, slot {asset.slot_index} · {asset.payload_offset_hex}</code>
      <code>{assetDimension(asset)} · {asset.length_hex} · {asset.sha256_16}</code>
      {asset.palette_source && <code>palette: {asset.palette_source}</code>}
      {stats && <code>{stats}</code>}
      <span className="asset-open-hint">Open exact record</span>
    </button>
  );
}

function MenuAtlasView({
  atlas,
  onOpenAsset,
}: {
  atlas: MenuAtlas | null;
  onOpenAsset: (asset: MenuAsset) => void;
}) {
  const [showLowInformation, setShowLowInformation] = useState(false);

  if (!atlas) {
    return <div className="empty-state">Loading menu atlas...</div>;
  }

  const lowInformationCount = atlas.asset_groups.reduce(
    (total, group) => total + group.records.filter(isLowInformationAsset).length,
    0,
  );
  const displayedAssetCount = showLowInformation
    ? atlas.asset_count
    : atlas.asset_count - lowInformationCount;

  return (
    <section className="menu-atlas">
      <header className="atlas-header">
        <div>
          <p className="eyebrow">Runtime Discovery</p>
          <h2>PM99 Menu Assets</h2>
          <p>
            These are the source bitmap/GIF records from the UI PKFs. No runner screenshots are shown here:
            each card is an asset candidate you can inspect and target for replacement work. Blank-like masks
            and near-black state images are hidden by default so actual editable artwork is easier to find.
          </p>
          <div className="atlas-controls">
            <button
              type="button"
              onClick={() => setShowLowInformation((value) => !value)}
            >
              {showLowInformation ? 'Hide mask / blank-like records' : `Show ${lowInformationCount} mask / blank-like records`}
            </button>
          </div>
        </div>
        <div className="atlas-metrics">
          <span>{displayedAssetCount} shown assets</span>
          <span>{lowInformationCount} mask-like hidden</span>
          <span>{atlas.asset_groups.filter((group) => !group.missing).length} source PKFs</span>
        </div>
      </header>

      <nav className="asset-index" aria-label="Menu asset groups">
        {atlas.asset_groups.map((group) => {
          const shownRecords = showLowInformation
            ? group.records
            : group.records.filter((asset) => !isLowInformationAsset(asset));
          return (
            <a key={group.path} href={`#${assetGroupId(group.path)}`}>
              {group.title}
              <span>{shownRecords.length}/{group.records.length}</span>
            </a>
          );
        })}
      </nav>

      {atlas.asset_groups.map((group) => {
        const shownRecords = showLowInformation
          ? group.records
          : group.records.filter((asset) => !isLowInformationAsset(asset));
        const hiddenRecords = group.records.length - shownRecords.length;
        return (
          <section key={group.path} id={assetGroupId(group.path)} className="atlas-section">
            <h3>
              {group.title}
              <span>{shownRecords.length} shown / {group.records.length} total</span>
            </h3>
            <p>
              {group.missing ? `Missing ${group.path} from the current scan root.` : group.description}
              {!showLowInformation && hiddenRecords > 0 && ` ${hiddenRecords} mask/blank-like records hidden.`}
            </p>
            {shownRecords.length > 0 ? (
              <div className="atlas-grid">
                {shownRecords.map((asset) => (
                  <MenuAssetCard
                    key={`${asset.pkf_id}-${asset.table_index}-${asset.slot_index}`}
                    asset={asset}
                    onOpen={onOpenAsset}
                  />
                ))}
              </div>
            ) : (
              <div className="empty-state">No visible candidates in this group with the current mask filter.</div>
            )}
          </section>
        );
      })}
    </section>
  );
}

export function App() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [pkfs, setPkfs] = useState<PkfListItem[]>([]);
  const [menuAtlas, setMenuAtlas] = useState<MenuAtlas | null>(null);
  const [view, setView] = useState<'pkfs' | 'menus'>('pkfs');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<PkfDetail | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [selectedRecord, setSelectedRecord] = useState<PkfRecord | null>(null);
  const [pendingRecordTarget, setPendingRecordTarget] = useState<{
    pkfId: number;
    tableIndex: number;
    slotIndex: number;
  } | null>(null);
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('');
  const [dimension, setDimension] = useState('');
  const [p3dFamily, setP3dFamily] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([fetchSummary(), fetchPkfs(), fetchMenuAtlas()])
      .then(([nextSummary, nextPkfs, nextMenuAtlas]) => {
        if (!active) return;
        setSummary(nextSummary);
        setPkfs(nextPkfs);
        setMenuAtlas(nextMenuAtlas);
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
      setDetailId(null);
      setSelectedRecord(null);
      return;
    }
    let active = true;
    setDetail(null);
    setDetailId(null);
    setSelectedRecord(null);
    fetchPkf(selectedId)
      .then((nextDetail) => {
        if (!active) return;
        setDetail(nextDetail);
        setDetailId(selectedId);
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
  const activeFilters = useMemo(
    () => ({ query, kind, dimension, p3dFamily }),
    [query, kind, dimension, p3dFamily],
  );
  const filteredPkfs = useMemo(
    () => pkfs.filter((item) => matchesPkfFilters(item, activeFilters)),
    [pkfs, activeFilters],
  );
  const activeDetail = detailId === selectedId ? detail : null;
  const activeRecord = activeDetail ? selectedRecord : null;
  const selectedListItem = pkfs.find((item) => item.id === selectedId) ?? null;

  useEffect(() => {
    if (!activeDetail || pendingRecordTarget?.pkfId !== detailId) {
      return;
    }
    const targetRecord = activeDetail.tables
      .flatMap((table) => table.records)
      .find(
        (record) => record.table_index === pendingRecordTarget.tableIndex
          && record.slot_index === pendingRecordTarget.slotIndex,
      );
    if (!targetRecord) {
      return;
    }
    setSelectedRecord(targetRecord);
    setPendingRecordTarget(null);
  }, [activeDetail, detailId, pendingRecordTarget]);

  useEffect(() => {
    if (filteredPkfs.length === 0) {
      if (selectedId !== null) {
        setSelectedId(null);
      }
      return;
    }
    if (!filteredPkfs.some((item) => item.id === selectedId)) {
      setSelectedId(filteredPkfs[0].id);
    }
  }, [filteredPkfs, selectedId]);

  useEffect(() => {
    if (!activeDetail) {
      return;
    }
    if (activeRecord && matchesRecordFilters(activeRecord, activeFilters)) {
      return;
    }
    setSelectedRecord(firstRecordMatchingFilters(activeDetail, activeFilters));
  }, [activeDetail, activeRecord, activeFilters]);

  return (
    <main className="shell">
      <section className="hero">
        <div>
          <p className="eyebrow">PM99 Assets</p>
          <h1>{view === 'menus' ? 'Menu Atlas' : 'PKF Viewer'}</h1>
          <p>
            {view === 'menus'
              ? 'Browse the actual menu backgrounds, button strips, resource sprites, layout strips, and icons from the PKFs, with exact table/slot targets for replacement work.'
              : 'Browse table-indexed PM99 assets, stream image previews from local PKFs, and inspect the bytes without extracting files.'}
          </p>
          <div className="view-tabs" aria-label="Viewer mode">
            <button className={view === 'pkfs' ? 'active' : ''} onClick={() => setView('pkfs')}>PKF Records</button>
            <button className={view === 'menus' ? 'active' : ''} onClick={() => setView('menus')}>Menu Atlas</button>
          </div>
        </div>
        <div className="stat-card">
          <span>{view === 'menus' ? menuAtlas?.asset_count ?? 0 : summary?.pkf_count ?? 0}</span>
          <p>{view === 'menus' ? 'menu bitmap records surfaced' : `PKFs scanned from ${summary?.root ?? 'loading...'}`}</p>
        </div>
      </section>

      {error && <div className="error-banner">{error}</div>}
      {summary?.error && <div className="error-banner">{summary.error}</div>}

      {view === 'menus' ? (
        <MenuAtlasView
          atlas={menuAtlas}
          onOpenAsset={(asset) => {
            setPendingRecordTarget({
              pkfId: asset.pkf_id,
              tableIndex: asset.table_index,
              slotIndex: asset.slot_index,
            });
            setSelectedId(asset.pkf_id);
            setView('pkfs');
          }}
        />
      ) : (
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
          {activeDetail ? (
            <>
              <header className="file-header">
                <div>
                  <p className="eyebrow">Open PKF</p>
                  <h2>{activeDetail.relative_path}</h2>
                </div>
                <div className="file-meta">
                  <span>{activeDetail.selected_table_count} tables</span>
                  <span>{activeDetail.selected_entry_count} records</span>
                  <span>{(activeDetail.indexed_payload_coverage_ratio * 100).toFixed(2)}% indexed</span>
                </div>
              </header>

              <div className="tables">
                {activeDetail.tables.map((table) => (
                  <section key={table.table_index} className="table-section">
                    <h3>Table {table.table_index} <span>{table.entry_count} records</span></h3>
                    <div className="record-grid">
                      {table.records.map((record) => (
                        <button
                          key={`${record.table_index}-${record.slot_index}`}
                          className={record === activeRecord ? 'record-card active' : 'record-card'}
                          onClick={() => setSelectedRecord(record)}
                        >
                          <RecordPreview pkfId={detailId ?? 0} record={record} />
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

        <DetailPanel selected={selectedListItem} record={activeRecord} />
      </section>
      )}
    </main>
  );
}
