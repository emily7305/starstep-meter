import path from "node:path";
import { fileURLToPath } from "node:url";
import { compileFromFile } from "json-schema-to-typescript";

const here = path.dirname(fileURLToPath(import.meta.url));
const schemaDir = path.resolve(here, "..", "..", "shared", "schema");
const typesDir = path.resolve(here, "..", "src", "types");

// one entry per committed json schema, both scripts loop over this list
export const targets = [
  { schema: "timing_report.schema.json", types: "timingReport.ts" },
  { schema: "beats.schema.json", types: "beats.ts" },
  { schema: "timing_export.schema.json", types: "timingExport.ts" },
  { schema: "sonolus_export.schema.json", types: "sonolusExport.ts" },
].map((t) => ({
  schemaPath: path.join(schemaDir, t.schema),
  typesPath: path.join(typesDir, t.types),
  schemaName: t.schema,
  typesName: t.types,
}));

// both scripts go through this one function so the options can't drift apart
export async function renderTypes(target) {
  return compileFromFile(target.schemaPath, {
    bannerComment: `/* generated from shared/schema/${target.schemaName} by npm run gen:types, don't edit by hand */`,
    cwd: schemaDir,
    // JsonValue is an empty schema, unknown is the honest type for it
    unknownAny: true,
    additionalProperties: false,
    strictIndexSignatures: true,
    // prettier options pinned here so a stray config file can't change the output
    style: {
      bracketSpacing: false,
      printWidth: 100,
      semi: true,
      singleQuote: false,
      tabWidth: 2,
      trailingComma: "none",
      useTabs: false,
      endOfLine: "lf",
    },
  });
}
