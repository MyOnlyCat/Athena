# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root, or
- **`CONTEXT-MAP.md`** at the repo root if it exists — it points at one `CONTEXT.md` per context.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in.

If these files don't exist, proceed silently. The `/domain-modeling` skill creates them lazily when domain terms or decisions are resolved.

## File structure

Single-context repo:

```text
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-example-decision.md
│   └── 0002-another-decision.md
└── src/
```

## Use the glossary's vocabulary

When output names a domain concept—such as in an issue title, refactor proposal, hypothesis, or test—use the term defined in `CONTEXT.md`.

If the concept is absent from the glossary, reconsider whether the project uses that language or note the gap for `/domain-modeling`.

## Flag ADR conflicts

If output contradicts an existing ADR, surface it explicitly rather than silently overriding.
