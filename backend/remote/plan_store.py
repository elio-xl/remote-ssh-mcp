from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

from backend.paths import data_dir
from .models import ExecutionPlan, PlanStatus, plan_from_dict, plan_to_dict


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = data_dir()
DEFAULT_PLAN_PATH = DEFAULT_DATA_DIR / "plans.json"


class PlanStore:
    def __init__(self, path: Path = DEFAULT_PLAN_PATH) -> None:
        self.path = path

    def save(self, plan: ExecutionPlan) -> ExecutionPlan:
        plans = {p.id: p for p in self.list_plans(limit=100000)}
        plans[plan.id] = plan
        self._write_all(list(plans.values()))
        return plan

    def get(self, plan_id: str) -> ExecutionPlan | None:
        return next((p for p in self.list_plans(limit=100000) if p.id == plan_id), None)

    def list_plans(
        self,
        *,
        target_alias: str | None = None,
        status: PlanStatus | None = None,
        limit: int = 50,
    ) -> list[ExecutionPlan]:
        plans = self._read_all()
        now = time.time()
        changed = False
        normalized: list[ExecutionPlan] = []
        for plan in plans:
            if plan.expires_at is not None and plan.expires_at < now and plan.status in {"pending_approval", "approved"}:
                plan = replace(plan, status="expired")
                changed = True
            normalized.append(plan)
        if changed:
            self._write_all(normalized)
        filtered = [p for p in normalized if (not target_alias or p.target_alias == target_alias)]
        if status:
            filtered = [p for p in filtered if p.status == status]
        filtered.sort(key=lambda p: p.created_at, reverse=True)
        return filtered[: max(1, limit)]

    def transition(self, plan_id: str, **updates: object) -> ExecutionPlan:
        plan = self.get(plan_id)
        if plan is None:
            raise KeyError(f"Plan '{plan_id}' not found")
        updated = replace(plan, **updates)
        self.save(updated)
        return updated

    def _read_all(self) -> list[ExecutionPlan]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        return [plan_from_dict(item) for item in data if isinstance(item, dict)]

    def _write_all(self, plans: list[ExecutionPlan]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = [plan_to_dict(plan) for plan in plans]
        self.path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


_default_store = PlanStore()


def save(plan: ExecutionPlan) -> ExecutionPlan:
    return _default_store.save(plan)


def get(plan_id: str) -> ExecutionPlan | None:
    return _default_store.get(plan_id)


def list_plans(**kwargs: object) -> list[ExecutionPlan]:
    return _default_store.list_plans(**kwargs)  # type: ignore[arg-type]


def transition(plan_id: str, **updates: object) -> ExecutionPlan:
    return _default_store.transition(plan_id, **updates)
