"""Initial schema — full Phase 8 / Slice 0

Creates all Postgres enum types, tables, indexes, and CHECK constraints exactly
as specified in specs/08-system-design-lld-db.md §8.2.

Revision ID: 0001
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── pgvector extension ────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # ── Enum types ────────────────────────────────────────────────────────────
    op.execute("CREATE TYPE workspace_kind AS ENUM ('standard','demo');")
    op.execute("CREATE TYPE role AS ENUM ('owner','approver','viewer');")
    op.execute(
        "CREATE TYPE connector_type AS ENUM "
        "('vault','aws_ssm','aws_iam','aws_secrets_manager','infisical');"
    )
    op.execute(
        "CREATE TYPE connector_status AS ENUM ('untested','verified','degraded','disabled');"
    )
    op.execute(
        "CREATE TYPE scan_status AS ENUM ('queued','scanning','complete','error');"
    )
    op.execute(
        "CREATE TYPE finding_state AS ENUM "
        "('new','triaged','confirmed','false_positive','ignored');"
    )
    op.execute(
        "CREATE TYPE secret_health AS ENUM ('unknown','healthy','at_risk','exposed');"
    )
    op.execute(
        "CREATE TYPE exposure_status AS ENUM "
        "('unknown','live_inferred','public_leak','inactive');"
    )
    op.execute(
        "CREATE TYPE severity_bucket AS ENUM ('low','medium','high','critical');"
    )
    op.execute(
        "CREATE TYPE environment AS ENUM ('prod','staging','dev','unknown');"
    )
    op.execute(
        "CREATE TYPE node_kind AS ENUM "
        "('secret','location','ci','store_entry','principal','resource','environment');"
    )
    op.execute(
        "CREATE TYPE edge_kind AS ENUM "
        "('found_in','stored_in','is_principal','grants_access_to','used_by','can_access');"
    )
    op.execute("CREATE TYPE confidence AS ENUM ('high','medium','low');")
    op.execute(
        "CREATE TYPE investigation_status AS ENUM ('running','complete','error');"
    )
    op.execute(
        "CREATE TYPE rotation_status AS ENUM "
        "('proposed','plan_failed','pending_approval','provisioning',"
        "'distributing','verifying','awaiting_confirmation','revoking',"
        "'completed','rolling_back','rolled_back','rollback_failed',"
        "'rejected','needs_replan','abandoned');"
    )
    op.execute("CREATE TYPE step_kind AS ENUM ('provision','distribute','verify','revoke');")
    op.execute(
        "CREATE TYPE step_status AS ENUM "
        "('pending','awaiting_confirmation','running','done','failed','compensated');"
    )

    # ── Identity & tenancy ────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE workspaces (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name        text NOT NULL,
            kind        workspace_kind NOT NULL DEFAULT 'standard',
            demo_session_id text,
            expires_at  timestamptz,
            created_at  timestamptz NOT NULL DEFAULT now()
        );
    """)
    op.execute(
        "CREATE INDEX ix_workspaces_kind_expires_at ON workspaces (kind, expires_at);"
    )

    op.execute("""
        CREATE TABLE users (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            github_id   bigint UNIQUE NOT NULL,
            email       text,
            name        text,
            avatar_url  text,
            created_at  timestamptz NOT NULL DEFAULT now()
        );
    """)

    op.execute("""
        CREATE TABLE memberships (
            user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            role         role NOT NULL DEFAULT 'owner',
            PRIMARY KEY (user_id, workspace_id)
        );
    """)

    # ── Connectors ────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE connectors (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id      uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            type              connector_type NOT NULL,
            name              text NOT NULL,
            environment       environment NOT NULL DEFAULT 'unknown',
            path_prefix       text,
            connection        jsonb NOT NULL DEFAULT '{}',
            vault_auth_handle text NOT NULL,
            capabilities      jsonb NOT NULL DEFAULT '{}',
            status            connector_status NOT NULL DEFAULT 'untested',
            last_tested_at    timestamptz,
            created_at        timestamptz NOT NULL DEFAULT now(),
            updated_at        timestamptz NOT NULL DEFAULT now()
        );
    """)
    op.execute(
        "CREATE INDEX ix_connectors_workspace_type ON connectors (workspace_id, type);"
    )

    # ── GitHub sources ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE github_installations (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            installation_id bigint UNIQUE NOT NULL,
            account_login   text NOT NULL,
            created_at      timestamptz NOT NULL DEFAULT now()
        );
    """)

    op.execute("""
        CREATE TABLE repos (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            installation_id uuid NOT NULL REFERENCES github_installations(id) ON DELETE CASCADE,
            full_name       text NOT NULL,
            default_branch  text,
            UNIQUE (workspace_id, full_name)
        );
    """)

    op.execute("""
        CREATE TABLE scans (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            repo_id      uuid NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
            type         text NOT NULL,
            status       scan_status NOT NULL DEFAULT 'queued',
            head_sha     text NOT NULL,
            forced       boolean NOT NULL DEFAULT false,
            progress     numeric DEFAULT 0,
            error        text,
            started_at   timestamptz,
            finished_at  timestamptz
        );
    """)
    # Deduplicate non-forced scans by (repo, type, sha); forced scans always insert (N2)
    op.execute(
        "CREATE UNIQUE INDEX scans_dedupe ON scans (repo_id, type, head_sha) WHERE NOT forced;"
    )

    # ── Secrets & findings ────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE secrets (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            fingerprint     text NOT NULL,
            type            text NOT NULL,
            provider        text,
            principal_ref   jsonb,
            store_ref       jsonb,
            health          secret_health NOT NULL DEFAULT 'unknown',
            environment     environment NOT NULL DEFAULT 'unknown',
            exposure_status exposure_status NOT NULL DEFAULT 'unknown',
            severity_score  int,
            severity_bucket severity_bucket,
            rotatable       boolean NOT NULL DEFAULT false,
            first_seen      timestamptz NOT NULL DEFAULT now(),
            last_seen       timestamptz NOT NULL DEFAULT now(),
            UNIQUE (workspace_id, fingerprint)
        );
    """)
    op.execute(
        "CREATE INDEX ix_secrets_workspace_health ON secrets (workspace_id, health);"
    )
    op.execute(
        "CREATE INDEX ix_secrets_workspace_severity ON secrets (workspace_id, severity_score DESC);"
    )

    op.execute("""
        CREATE TABLE findings (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            secret_id    uuid REFERENCES secrets(id) ON DELETE SET NULL,
            repo_id      uuid REFERENCES repos(id) ON DELETE CASCADE,
            detector     text NOT NULL DEFAULT 'gitleaks',
            rule_id      text,
            commit_sha   text,
            file_path    text,
            line         int,
            match_hash   text NOT NULL,
            state        finding_state NOT NULL DEFAULT 'new',
            first_seen   timestamptz NOT NULL DEFAULT now(),
            last_seen    timestamptz NOT NULL DEFAULT now(),
            UNIQUE (workspace_id, match_hash, repo_id, commit_sha, file_path, line)
        );
    """)
    op.execute(
        "CREATE INDEX ix_findings_workspace_state ON findings (workspace_id, state);"
    )
    op.execute("CREATE INDEX ix_findings_secret_id ON findings (secret_id);")

    # ── Blast-radius graph ────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE graph_nodes (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            secret_id    uuid NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
            kind         node_kind NOT NULL,
            label        text NOT NULL,
            environment  environment NOT NULL DEFAULT 'unknown',
            attrs        jsonb NOT NULL DEFAULT '{}',
            created_at   timestamptz NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX ix_graph_nodes_secret_id ON graph_nodes (secret_id);")

    op.execute("""
        CREATE TABLE graph_edges (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            secret_id    uuid NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
            src_node_id  uuid NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
            dst_node_id  uuid NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
            kind         edge_kind NOT NULL,
            confidence   confidence NOT NULL DEFAULT 'medium',
            attrs        jsonb NOT NULL DEFAULT '{}'
        );
    """)
    op.execute("CREATE INDEX ix_graph_edges_secret_id ON graph_edges (secret_id);")
    op.execute("CREATE INDEX ix_graph_edges_src_node_id ON graph_edges (src_node_id);")

    # ── Severity history ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE severities (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            secret_id    uuid NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
            score        int NOT NULL,
            factors      jsonb NOT NULL,
            explanation  text,
            computed_at  timestamptz NOT NULL DEFAULT now()
        );
    """)
    op.execute(
        "CREATE INDEX ix_severities_secret_computed ON severities (secret_id, computed_at DESC);"
    )

    # ── Investigations ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE investigations (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            secret_id    uuid NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
            status       investigation_status NOT NULL DEFAULT 'running',
            trace_id     text,
            coverage     jsonb,
            started_at   timestamptz NOT NULL DEFAULT now(),
            finished_at  timestamptz
        );
    """)
    # At most one in-flight investigation per secret (M5)
    op.execute(
        "CREATE UNIQUE INDEX one_active_investigation "
        "ON investigations (secret_id) WHERE status = 'running';"
    )

    # ── Rotations & steps ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE rotations (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            secret_id       uuid NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
            status          rotation_status NOT NULL DEFAULT 'proposed',
            plan            jsonb,
            plan_error      text,
            coverage        jsonb NOT NULL DEFAULT '{}',
            new_secret_ref  jsonb,
            plan_expires_at timestamptz,
            created_by      uuid REFERENCES users(id),
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT plan_present_when_actionable
                CHECK (plan IS NOT NULL OR status IN ('proposed','plan_failed'))
        );
    """)
    # Terminal states release the lock; active states hold it (N1)
    op.execute(
        "CREATE UNIQUE INDEX one_active_rotation ON rotations (secret_id) "
        "WHERE status NOT IN "
        "('completed','rolled_back','rejected','rollback_failed','abandoned','plan_failed');"
    )

    op.execute("""
        CREATE TABLE rotation_steps (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id         uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            rotation_id          uuid NOT NULL REFERENCES rotations(id) ON DELETE CASCADE,
            idx                  int NOT NULL,
            kind                 step_kind NOT NULL,
            target               jsonb NOT NULL,
            compensation         jsonb,
            requires_confirmation boolean NOT NULL DEFAULT false,
            status               step_status NOT NULL DEFAULT 'pending',
            confirmed_by         uuid REFERENCES users(id),
            confirmed_at         timestamptz,
            executed_at          timestamptz,
            error                text,
            UNIQUE (rotation_id, idx)
        );
    """)

    # ── Audit log (append-only, hash-chained) ─────────────────────────────────
    op.execute("""
        CREATE TABLE audit_log (
            id             bigserial PRIMARY KEY,
            workspace_id   uuid NOT NULL REFERENCES workspaces(id),
            actor          text NOT NULL,
            action         text NOT NULL,
            target_type    text,
            target_id      text,
            before         jsonb,
            after          jsonb,
            correlation_id text,
            prev_hash      text,
            hash           text NOT NULL,
            created_at     timestamptz NOT NULL DEFAULT now()
        );
    """)
    op.execute(
        "CREATE INDEX ix_audit_log_workspace_created "
        "ON audit_log (workspace_id, created_at DESC);"
    )
    op.execute(
        "CREATE INDEX ix_audit_log_target ON audit_log (target_type, target_id);"
    )
    # N3: chain replay/verify ordered by id per workspace
    op.execute(
        "CREATE INDEX ix_audit_log_workspace_id ON audit_log (workspace_id, id);"
    )

    # ── Embeddings (pgvector / HNSW) ──────────────────────────────────────────
    op.execute("""
        CREATE TABLE embeddings (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            secret_id    uuid REFERENCES secrets(id) ON DELETE CASCADE,
            kind         text NOT NULL,
            embedding    vector(768) NOT NULL,
            meta         jsonb NOT NULL DEFAULT '{}',
            created_at   timestamptz NOT NULL DEFAULT now()
        );
    """)
    # HNSW index for approximate nearest-neighbour with cosine distance
    op.execute(
        "CREATE INDEX ix_embeddings_hnsw "
        "ON embeddings USING hnsw (embedding vector_cosine_ops);"
    )


