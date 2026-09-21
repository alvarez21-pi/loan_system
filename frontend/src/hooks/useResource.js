import { useCallback, useEffect, useState } from "react";
import { errorMessage } from "../lib/api";

/**
 * Loads a list/detail resource from the API helper.
 * The loader must resolve to { data }.
 */
export function useResource(loader, deps = []) {
  const [state, setState] = useState({ data: null, loading: true, error: "" });

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: "" }));
    try {
      const result = await loader();
      setState({ data: result.data, loading: false, error: "" });
    } catch (error) {
      setState({ data: null, loading: false, error: errorMessage(error) });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    load();
  }, [load]);

  return { ...state, reload: load };
}

export default useResource;
