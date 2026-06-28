"""
Job registry — all arq job functions.
Each function is idempotent and keyed (rotation_id/secret_id/repo_id).

Jobs (filled in per milestone):
  M3: sweep_demo_workspaces (cron, every 15 min)
  M5: investigate_secret
  M6: rotation_step, plan_rotation
  M8: scan_repo, ingest_findings
"""
from worker.jobs.health import health_check
from worker.jobs.investigate import investigate_secret
from worker.jobs.run_rotation_step import run_rotation_step
from worker.jobs.sweeper import sweep_demo_workspaces

JOB_REGISTRY = [
    health_check,
    sweep_demo_workspaces,
    investigate_secret,
    run_rotation_step,
]
