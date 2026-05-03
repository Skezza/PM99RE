import { describe, expect, it } from 'vitest';
import {
  allDimensions,
  allKinds,
  allP3DFamilies,
  firstRecordMatchingFilters,
  matchesPkfFilters,
  matchesRecordFilters,
} from './filtering';
import type { PayloadInfo, PkfDetail, PkfListItem, PkfRecord } from './types';

const items: PkfListItem[] = [
  {
    id: 0,
    relative_path: 'Texturas/OTROS.pkf',
    size: 100,
    size_hex: '0x64',
    selected_table_count: 2,
    selected_entry_count: 46,
    indexed_payload_coverage_ratio: 0.99,
    payload_kind_counts: { BMP: 46 },
    bmp_dimension_counts: { '256x256x8': 21, '128x64x8': 14 },
    p3d_family_counts: {},
  },
  {
    id: 1,
    relative_path: 'Texturas/Varios/A.pkf',
    size: 200,
    size_hex: '0xc8',
    selected_table_count: 26,
    selected_entry_count: 804,
    indexed_payload_coverage_ratio: 0.99,
    payload_kind_counts: { GIF: 803, 'P3D-like binary': 1 },
    bmp_dimension_counts: {},
    p3d_family_counts: { 'fd...00-records@8': 1 },
  },
];

function payload(overrides: Partial<PayloadInfo>): PayloadInfo {
  return {
    kind: 'binary',
    prefix_hex: '',
    sha256_16: '',
    bmp_size: null,
    bmp_width: null,
    bmp_height: null,
    bmp_bpp: null,
    bmp_size_matches_record: null,
    riff_type: null,
    riff_total_size: null,
    riff_size_matches_record: null,
    gif_width: null,
    gif_height: null,
    duplicate_payload_count: null,
    p3d_magic_hex: null,
    p3d_magic_class: null,
    p3d_marker_field_count: null,
    p3d_family: null,
    p3d_label: null,
    p3d_first_ascii_offset: null,
    p3d_record_start_offset: null,
    p3d_optional_header_flag: null,
    p3d_optional_header_dwords_hex: null,
    p3d_optional_header_floats: null,
    p3d_printable_runs: null,
    p3d_ascii_run_count: null,
    p3d_longest_ascii_run_length: null,
    p3d_first_dwords_hex: null,
    p3d_first_inner_marker_hex: null,
    p3d_first_inner_marker_field_count: null,
    p3d_stream_bytes_after_header: null,
    p3d_chunk128_floor_count: null,
    p3d_chunk128_trailing_bytes: null,
    p3d_chunk128_loader_iterations: null,
    p3d_chunk_name_samples: null,
    p3d_float32_finite_sample_count: null,
    p3d_float32_plausible_sample_count: null,
    p3d_zero16_block_count: null,
    p3d_size_bucket: null,
    ...overrides,
  };
}

function record(slotIndex: number, payloadInfo: PayloadInfo): PkfRecord {
  return {
    table_index: 0,
    slot_index: slotIndex,
    field_offset: 0,
    field_offset_hex: '0x0',
    payload_offset: 0,
    payload_offset_hex: '0x0',
    length: 0,
    length_hex: '0x0',
    end_offset: 0,
    end_offset_hex: '0x0',
    flag: 1,
    descriptor_offset: 0,
    descriptor_offset_hex: '0x0',
    descriptor_size: 0,
    descriptor_status: 'missing',
    descriptor_hex: null,
    payload: payloadInfo,
  };
}

function detail(records: PkfRecord[]): PkfDetail {
  return {
    relative_path: 'mixed.pkf',
    size: 1,
    size_hex: '0x1',
    sha256_16: '',
    head32_hex: '',
    candidate_record_fields: records.length,
    selected_table_count: 1,
    selected_entry_count: records.length,
    indexed_payload_bytes_union: 0,
    indexed_payload_coverage_ratio: 1,
    tail_unindexed_bytes_after_last_indexed_payload: 0,
    payload_kind_counts: {},
    bmp_dimension_counts: {},
    p3d_family_counts: {},
    tables: [{
      table_index: 0,
      field_start_offset: 0,
      field_start_offset_hex: '0x0',
      entry_count: records.length,
      first_payload_offset: 0,
      first_payload_offset_hex: '0x0',
      last_payload_end: 0,
      last_payload_end_hex: '0x0',
      summed_payload_bytes: 0,
      payload_kind_counts: {},
      records,
    }],
  };
}

describe('filtering', () => {
  it('filters PKFs by path, kind, and dimensions', () => {
    expect(matchesPkfFilters(items[0], { query: 'otros', kind: 'BMP', dimension: '256x256x8', p3dFamily: '' })).toBe(true);
    expect(matchesPkfFilters(items[0], { query: 'varios', kind: '', dimension: '', p3dFamily: '' })).toBe(false);
    expect(matchesPkfFilters(items[1], { query: '', kind: 'BMP', dimension: '', p3dFamily: '' })).toBe(false);
    expect(matchesPkfFilters(items[1], { query: '', kind: '', dimension: '', p3dFamily: 'fd...00-records@8' })).toBe(true);
  });

  it('collects unique kinds and dimensions', () => {
    expect(allKinds(items)).toEqual(['BMP', 'GIF', 'P3D-like binary']);
    expect(allDimensions(items)).toEqual(['128x64x8', '256x256x8']);
    expect(allP3DFamilies(items)).toEqual(['fd...00-records@8']);
  });

  it('selects the first record matching active detail filters', () => {
    const first = record(0, payload({ kind: 'P3D-like binary', p3d_family: 'fd...00-records@8' }));
    const second = record(1, payload({ kind: 'P3D-like binary', p3d_family: 'fd...01-records@32' }));
    const third = record(2, payload({ kind: 'BMP', bmp_width: 640, bmp_height: 480, bmp_bpp: 8 }));
    const mixed = detail([first, second, third]);

    expect(matchesRecordFilters(second, { query: '', kind: '', dimension: '', p3dFamily: 'fd...01-records@32' })).toBe(true);
    expect(firstRecordMatchingFilters(mixed, { query: '', kind: '', dimension: '', p3dFamily: 'fd...01-records@32' })).toBe(second);
    expect(firstRecordMatchingFilters(mixed, { query: '', kind: 'BMP', dimension: '640x480x8', p3dFamily: '' })).toBe(third);
    expect(firstRecordMatchingFilters(mixed, { query: '', kind: 'GIF', dimension: '', p3dFamily: '' })).toBe(first);
  });
});
