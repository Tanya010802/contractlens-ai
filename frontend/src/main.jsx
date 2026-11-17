import React, { useEffect, useId, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const names = {
  request_field_required: "New required request field",
  operation_removed: "Operation removed",
  response_field_removed: "Response field removed",
  request_type_changed: "Request type changed",
  response_type_changed: "Response type changed",
};

async function getJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Check the input and try again.");
  return data;
}

function post(url, input) {
  return getJson(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
}

function parseSpec(text, label) {
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(label + " must contain valid JSON.");
  }
}

function SpecInput({ title, value, onChange, onError }) {
  const id = useId();
  return (
    <section className="spec">
      <div className="row">
        <label className="label" htmlFor={id}>{title}</label>
        <label className="upload">
          Upload JSON
          <input type="file" accept=".json,application/json" aria-label={"Upload " + title}
            onChange={async (event) => {
              const file = event.target.files[0];
              event.target.value = "";
              if (!file) return;
              if (file.size > 2_000_000) return onError("Use a JSON file smaller than 2 MB.");
              try { onChange(await file.text()); } catch { onError("Could not read that file."); }
            }} />
        </label>
      </div>
      <textarea id={id} placeholder="Paste OpenAPI JSON…" value={value} onChange={(event) => onChange(event.target.value)}
        spellCheck={false} maxLength={2_000_000} required />
    </section>
  );
}

function Finding({ finding, ai, busy, onSuggest, suggestions, error }) {
  const field = finding.field.join(".");
  return (
    <article className="finding">
      <div className="row"><code>{finding.operation}</code><span className="priority">High priority</span></div>
      <h3>{names[finding.rule] || finding.rule}{field && <span> · {field}</span>}</h3>
      <p className="location">{finding.location}</p>
      <p>{finding.impact}</p>
      <details>
        <summary>View spec evidence</summary>
        <div className="evidence">
          {["before", "after"].map((version) => <div key={version}><strong>{version}</strong><code>{finding[version].pointer}</code>
            <pre>{JSON.stringify(finding[version].value, null, 2)}</pre></div>)}
        </div>
      </details>
      {ai && <button className="secondary" type="button" disabled={busy} onClick={onSuggest}>
        {busy ? "Generating…" : "Generate AI test ideas"}
      </button>}
      {error && <p className="error" role="alert">{error}</p>}
      {suggestions && <div className="scenarios">
        <h4>Suggested tests</h4>
        <p>Review these ideas against your API requirements before running them.</p>
        <ol>{suggestions.map((item, index) => <li key={index}>
          <span className="category">{item.category}</span> <strong>{item.title}</strong>
          <p>{item.procedure}</p><p><strong>Verify</strong> {item.verify}</p>
        </li>)}</ol>
      </div>}
    </article>
  );
}

function App() {
  const [before, setBefore] = useState("");
  const [after, setAfter] = useState("");
  const [result, setResult] = useState(null);
  const [ai, setAi] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [generated, setGenerated] = useState({});
  const generation = useRef(0);

  useEffect(() => {
    getJson("/api/config").then((data) => setAi(data.ai_available)).catch(() => {});
  }, []);

  function edited() {
    generation.current += 1;
    setResult(null);
    setGenerated({});
    setError("");
    setBusy("");
  }

  async function loadDemo() {
    const token = ++generation.current;
    setBusy("demo");
    setError("");
    try {
      const [oldSpec, newSpec] = await Promise.all([getJson("/examples/before.json"), getJson("/examples/after.json")]);
      if (token !== generation.current) return;
      setBefore(JSON.stringify(oldSpec, null, 2));
      setAfter(JSON.stringify(newSpec, null, 2));
      edited();
    } catch {
      if (token === generation.current) setError("Could not load the sample specifications.");
    } finally {
      if (token === generation.current) setBusy("");
    }
  }

  async function compareSpecs(event) {
    event.preventDefault();
    const token = ++generation.current;
    setBusy("compare");
    setError("");
    setResult(null);
    setGenerated({});
    try {
      const input = { before: parseSpec(before, "Before spec"), after: parseSpec(after, "After spec") };
      const report = await post("/api/compare", input);
      if (token === generation.current) setResult({ report, input });
    } catch (err) {
      if (token === generation.current) setError(err.message);
    } finally {
      if (token === generation.current) setBusy("");
    }
  }

  async function generate(id) {
    const token = generation.current;
    setGenerated((current) => ({ ...current, [id]: { busy: true } }));
    try {
      const data = await post("/api/suggestions", { ...result.input, finding_id: id });
      if (token === generation.current) setGenerated((current) => ({ ...current, [id]: data }));
    } catch (err) {
      if (token === generation.current) setGenerated((current) => ({ ...current, [id]: { error: err.message } }));
    }
  }

  function download() {
    const report = { ...result.report, suggested_tests: Object.fromEntries(Object.entries(generated)
      .filter(([, data]) => data.scenarios).map(([id, data]) => [id, data.scenarios])) };
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "contractlens-report.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <>
    <header><div className="frame masthead"><a href="/" className="brand"><span aria-hidden="true">◎</span> ContractLens <em>AI</em></a>
      <a href="/docs">API docs ↗</a></div></header>
    <main className="frame">
      <div className="intro"><p className="kicker">API compatibility</p><h1>Review API changes<span>.</span></h1>
        <p>Compare two OpenAPI specifications to see which changes could affect existing clients.</p></div>
      <form className="panel" onSubmit={compareSpecs}>
        <div className="row panel-heading"><h2>Specifications</h2>
          <button className="secondary" type="button" onClick={loadDemo} disabled={!!busy}>Load sample</button></div>
        <div className="spec-grid">
          <SpecInput title="Before spec" value={before} onChange={(value) => { edited(); setBefore(value); }} onError={setError} />
          <SpecInput title="After spec" value={after} onChange={(value) => { edited(); setAfter(value); }} onError={setError} />
        </div>
        <div className="row controls"><p>OpenAPI 3.0 or 3.1 · JSON</p><button type="submit" disabled={!!busy}>
          {busy === "compare" ? "Comparing…" : "Compare specifications →"}</button></div>
        {error && <p role="alert" className="error">{error}</p>}
      </form>
      <section className="results" aria-labelledby="report-title">
        <div className="row result-heading"><h2 id="report-title">Comparison report</h2>
          {result && <button className="secondary" type="button" onClick={download}>Download JSON ↓</button>}</div>
        {!result ? <p className="placeholder">Compare two specs to review findings and source evidence.</p> : <>
          <p role="status" className="summary">
            {result.report.summary.high} high-priority {result.report.summary.high === 1 ? "finding" : "findings"}.
            {!result.report.findings.length && " The comparison found no changes covered by the current rules."}
          </p>
          {result.report.warnings.length > 0 && <details className="warning"><summary>Some schema sections were skipped</summary>
            <ul>{result.report.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
          </details>}
          {ai && result.report.findings.length > 0 && <p className="location">
            Generating AI test ideas sends the finding’s operation, field, and impact to OpenAI.
          </p>}
          {result.report.findings.map((finding) => <Finding key={finding.id} finding={finding} ai={ai}
            onSuggest={() => generate(finding.id)} {...generated[finding.id]} suggestions={generated[finding.id]?.scenarios} />)}
        </>}
      </section>
    </main>
  </>;
}

createRoot(document.getElementById("root")).render(<App />);
