export interface Summary {
  root: string;
  exists: boolean;
  error: string | null;
  pkf_count: number;
  total_bytes: number;
  table_count: number;
  entry_count: number;
  payload_kind_counts: Record<string, number>;
  p3d_family_counts: Record<string, number>;
}

export interface PkfListItem {
  id: number;
  relative_path: string;
  size: number;
  size_hex: string;
  selected_table_count: number;
  selected_entry_count: number;
  indexed_payload_coverage_ratio: number;
  payload_kind_counts: Record<string, number>;
  bmp_dimension_counts: Record<string, number>;
  p3d_family_counts: Record<string, number>;
}

export interface PayloadInfo {
  kind: string;
  prefix_hex: string;
  sha256_16: string;
  bmp_size: number | null;
  bmp_width: number | null;
  bmp_height: number | null;
  bmp_bpp: number | null;
  bmp_size_matches_record: boolean | null;
  riff_type: string | null;
  riff_total_size: number | null;
  riff_size_matches_record: boolean | null;
  gif_width: number | null;
  gif_height: number | null;
  duplicate_payload_count: number | null;
  p3d_magic_hex: string | null;
  p3d_magic_class: string | null;
  p3d_marker_field_count: number | null;
  p3d_family: string | null;
  p3d_label: string | null;
  p3d_first_ascii_offset: number | null;
  p3d_record_start_offset: number | null;
  p3d_optional_header_flag: number | null;
  p3d_optional_header_dwords_hex: string[] | null;
  p3d_optional_header_floats: number[] | null;
  p3d_printable_runs: string[] | null;
  p3d_ascii_run_count: number | null;
  p3d_longest_ascii_run_length: number | null;
  p3d_first_dwords_hex: string[] | null;
  p3d_first_inner_marker_hex: string | null;
  p3d_first_inner_marker_field_count: number | null;
  p3d_stream_bytes_after_header: number | null;
  p3d_chunk128_floor_count: number | null;
  p3d_chunk128_trailing_bytes: number | null;
  p3d_chunk128_loader_iterations: number | null;
  p3d_chunk_name_samples: P3DChunkName[] | null;
  p3d_float32_finite_sample_count: number | null;
  p3d_float32_plausible_sample_count: number | null;
  p3d_zero16_block_count: number | null;
  p3d_size_bucket: string | null;
}

export interface P3DChunkName {
  index: number;
  offset: number;
  offset_hex: string;
  name: string;
}

export interface PkfRecord {
  table_index: number;
  slot_index: number;
  field_offset: number;
  field_offset_hex: string;
  payload_offset: number;
  payload_offset_hex: string;
  length: number;
  length_hex: string;
  end_offset: number;
  end_offset_hex: string;
  flag: number;
  descriptor_offset: number;
  descriptor_offset_hex: string;
  descriptor_size: number;
  descriptor_status: string;
  descriptor_hex: string | null;
  payload: PayloadInfo;
}

export interface PkfTable {
  table_index: number;
  field_start_offset: number;
  field_start_offset_hex: string;
  entry_count: number;
  first_payload_offset: number;
  first_payload_offset_hex: string;
  last_payload_end: number;
  last_payload_end_hex: string;
  summed_payload_bytes: number;
  payload_kind_counts: Record<string, number>;
  records: PkfRecord[];
}

export interface PkfDetail {
  relative_path: string;
  size: number;
  size_hex: string;
  sha256_16: string;
  head32_hex: string;
  candidate_record_fields: number;
  selected_table_count: number;
  selected_entry_count: number;
  indexed_payload_bytes_union: number;
  indexed_payload_coverage_ratio: number;
  tail_unindexed_bytes_after_last_indexed_payload: number;
  payload_kind_counts: Record<string, number>;
  bmp_dimension_counts: Record<string, number>;
  p3d_family_counts: Record<string, number>;
  tables: PkfTable[];
}

export interface PaletteColor {
  index: number;
  r: number;
  g: number;
  b: number;
  flags: number;
}
