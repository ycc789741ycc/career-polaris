/**
 * A list endpoint's body as the API sends it when no `page_size` is asked for:
 * the whole list, on page 1 (ADR 0014). For fixtures that stand in for the API.
 */
export function page<T>(items: T[]): {
  items: T[];
  page: number;
  page_size: null;
  total: number;
} {
  return { items, page: 1, page_size: null, total: items.length };
}
