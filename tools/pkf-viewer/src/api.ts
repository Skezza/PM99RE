import type { PaletteColor, PkfDetail, PkfListItem, Summary } from './types';

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export function fetchSummary(): Promise<Summary> {
  return getJson<Summary>('/api/summary');
}

export function fetchPkfs(): Promise<PkfListItem[]> {
  return getJson<PkfListItem[]>('/api/pkfs');
}

export function fetchPkf(id: number): Promise<PkfDetail> {
  return getJson<PkfDetail>(`/api/pkfs/${id}`);
}

export function previewUrl(pkfId: number, tableIndex: number, slotIndex: number): string {
  return `/api/pkfs/${pkfId}/records/${tableIndex}/${slotIndex}/preview`;
}

export async function fetchPalette(
  pkfId: number,
  tableIndex: number,
  slotIndex: number,
): Promise<PaletteColor[]> {
  const payload = await getJson<{ colors: PaletteColor[] }>(
    `/api/pkfs/${pkfId}/records/${tableIndex}/${slotIndex}/palette`,
  );
  return payload.colors;
}
