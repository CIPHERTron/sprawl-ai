# Sprawl AI — Documentation

This directory contains the [Mintlify](https://mintlify.com) documentation site for Sprawl AI.

## Local development

**Requirements:** Node 20.17+ (Mintlify does not support Node 16/18).

Start the local preview server from the repo root:

```bash
make docs-dev
```

This runs [`docs/dev.sh`](./dev.sh), which:

1. Selects Node 20 (via `nvm` if your active node is older).
2. Installs the `mint` CLI if it is missing.
3. Repairs the Mintlify client cache if needed (see Troubleshooting below).
4. Starts the preview at [http://localhost:3333](http://localhost:3333) with hot reload.

You can also run it directly: `./docs/dev.sh` (override the port with `PORT=4000 ./docs/dev.sh`).

## Troubleshooting

### `Error: Client not built`

This is a known Mintlify CLI bug ([mintlify/docs#5624](https://github.com/mintlify/docs/issues/5624)): the npm-bundled `tar` silently drops the client's `.next/` directory during extraction on macOS, so `mint dev` thinks the client was never built.

`docs/dev.sh` works around it automatically by re-extracting the client tarball with the system `tar` (which preserves `.next/`). If you ever hit this running `mint dev` by hand, just use `make docs-dev` instead, or manually clear and let the script repair:

```bash
rm -rf ~/.mintlify && make docs-dev
```

### Old `mintlify` package

The CLI package was renamed from `mintlify` to `mint`. If you have a stale global `mintlify`, remove it: `npm uninstall -g mintlify`.

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
