import { readFile } from "node:fs/promises";
import { renderTypes, targets } from "./schema-types.mjs";

const lf = (s) => s.replace(/\r\n/g, "\n");

let stale = false;
for (const target of targets) {
  const expected = lf(await renderTypes(target));

  let committed = null;
  try {
    committed = lf(await readFile(target.typesPath, "utf8"));
  } catch (err) {
    // missing file counts as out of date, anything else is a real problem
    if (err.code !== "ENOENT") throw err;
  }

  if (committed !== expected) {
    console.error(`src/types/${target.typesName} is out of date, run npm run gen:types`);
    stale = true;
  }
}

if (stale) process.exit(1);
console.log("types up to date");
