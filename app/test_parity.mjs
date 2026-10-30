// Parity test: the JavaScript predictor must match the Python model on the cases written by src/modeling/export.py.
import { readFileSync } from "node:fs";
import { parts, predictLogPpm2 } from "./model.js";

const dir = new URL(".", import.meta.url);
const model = JSON.parse(readFileSync(new URL("model.json", dir), "utf-8"));
const cases = JSON.parse(readFileSync(new URL("parity.json", dir), "utf-8"));
const gaps = cases.map((c) => Math.abs(predictLogPpm2(model, c.features, c.words) - c.expected));
const worst = Math.max(...gaps);
for (const name of ["xgboost", "ridge", "text_score"]) {
  const g = cases.map((c) => Math.abs(parts(model, c.features, c.words)[name] - c.parts[name]));
  console.log(`  ${name}: max gap ${Math.max(...g).toExponential(2)}, cases off by more than 1e-4: ${g.filter((v) => v > 1e-4).length}`);
}
console.log(`${cases.length} cases: max gap ${worst.toExponential(2)}, mean gap ${(gaps.reduce((a, b) => a + b, 0) / gaps.length).toExponential(2)} (log price per m²)`);
process.exit(worst < 1e-4 ? 0 : 1);
