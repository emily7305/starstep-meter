import { readFile } from "node:fs/promises";
import { renderTypes, typesPath } from "./schema-types.mjs";

const lf = (s) => s.replace(/\r\n/g, "\n");

const expected = lf(await renderTypes());

let committed = null;
try {
  committed = lf(await readFile(typesPath, "utf8"));
} catch (err) {
  // missing file counts as out of date, anything else is a real problem
  if (err.code !== "ENOENT") throw err;
}

if (committed !== expected) {
  console.error("src/types/timingReport.ts is out of date, run npm run gen:types");
  process.exit(1);
}
console.log("types up to date");
