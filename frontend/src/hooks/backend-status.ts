import { useEffect, useState } from "react";
import { fetchOsLayerStatus } from "@/lib/api";
import type { OsLayerStatus } from "@/lib/types";

export interface BackendStatus {
  /** null until the first answer (or failure) arrives. */
  online: boolean | null;
  status: OsLayerStatus | null;
}

/** One honest check of GET /os-layer/status on mount and then every `everyMs`. Never fabricates a value. */
export function useBackendStatus(everyMs = 20000): BackendStatus {
  const [state, setState] = useState<BackendStatus>({ online: null, status: null });
  useEffect(() => {
    let live = true;
    const check = () =>
      fetchOsLayerStatus(undefined, 2500).then(
        (status) => live && setState({ online: true, status }),
        () => live && setState({ online: false, status: null }),
      );
    void check();
    const id = setInterval(check, everyMs);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, [everyMs]);
  return state;
}
