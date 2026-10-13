import { cpSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import process from "node:process";

const source = join(process.cwd(), "node_modules", "pdfjs-dist");
const target = join(process.cwd(), "public", "pdfjs");
mkdirSync(target, { recursive: true });
cpSync(join(source, "build", "pdf.worker.min.mjs"), join(target, "pdf.worker.min.mjs"));
for (const folder of ["cmaps", "standard_fonts", "wasm"]) {
  cpSync(join(source, folder), join(target, folder), { recursive: true });
}
cpSync(join(source, "LICENSE"), join(target, "LICENSE"));
