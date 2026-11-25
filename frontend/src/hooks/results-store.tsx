import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { idbAll, idbClear, idbDelete, idbPut } from "@/lib/idb";
import { parseExperiment, ResultParseError } from "@/lib/results";
import type { ExperimentResult } from "@/lib/types";

export interface StoredExperiment {
  exp: ExperimentResult;
  fileName: string;
  importedAt: string;
}

export interface ImportReport {
  fileName: string;
  ok: boolean;
  message: string;
  id?: string;
}

interface Store {
  items: StoredExperiment[];
  ready: boolean;
  persisted: boolean; // false when the browser refused to save (private window, blocked storage)
  selectedId: string | null;
  select: (id: string | null) => void;
  get: (id: string | null | undefined) => StoredExperiment | undefined;
  importFiles: (files: File[]) => Promise<ImportReport[]>;
  /** Add an already-parsed experiment (for example one fetched from the server) and select it. */
  addExperiment: (exp: ExperimentResult, fileName: string) => Promise<void>;
  remove: (id: string) => void;
  clear: () => void;
}

const Ctx = createContext<Store | null>(null);
const MAX_FILE_BYTES = 60 * 1024 * 1024;

export function ResultsProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<StoredExperiment[]>([]);
  const [ready, setReady] = useState(false);
  const [persisted, setPersisted] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    idbAll().then((rows) => {
      if (!live) return;
      const valid = (rows as StoredExperiment[]).filter((r) => r && r.exp && typeof r.exp.experiment_id === "string");
      valid.sort((a, b) => b.importedAt.localeCompare(a.importedAt));
      setItems(valid);
      setSelectedId((current) => current ?? valid[0]?.exp.experiment_id ?? null);
      setReady(true);
    });
    return () => {
      live = false;
    };
  }, []);

  const importFiles = useCallback(async (files: File[]) => {
    const reports: ImportReport[] = [];
    const added: StoredExperiment[] = [];
    for (const file of files) {
      if (file.size > MAX_FILE_BYTES) {
        reports.push({ fileName: file.name, ok: false, message: `File is larger than ${MAX_FILE_BYTES / 1024 / 1024} MB.` });
        continue;
      }
      try {
        const exp = parseExperiment(await file.text());
        added.push({ exp, fileName: file.name, importedAt: new Date().toISOString() });
        reports.push({ fileName: file.name, ok: true, message: `${exp.results.length.toLocaleString("en-US")} request records`, id: exp.experiment_id });
      } catch (error) {
        reports.push({ fileName: file.name, ok: false, message: error instanceof ResultParseError ? error.message : "Could not read this file." });
      }
    }
    if (added.length > 0) {
      for (const item of added) {
        const saved = await idbPut(item.exp.experiment_id, item);
        if (!saved) setPersisted(false);
      }
      setItems((current) => {
        const ids = new Set(added.map((a) => a.exp.experiment_id));
        return [...added, ...current.filter((c) => !ids.has(c.exp.experiment_id))];
      });
      setSelectedId(added[0].exp.experiment_id);
    }
    return reports;
  }, []);

  const addExperiment = useCallback(async (exp: ExperimentResult, fileName: string) => {
    const item: StoredExperiment = { exp, fileName, importedAt: new Date().toISOString() };
    if (!(await idbPut(exp.experiment_id, item))) setPersisted(false);
    setItems((current) => [item, ...current.filter((c) => c.exp.experiment_id !== exp.experiment_id)]);
    setSelectedId(exp.experiment_id);
  }, []);

  const remove = useCallback((id: string) => {
    void idbDelete(id);
    setItems((current) => current.filter((c) => c.exp.experiment_id !== id));
    setSelectedId((current) => (current === id ? null : current));
  }, []);

  const clear = useCallback(() => {
    void idbClear();
    setItems([]);
    setSelectedId(null);
  }, []);

  const value = useMemo<Store>(
    () => ({
      items,
      ready,
      persisted,
      selectedId: selectedId && items.some((i) => i.exp.experiment_id === selectedId) ? selectedId : (items[0]?.exp.experiment_id ?? null),
      select: setSelectedId,
      get: (id) => (id ? items.find((i) => i.exp.experiment_id === id) : undefined),
      importFiles,
      addExperiment,
      remove,
      clear,
    }),
    [items, ready, persisted, selectedId, importFiles, addExperiment, remove, clear],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useResults(): Store {
  const value = useContext(Ctx);
  if (!value) throw new Error("useResults must be used inside <ResultsProvider>");
  return value;
}
