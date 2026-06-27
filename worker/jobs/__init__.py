"""
Job registry — all arq job functions.
Each function is idempotent and keyed (rotation_id/secret_id/repo_id).

Jobs (filled in per milestone):
  M3: demo_session_gc
  M5: rotation_step
  M7: investigate_secret, plan_rotation
  M8: scan_repo, ingest_findings
"""
from worker.jobs.health import health_check

JOB_REGISTRY = [
    health_check,
]
