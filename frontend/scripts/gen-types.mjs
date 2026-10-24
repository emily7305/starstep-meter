import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { renderTypes, targets } from "./schema-types.mjs";

for (const target of targets) {
  const text = await renderTypes(target);
  await mkdir(path.dirname(target.typesPath), { recursive: true });
  await writeFile(target.typesPath, text.replace(/\r\n/g, "\n"), "utf8");
  console.log(`wrote src/types/${target.typesName}`);
}
