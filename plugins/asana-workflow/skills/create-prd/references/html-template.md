# PRD HTML Template Reference

This file defines the exact HTML structure and CSS patterns to use when generating a PRD. Follow every component pattern precisely — do not invent new layouts.

---

## Full CSS Block

Paste this inside `<head>` verbatim. Adjust `--brand` only if the product's own colour is identifiable from the resources.

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Inter', -apple-system, sans-serif; font-size: 15px; line-height: 1.65; color: #111827; background: #F9FAFB; }
  .page { max-width: 860px; margin: 0 auto; padding: 48px 32px 120px; }

  /* Header */
  .doc-header { margin-bottom: 40px; padding-bottom: 32px; border-bottom: 1px solid #E5E7EB; }
  .doc-title { font-size: 30px; font-weight: 700; letter-spacing: -0.5px; color: #0A1B33; margin-bottom: 16px; }
  .doc-title span { color: #4B55E5; }
  .doc-meta { display: flex; flex-wrap: wrap; gap: 20px; font-size: 13px; color: #6B7280; }
  .doc-meta strong { color: #374151; font-weight: 500; }

  /* Badges */
  .badge { display: inline-flex; align-items: center; gap: 5px; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 500; }
  .badge-draft    { background: #FEF3C7; color: #92400E; }
  .badge-review   { background: #DBEAFE; color: #1E40AF; }
  .badge-approved { background: #D1FAE5; color: #065F46; }
  .badge-tbd      { background: #F3F4F6; color: #6B7280; }
  .badge-open     { background: #FEF3C7; color: #92400E; }

  /* Table of contents */
  .toc { background: #fff; border: 1px solid #E5E7EB; border-radius: 12px; padding: 20px 24px; margin-bottom: 40px; }
  .toc-title { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: #9CA3AF; margin-bottom: 12px; }
  .toc ol { padding-left: 18px; display: flex; flex-direction: column; gap: 6px; }
  .toc a { color: #4B55E5; text-decoration: none; font-size: 14px; }
  .toc a:hover { text-decoration: underline; }

  /* Sections */
  .section { margin-bottom: 52px; }
  h2 { font-size: 20px; font-weight: 700; color: #0A1B33; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 2px solid #E5E7EB; }
  h3 { font-size: 16px; font-weight: 600; color: #111827; margin: 28px 0 12px; }
  h4 { font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: #6B7280; margin: 20px 0 8px; }
  p { color: #374151; margin-bottom: 12px; }
  ul, ol { padding-left: 20px; color: #374151; display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }

  /* Feature cards */
  .feature-card { background: #fff; border: 1px solid #E5E7EB; border-radius: 12px; padding: 24px; margin-bottom: 24px; }
  .feature-card h3 { margin-top: 0; font-size: 17px; color: #0A1B33; }
  .user-story { background: #F0F4FF; border-left: 3px solid #4B55E5; border-radius: 0 8px 8px 0; padding: 12px 16px; font-size: 14px; color: #374151; margin: 12px 0 20px; font-style: italic; }

  /* Requirement lists */
  .req-list { display: flex; flex-direction: column; gap: 8px; padding-left: 0; list-style: none; }
  .req-list li { display: flex; gap: 10px; align-items: flex-start; font-size: 14px; color: #374151; }
  .req-id { flex-shrink: 0; font-size: 11px; font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace; color: #4B55E5; background: #EEF2FF; padding: 1px 6px; border-radius: 4px; margin-top: 2px; }
  .figma-link { display: inline-flex; align-items: center; gap: 6px; margin-top: 16px; font-size: 13px; color: #9CA3AF; }

  /* Tables */
  table { width: 100%; border-collapse: collapse; font-size: 14px; margin-bottom: 12px; }
  thead tr { background: #F3F4F6; }
  th { text-align: left; padding: 10px 14px; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: #6B7280; border-bottom: 1px solid #E5E7EB; }
  td { padding: 10px 14px; border-bottom: 1px solid #F3F4F6; vertical-align: top; color: #374151; }
  tr:last-child td { border-bottom: none; }
  .table-wrap { border: 1px solid #E5E7EB; border-radius: 10px; overflow: hidden; margin-bottom: 16px; }

  /* Scope list */
  .scope-in  { color: #065F46; background: #D1FAE5; padding: 1px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }
  .scope-out { color: #6B7280; background: #F3F4F6; padding: 1px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }
  .scope-tbd { color: #92400E; background: #FEF3C7; padding: 1px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }
  .scope-item { display: flex; align-items: baseline; gap: 10px; padding: 8px 0; border-bottom: 1px solid #F3F4F6; font-size: 14px; color: #374151; }
  .scope-item:last-child { border-bottom: none; }
  .scope-list { background: #fff; border: 1px solid #E5E7EB; border-radius: 10px; padding: 4px 16px; margin-bottom: 16px; }

  /* Risk levels */
  .risk-high   { color: #991B1B; font-weight: 500; }
  .risk-medium { color: #92400E; font-weight: 500; }

  /* Links section */
  .links-grid { display: flex; flex-direction: column; gap: 10px; }
  .link-card { display: flex; align-items: center; gap: 14px; background: #fff; border: 1px solid #E5E7EB; border-radius: 10px; padding: 14px 18px; text-decoration: none; color: #111827; transition: border-color 0.15s; }
  .link-card:hover { border-color: #4B55E5; box-shadow: 0 0 0 1px #4B55E5; }
  .link-icon { width: 36px; height: 36px; border-radius: 8px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; font-size: 18px; }
  .link-icon-pdf  { background: #FEE2E2; }
  .link-icon-html { background: #EEF2FF; }
  .link-icon-fig  { background: #F0FDF4; }
  .link-icon-missing { background: #F3F4F6; }
  .link-label { font-size: 14px; font-weight: 500; }
  .link-sub   { font-size: 12px; color: #9CA3AF; margin-top: 1px; }
  .link-card-missing { background: #F9FAFB; border-style: dashed; cursor: default; pointer-events: none; opacity: 0.7; }
  .link-card-missing:hover { border-color: #E5E7EB; box-shadow: none; }
  .link-missing-badge { font-size: 11px; font-weight: 500; color: #9CA3AF; background: #F3F4F6; padding: 1px 7px; border-radius: 4px; margin-top: 3px; display: inline-block; }

  /* Inline code */
  code { background: #F3F4F6; padding: 1px 6px; border-radius: 4px; font-size: 13px; font-family: 'SF Mono', 'Fira Code', monospace; }
</style>
```

---

## Section-by-Section HTML Patterns

### 1. Header

```html
<div class="doc-header">
  <div class="doc-title">Product Name: <span>Feature Name</span> — PRD</div>
  <div class="doc-meta">
    <span><strong>PM Owner</strong> Name Here</span>
    <span><strong>Status</strong> <span class="badge badge-draft">Draft</span></span>
    <span><strong>Last Updated</strong> Month DD, YYYY</span>
    <span><strong>Version</strong> v0.1</span>
    <span><strong>Target launch</strong> Q? YYYY</span>
  </div>
</div>
```

---

### 2. Table of Contents

```html
<div class="toc">
  <div class="toc-title">Contents</div>
  <ol>
    <li><a href="#problem">Problem &amp; KPIs</a></li>
    <li><a href="#scope">Scope</a></li>
    <li><a href="#features">Features</a>
      <ol style="margin-top:6px">
        <li><a href="#feature-one">Feature One</a></li>
        <li><a href="#feature-two">Feature Two</a></li>
      </ol>
    </li>
    <li><a href="#dependencies">Dependencies &amp; Integrations</a></li>
    <li><a href="#questions">Open Questions</a></li>
    <li><a href="#links">Links</a></li>
  </ol>
</div>
```

---

### 3. Problem & KPIs

```html
<div class="section" id="problem">
  <h2>Problem &amp; KPIs</h2>

  <h3>Problem</h3>
  <p><strong>What is happening:</strong> ...</p>

  <h4>Who is affected</h4>
  <ul>
    <li><strong>Role A</strong> — impact description</li>
    <li><strong>Role B</strong> — impact description</li>
  </ul>

  <h4>Why it matters</h4>
  <p>...</p>

  <h3>Target KPIs</h3>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>Metric</th><th>Baseline</th><th>Target</th><th>How we measure</th></tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Primary metric name</strong><br><small style="color:#9CA3AF">clarifying note if needed</small></td>
          <td>0</td>
          <td style="font-weight:600;color:#4B55E5">Target value</td>
          <td style="font-size:13px;color:#6B7280">Instrumentation or logging source</td>
        </tr>
        <tr>
          <td><strong>Secondary metric name</strong></td>
          <td><span class="badge badge-tbd">TBD</span></td>
          <td><span class="badge badge-tbd">TBD</span> ↓</td>
          <td style="font-size:13px;color:#6B7280">What needs to be built to measure this</td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
```

---

### 4. Scope

```html
<div class="section" id="scope">
  <h2>Scope</h2>

  <h3>What's In</h3>
  <p>Prose description of what the initiative adds to the product...</p>

  <div class="scope-list">
    <div class="scope-item"><span class="scope-in">In scope</span> <span>Description of what's included</span></div>
    <div class="scope-item"><span class="scope-out">Out of scope</span> <span>Description of what's excluded and why</span></div>
    <div class="scope-item"><span class="scope-tbd">TBD</span> <span>Something not yet decided</span></div>
  </div>

  <h3>Future Considerations</h3>
  <ul>
    <li>Future item 1</li>
    <li>Future item 2</li>
  </ul>
</div>
```

---

### 5. Feature Card

One card per feature. Repeat this block inside `<div class="section" id="features">`.

```html
<div class="feature-card" id="feature-slug">
  <h3>Feature Name</h3>

  <div class="user-story">"As a [role], I want to [action], so that [outcome]."</div>

  <h4>Functional Requirements</h4>
  <ul class="req-list">
    <li><span class="req-id">FR-1</span> Description of what the system must do.</li>
    <li><span class="req-id">FR-2</span> Another requirement.</li>
  </ul>

  <h4>Business Rules</h4>
  <ul class="req-list">
    <li><span class="req-id">BR-1</span> A constraint or invariant.</li>
    <li><span class="req-id">BR-2</span> Another constraint.</li>
  </ul>

  <!-- If Figma URL exists -->
  <div class="figma-link">
    🔗 <a href="https://figma.com/..." target="_blank" style="color:#4B55E5">Figma — Feature Name</a>
  </div>

  <!-- If design not yet started — use this instead, never omit the slot -->
  <div class="figma-link" style="color:#D1D5DB;">
    🔗 <span style="color:#9CA3AF">Figma — Design not yet available</span>
  </div>
</div>
```

**Rules for FRs vs BRs:**
- FR = what the system does (actions, behaviours, UI elements)
- BR = what is always or never true (limits, formats, constraints, invariants)
- Never repeat the same point in both

---

### 6. Dependencies & Integrations

```html
<div class="section" id="dependencies">
  <h2>Dependencies &amp; Integrations</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>System / Team</th><th>Nature of Dependency</th><th>Impact / Risk</th></tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>System Name</strong></td>
          <td>What this initiative depends on it for. If being built as part of this initiative, state what data/events it must emit.</td>
          <td><span class="risk-high">High</span> — specific reason</td>
        </tr>
        <tr>
          <td><strong>Another System</strong></td>
          <td>Nature of the dependency.</td>
          <td><span class="risk-medium">Medium</span> — specific reason</td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
```

---

### 7. Open Questions

Only include questions that are genuine TBDs — confirmed as unresolved by the user during the interview.

**Owner and Due Date must come from the interview — do not write `TBD` here unless the user explicitly said so.** Copy the *structure* of the example below, not its placeholder values.

```html
<div class="section" id="questions">
  <h2>Open Questions</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>Question</th><th>Owner</th><th>Due Date</th><th>Status</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>The specific question that is unresolved.</td>
          <td>Jane Doe</td>
          <td>Aug 15, 2026</td>
          <td><span class="badge badge-open">Open</span></td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
```

---

### 8. Links

Every resource referenced in the PRD must appear here — whether or not it has a URL yet. If the resource exists and has a URL, link it. If the resource is referenced but has no URL yet (design not started, spec not written), use the missing card pattern — never omit it.

```html
<div class="section" id="links">
  <h2>Links</h2>
  <div class="links-grid">

    <!-- Resource with a real URL -->
    <a class="link-card" href="filename.pdf" target="_blank">
      <div class="link-icon link-icon-pdf">📄</div>
      <div>
        <div class="link-label">One Pager — Feature Name</div>
        <div class="link-sub">filename.pdf</div>
      </div>
    </a>

    <a class="link-card" href="prototype.html" target="_blank">
      <div class="link-icon link-icon-html">⚡</div>
      <div>
        <div class="link-label">Flow Prototype</div>
        <div class="link-sub">prototype.html</div>
      </div>
    </a>

    <a class="link-card" href="https://figma.com/..." target="_blank">
      <div class="link-icon link-icon-fig">🎨</div>
      <div>
        <div class="link-label">Figma — Design File</div>
        <div class="link-sub">figma.com</div>
      </div>
    </a>

    <!-- Resource referenced in PRD but URL not yet available — use this pattern -->
    <div class="link-card link-card-missing">
      <div class="link-icon link-icon-missing">📋</div>
      <div>
        <div class="link-label">Backend Spec — VAST Serving Infrastructure</div>
        <div class="link-sub"><span class="link-missing-badge">Not yet available</span></div>
      </div>
    </div>

  </div>
</div>
```

---

## Full Page Shell

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>PRD — [Feature Name]</title>
  <!-- PASTE CSS BLOCK HERE -->
</head>
<body>
<div class="page">
  <!-- HEADER -->
  <!-- TABLE OF CONTENTS -->
  <!-- PROBLEM & KPIs section -->
  <!-- SCOPE section -->
  <!-- FEATURES section -->
  <!-- DEPENDENCIES section -->
  <!-- OPEN QUESTIONS section -->
  <!-- LINKS section -->
</div>
</body>
</html>
```
