import { Activity, BarChart3, Boxes, FlaskConical, Gauge, PlayCircle, Radar, Scale, ShieldCheck, SlidersHorizontal, Terminal, type LucideIcon } from "lucide-react";

/** Every destination the navbar, the mobile sheet and the command palette link to. Section ids exist on the landing page. */
export interface NavLinkDef {
  id: string;
  label: string;
  desc: string;
  to: string;
  Icon: LucideIcon;
}

export interface NavCardDef {
  id: string;
  title: string;
  desc: string;
  to: string;
  poster: string;
}

export interface NavMenuDef {
  id: string;
  label: string;
  /** Width of the popup in px (needed to keep it inside the window while it follows its trigger). */
  width: number;
  links: NavLinkDef[];
  cards?: NavCardDef[];
  /** Landing-page section ids that belong to this menu (for the scroll-spy dot). */
  sections?: string[];
}

export const SECTION_LINKS: NavLinkDef[] = [
  { id: "run", label: "Run an experiment", desc: "Seeded workloads and the exact command", to: "/#run", Icon: Terminal },
  { id: "workloads", label: "Configure workloads", desc: "Preview the schedule before sending", to: "/#workloads", Icon: SlidersHorizontal },
  { id: "results", label: "Read the results", desc: "Rates, percentiles and validity", to: "/#results", Icon: BarChart3 },
  { id: "guarantees", label: "Guarantees", desc: "What the database enforces", to: "/#guarantees", Icon: ShieldCheck },
  { id: "reproduce", label: "Reproducibility", desc: "Seeds, real excerpts and tests", to: "/#reproduce", Icon: FlaskConical },
  { id: "control", label: "Architecture and measurement", desc: "Explore the pipeline in place", to: "/#control", Icon: Boxes },
  { id: "facts", label: "Claims and limits", desc: "What is and is not established", to: "/#facts", Icon: Scale },
];

export const DASHBOARD_LINKS: NavLinkDef[] = [
  { id: "d-demo", label: "Live demo", desc: "Run it for real, check the database, run the tests", to: "/dashboard/demo", Icon: PlayCircle },
  { id: "d-overview", label: "Overview", desc: "Live counters and the selected run", to: "/dashboard", Icon: Gauge },
  { id: "d-monitoring", label: "Monitoring", desc: "Queue, workers and semaphore over time", to: "/dashboard/monitoring", Icon: Activity },
  { id: "d-iasl", label: "IASL", desc: "Adaptive admission limit, system state and every decision", to: "/dashboard/iasl", Icon: Radar },
  { id: "d-experiments", label: "Experiments", desc: "Import, compare and export runs", to: "/dashboard/experiments", Icon: FlaskConical },
  { id: "d-workloads", label: "Workloads", desc: "Validate settings, build commands", to: "/dashboard/workloads", Icon: SlidersHorizontal },
  { id: "d-architecture", label: "Architecture", desc: "Stage by stage, with live values", to: "/dashboard/architecture", Icon: Boxes },
];

const byId = (ids: string[]) => ids.map((id) => SECTION_LINKS.find((l) => l.id === id)!);

export const MENUS: NavMenuDef[] = [
  {
    id: "product",
    label: "Product",
    width: 640,
    links: byId(["run", "workloads", "results", "guarantees"]),
    sections: ["run", "experience", "workloads", "results", "guarantees"],
    cards: [
      { id: "c-builder", title: "Workload builder", desc: "Validate and preview", to: "/dashboard/workloads", poster: "/media/schedule-poster.jpg" },
      { id: "c-runs", title: "Experiments", desc: "Import and compare", to: "/dashboard/experiments", poster: "/media/cli-poster.jpg" },
    ],
  },
  {
    id: "research",
    label: "Research",
    width: 600,
    links: byId(["reproduce", "control", "facts"]),
    sections: ["reproduce", "control", "facts"],
    cards: [
      { id: "c-repro", title: "Reproduce every run", desc: "Seeds and excerpts", to: "/#reproduce", poster: "/media/seed-poster.jpg" },
      { id: "c-arch", title: "Live architecture", desc: "Stage by stage", to: "/dashboard/architecture", poster: "/media/ring-poster.jpg" },
    ],
  },
  { id: "dashboard", label: "Dashboard", width: 600, links: DASHBOARD_LINKS },
];

/** Landing-page section ids in page order, for the scroll-spy. */
export const SECTION_IDS = ["run", "experience", "workloads", "results", "reproduce", "guarantees", "control", "facts"];

export function menuForSection(sectionId: string | null): string | null {
  if (!sectionId) return null;
  return MENUS.find((m) => m.sections?.includes(sectionId))?.id ?? null;
}
