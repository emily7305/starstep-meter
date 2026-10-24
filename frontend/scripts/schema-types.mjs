import path from "node:path";
import { fileURLToPath } from "node:url";
import { compileFromFile } from "json-schema-to-typescript";

const here = path.dirname(fileURLToPath(import.meta.url));

export const schemaPath = path.resolve(here, "..", "..", "shared", "schema", "timing_report.schema.json");
export const typesPath = path.resolve(here, "..", "src", "types", "timingReport.ts");

// both scripts go through this one function so the options can't drift apart
export async function renderTypes() {
  return compileFromFile(schemaPath, {
    bannerComment:
      "/* generated from shared/schema/timing_report.schema.json by npm run gen:types, don't edit by hand */",
    cwd: path.dirname(schemaPath),
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
