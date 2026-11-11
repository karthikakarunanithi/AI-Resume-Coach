// Copies the Silero VAD model, its audio worklet and the ONNX Runtime WASM files into public/vad/,
// so the browser loads them from our own origin instead of a CDN. Runs before `dev` and `build`.
import { copyFileSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "vad");
mkdirSync(out, { recursive: true });

const sources = [
  [join(root, "node_modules/@ricky0123/vad-web/dist"), (f) => f === "silero_vad_v5.onnx" || f === "vad.worklet.bundle.min.js"],
  [join(root, "node_modules/onnxruntime-web/dist"), (f) => /^ort-wasm.*\.(wasm|mjs)$/.test(f)],
];
let n = 0;
for (const [dir, keep] of sources) {
  for (const f of readdirSync(dir).filter(keep)) {
    copyFileSync(join(dir, f), join(out, f));
    n++;
  }
}
console.log(`copied ${n} VAD assets to public/vad/`);
