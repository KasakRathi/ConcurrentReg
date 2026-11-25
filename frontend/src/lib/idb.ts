// Tiny IndexedDB key-value wrapper. Every call is wrapped so that private windows, blocked storage or
// quota errors degrade to "not saved" instead of breaking the page.
const DB = "concurrentreg";
const STORE = "experiments";

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    try {
      const request = indexedDB.open(DB, 1);
      request.onupgradeneeded = () => request.result.createObjectStore(STORE);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    } catch (error) {
      reject(error);
    }
  });
}

async function run<T>(mode: IDBTransactionMode, work: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  try {
    return await new Promise<T>((resolve, reject) => {
      const request = work(db.transaction(STORE, mode).objectStore(STORE));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  } finally {
    db.close();
  }
}

export const idbPut = (key: string, value: unknown) => run("readwrite", (s) => s.put(value, key)).then(() => true).catch(() => false);
export const idbDelete = (key: string) => run("readwrite", (s) => s.delete(key)).then(() => true).catch(() => false);
export const idbClear = () => run("readwrite", (s) => s.clear()).then(() => true).catch(() => false);
export const idbAll = () => run<unknown[]>("readonly", (s) => s.getAll()).catch(() => [] as unknown[]);
