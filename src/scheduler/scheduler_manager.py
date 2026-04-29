"""Scheduler Manager — Core orchestration for scheduled tasks.

Wraps APScheduler's BackgroundScheduler.
Responsible for:
- Registering APScheduler jobs from TaskRecords
- Executing tasks when they fire (invoking the main_graph)
- Keeping in sync with the TaskStore
"""

from __future__ import annotations

import logging
import uuid
import json
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger

from langchain_core.messages import HumanMessage, SystemMessage

from src.scheduler.models import TaskRecord
from src.scheduler.task_store import TaskStore
from src.config.logger import get_logger
from src.workflow import main_graph

logger = get_logger("scheduler.manager")

# Colors for terminal output
class Colors:
    RESET      = "\033[0m"
    BOLD       = "\033[1m"
    GREEN      = "\033[38;5;114m"
    BLUE       = "\033[38;5;111m"
    MAGENTA    = "\033[38;5;170m"


class SchedulerManager:
    """Singleton manager for scheduled tasks."""
    _instance = None

    def __new__(cls, task_store: Optional[TaskStore] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_scheduler(task_store or TaskStore())
        return cls._instance

    def attach_callback(self, cb):
        self.send_msg = cb

    def _init_scheduler(self, task_store: TaskStore):
        self.send_msg = None
        self.store = task_store
        
        # Suppress apscheduler noisy logs
        logging.getLogger('apscheduler').setLevel(logging.WARNING)

        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        logger.info("SchedulerManager started.")

        # Load all enabled tasks from DB and schedule them
        tasks = self.store.list_all_active()
        logger.info(f"Loaded {len(tasks)} active tasks from store into memory.")
        for task in tasks:
            self._schedule_job(task)

    def _get_trigger(self, task: TaskRecord):
        """Convert schedule_type directly to an APScheduler trigger."""
        params = task.schedule_params
        if task.schedule_type == "cron":
            return CronTrigger(**params)
        elif task.schedule_type == "interval":
            return IntervalTrigger(**params)
        elif task.schedule_type == "once":
            run_date = params.get("run_date")
            if run_date:
                # Assuming run_date is ISO format, parse it or pass it.
                # APScheduler can accept strings or datetime objects
                return DateTrigger(run_date=run_date)
            return None
        return None

    def _schedule_job(self, task: TaskRecord):
        """Add or update an APScheduler job for this task."""
        trigger = self._get_trigger(task)
        if not trigger:
            logger.warning("Could not create trigger for task %s, type %s", task.task_id, task.schedule_type)
            return

        self.scheduler.add_job(
            self._execute_task,
            trigger=trigger,
            args=[task.task_id],
            id=task.task_id,
            replace_existing=True,
            misfire_grace_time=60, # Allow up to 60s delay if busy
        )
        logger.info("Scheduled job for task %s", task.task_id)

        # Update next_run_at in store
        job = self.scheduler.get_job(task.task_id)
        if job and job.next_run_time:
            self.store.update(task.task_id, next_run_at=job.next_run_time.isoformat())

    def _execute_task(self, task_id: str):
        """Fired by APScheduler. Loads context, invokes graph, prints output."""
        
        assert self.send_msg is not None, "No callback attached for scheduled task execution."
        
        task = self.store.get(task_id)
        if not task or not task.is_enabled:
            logger.warning("Job fired for disabled or missing task %s", task_id)
            return

        logger.info("Execute task %s: %s", task_id[:8], task.task_description)
        
        # Build context
        context = f"Scheduled Task Execution:\nDescription: {task.task_description}\n"
        if task.task_plan:
            context += f"Plan Details: {task.task_plan}\n"
            
        context += "Please execute this task and provide a final result."

        print(f"\n{Colors.MAGENTA}{Colors.BOLD}⏰ Scheduled Task Fired ▸{Colors.RESET} {task.task_description}")
        
        self.send_msg(context)

        # Update next_run_at in store if recurred
        job = self.scheduler.get_job(task_id)
        if job:
            nxt = job.next_run_time.isoformat() if job.next_run_time else None
            self.store.update(task_id, next_run_at=nxt)


    # ── Public API (used by LangChain Tools) ──────────────────────────────────

    def register_task(self, task: TaskRecord):
        """Called when a new task is created or updated."""
        if task.is_enabled:
            self._schedule_job(task)
        else:
            self.unregister_task(task.task_id)
            
    def unregister_task(self, task_id: str):
        """Remove from APScheduler."""
        if self.scheduler.get_job(task_id):
            self.scheduler.remove_job(task_id)
            self.store.update(task_id, next_run_at=None)

    def shutdown(self):
        """Stop scheduler."""
        self.scheduler.shutdown(wait=False)
        logger.info("SchedulerManager shut down.")

