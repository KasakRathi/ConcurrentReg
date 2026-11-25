// Renders the landing-page videos and background images from scene.html.
//   node scripts/render-media/render.mjs still <scene> <t 0..1> <out.png>   one frame, for previewing
//   node scripts/render-media/render.mjs all [clip ...]                       every clip (or only the named ones) + posters + images into public/media
// Needs: Playwright (set PLAYWRIGHT_MODULE to its index.mjs if it is not installed here) and ffmpeg on PATH.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.resolve(here, "../../public/media");
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? "playwright");

const CLIPS = { hero: { frames: 300, fps: 30 }, cli: { frames: 120, fps: 30 }, schedule: { frames: 120, fps: 30 }, seed: { frames: 120, fps: 30 }, ring: { frames: 120, fps: 30 } };
const IMAGES = ["floor", "rays"];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1000, height: 1000 } });
await page.goto(pathToFileURL(path.join(here, "scene.html")).href);
const grab = async (name, t) => Buffer.from((await page.evaluate(([n, tt]) => window.drawScene(n, tt), [name, t])).split(",")[1], "base64");

const mode = process.argv[2];
if (mode === "still") {
  const [, , , name, t, out] = process.argv;
  fs.writeFileSync(out, await grab(name, Number(t)));
  console.log("wrote", out);
} else if (mode === "all") {
  fs.mkdirSync(outDir, { recursive: true });
  const only = process.argv.slice(3);
  for (const [name, { frames, fps }] of Object.entries(CLIPS)) {
    if (only.length && !only.includes(name)) continue;
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), `creg-${name}-`));
    for (let i = 0; i < frames; i++) fs.writeFileSync(path.join(tmp, `f${String(i).padStart(4, "0")}.png`), await grab(name, i / frames));
    const mp4 = path.join(outDir, `${name}.mp4`);
    const scale = name === "hero" ? ["-vf", "scale=720:720"] : []; // the hero is rendered at 960 px and shipped at 720 px (grain is costly to compress)
    execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-framerate", String(fps), "-i", path.join(tmp, "f%04d.png"), ...scale, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", name === "hero" ? "29" : "24", "-preset", "slow", "-movflags", "+faststart", "-an", mp4]);
    // WebM first (plays everywhere, including Chromium builds without H.264), MP4 as the Safari/iOS fallback.
    const webm = path.join(outDir, `${name}.webm`);
    execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-framerate", String(fps), "-i", path.join(tmp, "f%04d.png"), ...scale, "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-b:v", "0", "-crf", name === "hero" ? "48" : "36", "-row-mt", "1", "-an", webm]);
    execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", path.join(tmp, "f0000.png"), "-q:v", "3", path.join(outDir, `${name}-poster.jpg`)]);
    fs.rmSync(tmp, { recursive: true, force: true });
    console.log(name, (fs.statSync(mp4).size / 1024).toFixed(0), "KB");
  }
  for (const name of IMAGES) {
    const tmp = path.join(os.tmpdir(), `creg-${name}.png`);
    fs.writeFileSync(tmp, await grab(name, 0));
    execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", tmp, "-q:v", "4", path.join(outDir, `${name}.jpg`)]);
    console.log(name, "image");
  }
} else console.log("usage: still <scene> <t> <out.png> | all");
await browser.close();
