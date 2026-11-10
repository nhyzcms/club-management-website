/**
 * Build-seam check for Django-admin SurveyJS vendor files.
 * Hooked at the end of `npm run build`. No test runner.
 */
const fs = require("fs");
const path = require("path");

const distRoot = path.join(__dirname, "..", "dist", "surveyjs");
const required = [
  "survey.core.min.js",
  "survey-core.min.css",
  "survey-js-ui.min.js",
  "survey-creator-core.min.js",
  "survey-creator-core.min.css",
  "survey-creator-js.min.js",
  "survey.analytics.min.js",
  "survey.analytics.min.css",
  "chart.umd.min.js",
  "survey.i18n.zh-cn.min.js",
  "survey-creator.i18n.zh-cn.min.js",
];

function fail(message) {
  console.error(`assert-surveyjs-dist: ${message}`);
  process.exit(1);
}

if (!fs.existsSync(distRoot)) {
  fail(`missing directory ${distRoot} (npm run build must run copy-surveyjs after webpack)`);
}

for (const name of required) {
  const abs = path.join(distRoot, name);
  if (!fs.existsSync(abs)) {
    fail(`missing dist/surveyjs/${name}`);
  }
}

console.log(`assert-surveyjs-dist: ok (${required.length} files)`);
