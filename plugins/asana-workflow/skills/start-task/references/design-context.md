# Design Context — Fetch Protocol & Pixel-Perfect Contract

Used by Step 5 (context assembly) and Step 10 (handoff) in `start-task`.

---

## When This Applies

Activate this protocol whenever the task description, comments, or attachments contain a link to a design tool (Figma, Zeplin, etc.). The goal is to assemble **exact, copy-pasteable implementation values** before any code is written — not general visual descriptions.

---

## Figma: Two-Step Fetch Protocol

### Step A — Identify the right nodes

Call `get_metadata` on the file/node from the URL. Do **not** skip this step and jump straight to `get_design_context` on the top-level page — top-level pages truncate at token limits and return noise.

From the metadata, identify the specific **component or frame nodes** that correspond to what is being built. Look for:
- The modal/dialog frame
- Individual UI components (inputs, buttons, table rows, etc.)

Record the `nodeId` for each.

### Step B — Get exact implementation values

For each node identified in Step A, call `get_design_context`. This returns:
- Exact Tailwind/CSS class names (e.g. `rounded-[12px]`, `text-[#101828]`, `drop-shadow-[0px_1px_0.25px_rgba(29,41,61,0.02)]`)
- Exact color tokens
- Exact spacing, padding, border-radius values
- Typography: font-size, font-weight, line-height, letter-spacing
- Shadow definitions

**Do not stop at `get_metadata`.** Metadata gives node hierarchy; `get_design_context` gives the values you can actually type into code.

### Step C — Assemble the Design Context section

Produce a `## Design Context` section in the handoff bundle. For each node:

```
### [Component name] (node: XXXX:YYYY)
[Full get_design_context output — do not summarise or paraphrase]
```

Paste the raw output verbatim. Downstream implementers need the exact strings, not your interpretation of them.

---

## Handoff: Pixel-Perfect Contract

Include this block **verbatim** in every handoff prompt that carries a Design Context section:

---

> **PIXEL-PERFECT IMPLEMENTATION CONTRACT**
>
> This context bundle includes a Design Context section with exact CSS/Tailwind values fetched directly from the design tool. Implementation rules — all non-negotiable:
>
> 1. **Use exact values only.** Every styled element must use the values from the Design Context section. No rounding, no "close enough" substitutes. If the design says `rounded-[12px]`, write `rounded-[12px]` — not `rounded-lg` (8px), not `rounded-xl` (12px via alias if you're not sure). Copy the string.
>
> 2. **Check for existing components first.** Before building any UI element from scratch, search the codebase (especially `packages/ui/` or the equivalent shared component library) for an existing component that matches the pattern. Use it if it exists. Document what you found before starting.
>
> 3. **Re-read Design Context before every component.** Not once at the start — before each new component you implement. Values differ between components.
>
> 4. **No approximation is ever acceptable.** "The colour looks about right" is not compliance. If a value is unclear, call `get_design_context` again on the specific node rather than guessing.

---

## Anti-Patterns to Reject in Review

The spec-reviewer and code-quality-reviewer should flag any of these as non-compliant:

| Anti-pattern | Example | Why it fails |
|---|---|---|
| Tailwind alias instead of exact value | `rounded-xl` when design says `rounded-[12px]` | Aliases can drift; exact values cannot |
| Gray palette shorthand | `text-gray-900` when design says `text-[#101828]` | Palette grays rarely match brand tokens exactly |
| Native browser UI for interactive controls | `<select>` for a styled dropdown | Looks nothing like the design; always check for existing component first |
| Single top-level `get_design_context` call | Calling on the whole page/frame | Truncates at token limit; call per-component node |
| Implementing without reading Design Context | Writing from memory or intuition | Produces first-draft approximations that require full re-review |
