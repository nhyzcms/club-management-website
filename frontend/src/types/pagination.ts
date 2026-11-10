// 列表分页信封（与 DRF PageNumberPagination 对齐）。所有列表 API 应返回此形状。
export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
