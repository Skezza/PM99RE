import type { PkfDetail, PkfListItem, PkfRecord } from './types';

export interface PkfFilters {
  query: string;
  kind: string;
  dimension: string;
  p3dFamily: string;
}

export function recordDimension(record: PkfRecord): string | null {
  const payload = record.payload;
  if (payload.kind === 'BMP' && payload.bmp_width && payload.bmp_height) {
    return `${payload.bmp_width}x${payload.bmp_height}x${payload.bmp_bpp ?? '?'}`;
  }
  if (payload.kind === 'GIF' && payload.gif_width && payload.gif_height) {
    return `${payload.gif_width}x${payload.gif_height}`;
  }
  return null;
}

export function matchesPkfFilters(item: PkfListItem, filters: PkfFilters): boolean {
  const query = filters.query.trim().toLowerCase();
  if (query && !item.relative_path.toLowerCase().includes(query)) {
    return false;
  }
  if (filters.kind && !item.payload_kind_counts[filters.kind]) {
    return false;
  }
  if (filters.dimension && !item.bmp_dimension_counts[filters.dimension]) {
    return false;
  }
  if (filters.p3dFamily && !item.p3d_family_counts[filters.p3dFamily]) {
    return false;
  }
  return true;
}

export function matchesRecordFilters(record: PkfRecord, filters: PkfFilters): boolean {
  if (filters.kind && record.payload.kind !== filters.kind) {
    return false;
  }
  if (filters.dimension && recordDimension(record) !== filters.dimension) {
    return false;
  }
  if (filters.p3dFamily && record.payload.p3d_family !== filters.p3dFamily) {
    return false;
  }
  return true;
}

export function firstRecordMatchingFilters(detail: PkfDetail, filters: PkfFilters): PkfRecord | null {
  const records = detail.tables.flatMap((table) => table.records);
  return records.find((record) => matchesRecordFilters(record, filters)) ?? records[0] ?? null;
}

export function allKinds(items: PkfListItem[]): string[] {
  return Array.from(new Set(items.flatMap((item) => Object.keys(item.payload_kind_counts)))).sort();
}

export function allDimensions(items: PkfListItem[]): string[] {
  return Array.from(new Set(items.flatMap((item) => Object.keys(item.bmp_dimension_counts)))).sort();
}

export function allP3DFamilies(items: PkfListItem[]): string[] {
  return Array.from(new Set(items.flatMap((item) => Object.keys(item.p3d_family_counts)))).sort();
}
