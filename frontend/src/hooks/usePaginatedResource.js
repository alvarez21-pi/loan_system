import { useCallback, useEffect, useState } from "react";
import { errorMessage } from "../lib/api";

const PAGE_SIZE = 25;

/**
 * Phase 5: search + sort + server-side pagination (25/page) for the five
 * named lists. `loader(params)` must accept {page, page_size, q, sort,
 * order} and resolve to {data, pagination}. Debounces the search term
 * (300ms) so every keystroke doesn't fire a request.
 */
/**
 * @typedef {{ page: number, page_size: number, total: number, total_pages: number }} Pagination
 * @param {(params: { page: number, page_size: number, q: string|undefined, sort: string|undefined, order: "asc"|"desc" }) => Promise<{ data: any[], pagination: Pagination|null }>} loader
 * @param {any[]} [deps]
 */
export function usePaginatedResource(loader, deps = []) {
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  /** @type {[string|null, (v: string|null) => void]} */
  const [sort, setSort] = useState(null);
  /** @type {["asc"|"desc", (v: "asc"|"desc") => void]} */
  const [order, setOrder] = useState("asc");
  /** @type {[{ data: any[], pagination: Pagination|null, loading: boolean, error: string }, Function]} */
  const [state, setState] = useState({ data: [], pagination: null, loading: true, error: "" });

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQ(q), 300);
    return () => clearTimeout(timer);
  }, [q]);

  useEffect(() => {
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ, sort, order, ...deps]);

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: "" }));
    try {
      const result = await loader({ page, page_size: PAGE_SIZE, q: debouncedQ || undefined, sort: sort || undefined, order });
      setState({ data: result.data || [], pagination: result.pagination || null, loading: false, error: "" });
    } catch (error) {
      setState({ data: [], pagination: null, loading: false, error: errorMessage(error) });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, debouncedQ, sort, order, ...deps]);

  useEffect(() => {
    load();
  }, [load]);

  function toggleSort(column) {
    if (sort === column) {
      setOrder((o) => (o === "asc" ? "desc" : "asc"));
    } else {
      setSort(column);
      setOrder("asc");
    }
  }

  return { ...state, page, setPage, q, setQ, sort, order, toggleSort, pageSize: PAGE_SIZE, reload: load };
}

export default usePaginatedResource;
