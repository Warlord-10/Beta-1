---
name: organize_files
description: Inspect a directory and tidy it — sort, rename, or clean up files safely.
---
## When to use
"Organize", "clean up", "sort these files", "tidy this folder", "rename these".
Any task that moves, renames, groups, or deletes files on disk.

## Procedure
1. **Look before touching.** `list_directory` the target and `get_file_info` on anything
   ambiguous. Understand what's there before proposing any change.
2. Propose a scheme and state it back: how files will be grouped/renamed and why. If the
   task is vague ("organize my downloads"), pick a sensible default (by type, then date)
   and say what you chose.
3. **Dry run first.** Print the exact planned moves/renames as a list — old path → new path —
   before executing anything.
4. Execute with `agent_bash` (`mkdir -p`, `mv`, `rmdir`). Move, don't delete, unless the
   task explicitly says to delete. Never overwrite an existing file — check first and
   suffix on collision.
5. Verify: `list_directory` the result and confirm counts match (nothing lost).

## Rules
- Deletion is irreversible — confirm intent in the plan and never delete on a guess.
- Keep a record of every move in your final answer so it can be undone by hand.

## Output
The final layout, the count of files moved/renamed/deleted, and the full move list.