def downgrade() -> None:
    # Drop in reverse FK order
    op.execute("DROP TABLE IF EXISTS embeddings CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE;")
    op.execute("DROP TABLE IF EXISTS rotation_steps CASCADE;")
    op.execute("DROP TABLE IF EXISTS rotations CASCADE;")
    op.execute("DROP TABLE IF EXISTS investigations CASCADE;")
    op.execute("DROP TABLE IF EXISTS severities CASCADE;")
    op.execute("DROP TABLE IF EXISTS graph_edges CASCADE;")
    op.execute("DROP TABLE IF EXISTS graph_nodes CASCADE;")
    op.execute("DROP TABLE IF EXISTS findings CASCADE;")
    op.execute("DROP TABLE IF EXISTS secrets CASCADE;")
    op.execute("DROP TABLE IF EXISTS scans CASCADE;")
    op.execute("DROP TABLE IF EXISTS repos CASCADE;")
    op.execute("DROP TABLE IF EXISTS github_installations CASCADE;")
    op.execute("DROP TABLE IF EXISTS connectors CASCADE;")
    op.execute("DROP TABLE IF EXISTS memberships CASCADE;")
    op.execute("DROP TABLE IF EXISTS users CASCADE;")
    op.execute("DROP TABLE IF EXISTS workspaces CASCADE;")

    # Drop enum types
    for t in [
        "step_status", "step_kind", "rotation_status", "investigation_status",
        "confidence", "edge_kind", "node_kind", "environment", "severity_bucket",
        "exposure_status", "secret_health", "finding_state", "scan_status",
        "connector_status", "connector_type", "role", "workspace_kind",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {t};")
