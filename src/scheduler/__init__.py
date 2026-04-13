"""scheduler module.

Exports the TaskRecord model, the task_store singleton instance,
and the scheduler_manager singleton orchestrator.
"""

from src.scheduler.models import TaskRecord
from src.scheduler.task_store import TaskStore
from src.scheduler.scheduler_manager import SchedulerManager

# Singletons initialized here for global usage
task_store = TaskStore()
scheduler_manager = SchedulerManager(task_store)

__all__ = [
    "TaskRecord",
    "task_store",
    "scheduler_manager",
]
