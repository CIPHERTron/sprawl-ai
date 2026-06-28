# Sprawl AI — Documentation

This directory contains the [Mintlify](https://mintlify.com) documentation site for Sprawl AI.

## Local development

Install the Mintlify CLI:

```bash
npm install -g mintlify
```

Start the local preview server:

```bash
# From repo root:
make docs-dev

# Or directly:
cd docs && mintlify dev
```

The docs site starts at [http://localhost:3333](http://localhost:3333) with hot reload.

## Deploying to Mintlify (free Hobby tier)

1. Sign up at [mintlify.com](https://mintlify.com) (free Hobby tier is sufficient).
2. In the Mintlify dashboard, create a new project and connect the `CIPHERTron/sprawl-ai` GitHub repository.
3. Set the **docs directory** to `docs/` (this folder).
4. Mintlify will auto-deploy on every push to `main`. The site URL will be something like `https://sprawl-ai.mintlify.app`.

## Structure

```
docs/
├── docs.json                  ← Navigation, theme, metadata
├── index.mdx                  ← Landing page
├── get-started/
│   ├── quickstart.mdx
│   └── local-development.mdx
├── architecture/
│   ├── system-overview.mdx
│   ├── service-topology.mdx
│   ├── request-job-lifecycle.mdx
│   └── verify-before-revoke.mdx
├── codebase/
│   ├── repository-layout.mdx
│   ├── api-service.mdx
│   ├── worker-service.mdx
│   ├── shared-package.mdx
│   ├── data-model.mdx
│   └── web-frontend.mdx
├── connectors/
│   └── connector-model.mdx
└── reference/
    ├── environment-variables.mdx
    └── specs-archive.mdx
```

## Keeping docs current

A Cursor rule at `.cursor/rules/docs-maintenance.mdc` instructs the AI agent to update the matching docs page whenever code changes. See that file for the trigger → page mapping.

The key principle: `specs/` is the immutable design archive (the "why"). `docs/` is the living record of what exists (the "what").
