import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { CODE_FILES, PRESET_PATCHES, SERVER_VARIANTS } from "./landing-data";
import { buildCommand, DEFAULT_CONFIG } from "./command";
import { validateConfig } from "./schedule";

const root = path.resolve(__dirname, "../../..");

describe("landing code excerpts are exact copies of the repository", () => {
  for (const f of CODE_FILES) {
    it(`${f.path}`, () => {
      const source = readFileSync(path.join(root, f.path), "utf8");
      // Excerpts are written with the file's own indentation; compare line by line, ignoring trailing spaces.
      const norm = (t: string) => t.split("\n").map((l) => l.replace(/\s+$/, "")).join("\n");
      expect(norm(source)).toContain(norm(f.code));
    });
  }
});

describe("landing presets", () => {
  for (const p of PRESET_PATCHES) {
    it(`${p.id}: the generator's validation would accept it, and the command carries the preset's flags`, () => {
      const cfg = { ...DEFAULT_CONFIG, ...p.patch };
      expect(validateConfig(cfg)).toEqual([]);
      expect(buildCommand(cfg)).toContain("workload.workload_generator");
    });
  }
  it("server variants are whole numbers of at least 1 (as OSLayerConfig requires)", () => {
    for (const v of SERVER_VARIANTS) for (const n of [v.q, v.w, v.p]) expect(Number.isInteger(n) && n >= 1).toBe(true);
  });
});
