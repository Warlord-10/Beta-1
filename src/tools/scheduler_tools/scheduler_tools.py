"""Scheduler Tools — LangChain tools exposed to the agent.

These tools allow the agent to perform CRUD and enable/disable operations
on scheduled tasks using the SchedulerManager.
"""

from __future__ import annotations

import json
from langchain_core.tools import tool

from src.scheduler import task_store, scheduler_manager
from src.scheduler.models import TaskRecord
from src.config.logger import get_logger

logger = get_logger("tools.scheduler_tools")


@tool
def create_scheduled_task(
    task_description: str,
    schedule_type: str,
    schedule_params: str,
    task_plan: str = "",
) -> str:
    """Create a new scheduled task.
    
    Args:
        task_description: A clear description of what the agent needs to do.
        schedule_type: "cron", "interval", or "once".
        schedule_params: A JSON string representing the trigger parameters.
            - cron: {"hour": 9, "minute": 0, "day_of_week": "mon-fri"}
            - interval: {"hours": 2} or {"minutes": 30}
            - once: {"run_date": "2026-04-15 10:00:00"}
        task_plan: (Optional) A detailed plan or step-by-step instructions.
        
    Returns:
        Status message with the generated Task ID.
    """
    try:
        params_dict = json.loads(schedule_params)
    except json.JSONDecodeError:
        return "Error: schedule_params must be a valid JSON string."
        
    if schedule_type not in ["cron", "interval", "once"]:
        return "Error: schedule_type must be one of: cron, interval, once."

    task = TaskRecord(
        task_description=task_description,
        schedule_type=schedule_type,
        schedule_params=params_dict,
        task_plan=task_plan,
        is_enabled=True,
    )
    
    try:
        task_store.create(task)
        scheduler_manager.register_task(task)
    except Exception as e:
        logger.error(f"Failed to create task: {e}")
        return f"Error creating task: {str(e)}"
        
    return f"Successfully created scheduled task. ID: {task.task_id}"


@tool
def modify_scheduled_task(
    task_id: str,
    task_description: str = "",
    schedule_type: str = "",
    schedule_params: str = "",
    task_plan: str = "",
) -> str:
    """Modify an existing scheduled task. Provide only the fields you want to update.
    
    Args:
        task_id: The ID (or first 8 chars) of the task to modify.
        task_description: New description. Let empty to keep unchanged.
        schedule_type: New type ("cron", "interval", "once"). Let empty to keep unchanged.
        schedule_params: New trigger parameter JSON string. Let empty to keep unchanged.
        task_plan: New plan. Let empty to keep unchanged.
        
    Returns:
        Status message confirming the modification.
    """
    task = task_store.find_by_id_prefix(task_id)
    if not task:
        # Fallback to full lookup
        task = task_store.get(task_id)
        if not task:
            return f"Error: No task found with ID starting with '{task_id}'."
            
    updates = {}
    if task_description: updates["task_description"] = task_description
    if schedule_type: updates["schedule_type"] = schedule_type
    if task_plan: updates["task_plan"] = task_plan
    
    if schedule_params:
        try:
            updates["schedule_params"] = json.loads(schedule_params)
        except json.JSONDecodeError:
            return "Error: schedule_params must be a valid JSON string."
            
    if not updates:
        return "No updates provided."
        
    try:
        updated_task = task_store.update(task.task_id, **updates)
        if updated_task:
            scheduler_manager.register_task(updated_task)
            return f"Successfully updated task {task.task_id}."
        return "Error updating task in store."
    except Exception as e:
        logger.error(f"Failed to modify task {task.task_id}: {e}")
        return f"Error modifying task: {str(e)}"


@tool
def toggle_scheduled_task(task_id: str, enable: bool) -> str:
    """Enable or disable a scheduled task.
    
    Args:
        task_id: The ID (or prefix) of the task to toggle.
        enable: True to enable, False to disable.
        
    Returns:
        Confirmation message.
    """
    task = task_store.find_by_id_prefix(task_id) or task_store.get(task_id)
    if not task:
        return f"Error: No task found with ID '{task_id}'."
        
    try:
        updated_task = task_store.set_enabled(task.task_id, enable)
        if updated_task:
            scheduler_manager.register_task(updated_task)
            state = "enabled" if enable else "disabled"
            return f"Task {task.task_id} has been {state}."
        return "Error toggling task."
    except Exception as e:
        logger.error(f"Failed to toggle task {task.task_id}: {e}")
        return f"Error toggling task: {str(e)}"


@tool
def delete_scheduled_task(task_id: str) -> str:
    """Permanently delete a scheduled task.
    
    Args:
        task_id: The ID (or prefix) of the task to delete.
        
    Returns:
        Confirmation message.
    """
    task = task_store.find_by_id_prefix(task_id) or task_store.get(task_id)
    if not task:
        return f"Error: No task found with ID '{task_id}'."
        
    try:
        scheduler_manager.unregister_task(task.task_id)
        deleted = task_store.delete(task.task_id)
        if deleted:
            return f"Task {task.task_id} successfully deleted."
        return "Failed to delete task from store."
    except Exception as e:
        logger.error(f"Failed to delete task {task.task_id}: {e}")
        return f"Error deleting task: {str(e)}"


@tool
def list_scheduled_tasks() -> str:
    """List all scheduled tasks with their IDs, descriptions, schedules, and status.
    
    Returns:
        A formatted list of all scheduled tasks in the system.
    """
    try:
        tasks = task_store.list_all()
        if not tasks:
            return "No scheduled tasks found."
            
        summary = ["Scheduled Tasks:"]
        for task in tasks:
            summary.append(f"- {task.summary()}")
            
        return "\n".join(summary)
    except Exception as e:
        logger.error(f"Failed to list tasks: {e}")
        return f"Error retrieving tasks: {str(e)}"
