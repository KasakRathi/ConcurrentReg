import { describe, expect, it } from "vitest";
import { DASHBOARD_LINKS, MENUS, menuForSection, SECTION_IDS, SECTION_LINKS } from "@/components/nav/nav-data";

const DASHBOARD_ROUTES = ["/dashboard/demo", "/dashboard", "/dashboard/monitoring", "/dashboard/iasl", "/dashboard/experiments", "/dashboard/workloads", "/dashboard/architecture"];

describe("navbar data", () => {
  it("every in-page link points at a real landing-page section id", () => {
    const all = [...SECTION_LINKS, ...MENUS.flatMap((m) => m.links), ...MENUS.flatMap((m) => m.cards ?? [])];
    for (const l of all) if (l.to.startsWith("/#")) expect(SECTION_IDS, l.to).toContain(l.to.slice(2));
  });
  it("every dashboard link points at a route that exists", () => {
    const all = [...DASHBOARD_LINKS, ...MENUS.flatMap((m) => m.links), ...MENUS.flatMap((m) => m.cards ?? [])];
    for (const l of all) if (l.to.startsWith("/dashboard")) expect(DASHBOARD_ROUTES, l.to).toContain(l.to);
  });
  it("ids are unique, so palette items and React keys never collide", () => {
    const ids = [...SECTION_LINKS, ...DASHBOARD_LINKS].map((l) => l.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
  it("menu popups are wide enough to hold their content and narrow enough for a laptop", () => {
    for (const m of MENUS) { expect(m.width).toBeGreaterThanOrEqual(480); expect(m.width).toBeLessThanOrEqual(720); }
  });
  it("the scroll-spy maps sections to the menu that owns them", () => {
    expect(menuForSection("results")).toBe("product");
    expect(menuForSection("reproduce")).toBe("research");
    expect(menuForSection("facts")).toBe("research");
    expect(menuForSection(null)).toBeNull();
    expect(menuForSection("nonexistent")).toBeNull();
  });
  it("section ids exist in the landing page source", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const dir = join(__dirname, "../components/landing");
    const sources = ["RunSection", "ExperienceSection", "WorkloadsSection", "ResultsSection", "ReproduceSection", "GuaranteesSection", "ControlSection", "FactsSection", "Hero"].map((f) => readFileSync(join(dir, `${f}.tsx`), "utf8")).join("\n");
    for (const id of SECTION_IDS) expect(sources, id).toContain(`id="${id}"`);
  });
});
