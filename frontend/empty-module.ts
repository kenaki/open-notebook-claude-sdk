// Stub module used to alias the optional native `canvas` package that
// `pdfjs-dist` (pulled in by @react-pdf-viewer) tries to `require("canvas")`
// from its NodeCanvasFactory. That code path is Node-only and never runs in
// the browser/SSR bundle, but Turbopack still resolves the import at build
// time and fails because `canvas` (a native module) is not installed.
// Aliasing `canvas` → this empty module in next.config.ts skips it safely.
export default {};
