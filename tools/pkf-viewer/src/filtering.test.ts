import { describe, expect, it } from 'vitest';
import { allDimensions, allKinds, allP3DFamilies, matchesPkfFilters } from './filtering';
import type { PkfListItem } from './types';

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
});
