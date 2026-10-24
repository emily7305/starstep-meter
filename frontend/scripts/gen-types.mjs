import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { renderTypes, typesPath } from "./schema-types.mjs";

const text = await renderTypes();
await mkdir(path.dirname(typesPath), { recursive: true });
await writeFile(typesPath, text.replace(/\r\n/g, "\n"), "utf8");
console.log("wrote src/types/timingReport.ts");
