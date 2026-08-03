import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const globalCss = readFileSync(
  resolve("src/styles/global.css"),
  "utf8"
).replace(/\r\n/g, "\n");
const mobileRules = globalCss.match(
  /@media \(max-width: 767px\) \{([\s\S]*)\}\s*$/
)?.[1];

test("keeps the desktop node list and detail pane in two columns", () => {
  expect(globalCss).toContain(
    ".nodes-workspace {\n  display: grid;\n  grid-template-columns: minmax(260px, 34%) minmax(0, 1fr);"
  );
  expect(globalCss).toContain(
    ".node-detail-pane .ant-table-wrapper { overflow-x: auto; }"
  );
});

test("stacks node content and replaces the sider with a mobile menu below 768px", () => {
  expect(mobileRules).toBeDefined();
  expect(mobileRules).toContain(".app-sider { display: none; }");
  expect(mobileRules).toContain(".app-sider + .ant-layout { margin-left: 0; }");
  expect(mobileRules).toContain(".mobile-menu-button { display: inline-flex; }");
  expect(mobileRules).toContain(
    ".nodes-workspace { grid-template-columns: minmax(0, 1fr); }"
  );
  expect(mobileRules).toContain("border-bottom: 1px solid var(--border-soft);");
});
