# Beta-1 — Personal AI Assistant

**Beta-1** is a fully local, voice-enabled, multi-agent personal assistant built by Deepanshu Joshi. It classifies user intent, executes tool-augmented tasks, delegates complex work to specialized sub-agents, and speaks responses aloud with word-level text synchronization.

> This README is authoritative system context. Agents should read it to understand the full architecture, tool inventory, threading model, configuration surface, and design constraints before modifying any component.

---

## Table of Contents

1. [High-Level Overview](#1-high-level-overview)
2. [Project Structure](#2-project-structure)
3. [End-to-End Message Flow](#3-end-to-end-message-flow)
4. [Agent Architecture](#4-agent-architecture)
5. [LangGraph Workflow](#5-langgraph-workflow)
6. [State Schema](#6-state-schema)
7. [Tool Inventory](#7-tool-inventory)
8. [Voice Pipeline — TTS](#8-voice-pipeline--tts)
9. [Voice Pipeline — ASR](#9-voice-pipeline--asr)
10. [LLM Factory & Registry](#10-llm-factory--registry)
11. [Scheduler System](#11-scheduler-system)
12. [Threading Model](#12-threading-model)
13. [Configuration & Settings](#13-configuration--settings)
14. [Prompts](#14-prompts)
15. [CLI & TUI](#15-cli--tui)
16. [Quick Start](#16-quick-start)
17. [Environment Variables](#17-environment-variables)
18. [Design Constraints & Known Limitations](#18-design-constraints--known-limitations)

---

## 1. High-Level Overview

```
┌────────────────────────────────────────────────────────────────────────┐
│                         Beta-1 Runtime                                  │
│                                                                          │
│  User speaks / types                                                    │
│       │                                                                  │
│       ▼                                                                  │
│  [ASR] ──────────────────────── (voice mode, WIP)                      │
│       │                                                                  │
│       ▼                                                                  │
│  [Chat Agent] ── simple ──────────────────────────▶ LLM response       │
│       │                                                                  │
│       └── complex ──▶ [Planner] ──▶ [Supervisor] ──▶ [Sub-agents]     │
│                                           │                              │
│                                    [Format Response]                    │
│                                           │                              │
│                                           ▼                              │
│  [TTS Pipeline] ◀── token stream ── response text                      │
│       │                                                                  │
│       ├── KokoroTTS.synthesize() → audio_queue                         │
│       ├── OutputStream callback → speaker (realtime)                   │
│       └── word_callback thread → terminal (word-by-word, synced)       │
└────────────────────────────────────────────────────────────────────────┘
```

**Key characteristics:**
- Entry point: `main.py` — runs an interactive REPL with a colored terminal prompt
- Primary LLM: Gemma 4 31B (via Google API / OpenRouter)
- Voice: Kokoro TTS (24 kHz, word-level sync) + Whisper / MLX-Whisper ASR
- Orchestration: LangGraph with `InMemorySaver` for per-session conversation persistence
- Scheduler: APScheduler (cron / interval / one-shot) backed by SQLite
- TUI: Textual-based terminal UI (`src/cli/tui.py`) — currently inactive (commented in `main.py`)

---

## 2. Project Structure

```
Beta-1/
├── main.py                        # Entry point — Pipeline class, REPL loop
├── pyproject.toml                 # Dependencies (uv)
├── .env                           # API keys (never committed)
│
├── logs/                          # Daily log files: YYYY-MM-DD.log
├── data/
│   └── scheduler.sqlite           # APScheduler task store (SQLite)
│
└── src/
    ├── workflow.py                # Main LangGraph graph (planning → supervisor → format)
    │
    ├── states/
    │   └── main_state.py          # MainState, TaskItem, CodingState TypedDicts
    │
    ├── agents/
    │   ├── chatagent/
    │   │   ├── chat_agent.py      # ChatAgent class — entry point, stream(), chat()
    │   │   └── __init__.py
    │   │
    │   ├── planningagent/
    │   │   ├── planning_agent.py  # Structured output planner → PlanOutput
    │   │   ├── agent_tools.py     # Tools available during planning
    │   │   └── __init__.py
    │   │
    │   ├── supervisoragent/
    │   │   ├── supervisor_agent.py  # Orchestrator loop — routes tasks to sub-agents
    │   │   └── __init__.py
    │   │
    │   ├── codeagent/
    │   │   ├── code_agent.py      # ReAct loop — write, lint, debug code
    │   │   ├── agent_tools.py
    │   │   └── __init__.py
    │   │
    │   ├── systemagent/
    │   │   ├── system_agent.py    # ReAct loop — shell, git, packages (built, not wired)
    │   │   ├── agent_tools.py
    │   │   └── __init__.py
    │   │
    │   ├── fileagent/
    │   │   ├── file_agent.py      # ReAct loop — file CRUD (built, not wired)
    │   │   ├── agent_tools.py
    │   │   └── __init__.py
    │   │
    │   └── researchagent/
    │       ├── search_agent.py    # ReAct loop — web search (built, not wired)
    │       ├── agent_tools.py
    │       └── __init__.py
    │
    ├── tools/
    │   ├── file_tools/            # read_file, write_file, list_directory, search_*, etc.
    │   │   ├── read_file.py
    │   │   ├── write_file.py
    │   │   ├── list_directory.py
    │   │   ├── search_files.py
    │   │   ├── search_content.py
    │   │   ├── get_file_info.py
    │   │   ├── create_directory.py
    │   │   ├── move_file.py
    │   │   ├── copy_file.py
    │   │   ├── delete_file.py
    │   │   ├── change_directory.py
    │   │   ├── _helpers.py
    │   │   └── __init__.py
    │   │
    │   ├── code_tools/            # write_code, lint_code, debug_code
    │   │   └── __init__.py
    │   │
    │   ├── system_tools/          # bash_exec, git_ops, install_pkg, env_vars, process_mgmt
    │   │   ├── safe_bash.py       # Restricted bash (allowlist-based) — used by Chat Agent
    │   │   ├── bash_exec.py
    │   │   ├── git_ops.py
    │   │   ├── install_pkg.py
    │   │   ├── env_vars.py
    │   │   ├── process_mgmt.py
    │   │   └── __init__.py
    │   │
    │   ├── search_tools/          # web_search, browse_web
    │   │   ├── browse_web.py
    │   │   └── __init__.py
    │   │
    │   └── scheduler_tools/       # create/modify/delete/toggle/list scheduled tasks
    │       ├── scheduler_tools.py
    │       └── __init__.py
    │
    ├── voice/
    │   ├── base.py                # BaseTTS abstract class
    │   ├── kokoro_provider.py     # KokoroTTS — primary TTS with word-sync streaming
    │   ├── supertonic_provider.py # SupertonicTTS — alternative TTS
    │   ├── kitten_provider.py     # KittenProvider — alternative TTS
    │   └── factory.py             # get_tts_engine(provider, config) → BaseTTS
    │
    ├── asr/
    │   ├── base.py                # BaseASR abstract class
    │   ├── whisper_provider.py    # WhisperASR — faster-whisper backend
    │   ├── mlx_provider.py        # MLXWhisperASR — Apple Silicon optimized
    │   ├── vad.py                 # VoiceActivityDetector — Silero VAD
    │   ├── audio_stream.py        # ASRStream — live mic input + transcription
    │   └── factory.py             # get_asr_engine(config) → BaseASR
    │
    ├── scheduler/
    │   ├── models.py              # TaskRecord dataclass
    │   ├── task_store.py          # TaskStore — SQLite CRUD with thread lock
    │   ├── scheduler_manager.py   # SchedulerManager — APScheduler wrapper (singleton)
    │   └── __init__.py
    │
    ├── llms/
    │   ├── registry.py            # MODEL_REGISTRY dict + resolve_model()
    │   ├── factory.py             # LLMFactory.create() — returns LangChain model
    │   ├── cost_tracker.py        # CostTracker + CostTrackerCallback
    │   └── __init__.py            # Exports: llm_factory, cost_tracker
    │
    ├── prompts/
    │   ├── loader.py              # load_prompt(name) → reads src/prompts/{name}.md
    │   ├── chat_agent.md          # Persona, tonality, delegation rules
    │   ├── planning_agent.md      # Plan generation instructions
    │   ├── supervisor_agent.md    # Task routing and validation
    │   ├── coding_agent.md        # Code writing agent instructions
    │   └── system_agent.md        # Shell/system agent instructions
    │
    ├── utils/
    │   ├── text_utils.py          # accumulate_sentences(), clean_text()
    │   └── cli_old.py             # Archived Textual TUI (reference only)
    │
    ├── cli/
    │   ├── tui.py                 # TUI App (Textual) — inactive
    │   ├── widgets.py             # AudioBars, ChatMessage widgets
    │   └── panes.py               # SettingsPane, SchedulesPane, TasksPane, etc.
    │
    └── config/
        ├── settings.py            # All tunable settings — TTS provider, log mode, CWD
        └── logger.py              # get_logger(name) — returns child of "beta1" root logger
```

---

## 3. End-to-End Message Flow

### Input → Response

```
1. User types at terminal prompt ("[cwd] You ▸ ")
   │
2. Pipeline.run() reads user_input (str)
   │
3. ChatAgent.stream(user_input)
   │  ├── Wraps input in HumanMessage
   │  ├── Invokes LangGraph ReAct agent (create_agent from langchain)
   │  ├── LLM uses system prompt (chat_agent.md) with persona
   │  └── Yields AIMessageChunk.content tokens
   │
4. Pipeline.process_llm_stream(token_generator)
   │  └── accumulate_sentences() buffers tokens → yields complete sentences
   │       Break triggers: ".", "!", "?" (always); "," if buffer > 80 chars;
   │                       " " if buffer > 150 chars; flush remainder at end
   │       Each sentence → llm_chunk_queue.put(sentence)
   │
5. [Parallel — TTS daemon thread] process_tts_stream()
   │  └── llm_chunk_queue.get() → sentence string
   │       └── KokoroTTS.synthesize(sentence, word_callback=_print_word)
   │            ├── clean_text(sentence)          # strip ASCII, normalize whitespace
   │            ├── KPipeline(sentence, ...) → list of (gs, ps, audio) segments
   │            ├── Build words_with_offsets: [(word, offset_secs), ...]
   │            │    offset = segment_cursor + (word_index / n_words) * segment_duration
   │            ├── audio_queue.put(('_on_start', _on_start_fn))
   │            └── audio_queue.put(audio_chunk) for each segment
   │
6. [Audio streaming thread — sounddevice OutputStream]
   │  └── callback(outdata, frames, ...) fires continuously
   │       ├── Dequeues from audio_queue
   │       ├── On ('_on_start', fn): calls fn() → spawns word-printer daemon thread
   │       ├── On numpy array: concatenates to leftover buffer
   │       └── Writes frames to speaker output (fills outdata)
   │
7. [Word-printer daemon thread — one per sentence]
   │  └── _printer() iterates words_with_offsets:
   │       ├── remaining = offset - (time.monotonic() - t0)
   │       ├── time.sleep(remaining) if > 0
   │       └── word_callback(word) → print(word, end=" ", flush=True)
   │
8. Terminal shows words in real-time, synchronized with spoken audio
```

### Chat Agent — Decision Routing

```
User query
    │
    ▼
Chat Agent LLM + tools
    │
    ├── Simple / tool-handled path:
    │   ├── Greetings, factual Q&A → LLM responds directly
    │   ├── "Show me config.py" → read_file() → LLM summarizes
    │   ├── "List src/ directory" → list_directory() → LLM formats
    │   ├── "Schedule a task" → create_scheduled_task() → LLM confirms
    │   └── "Run git status" → safe_bash() → LLM presents result
    │
    └── Complex path (delegate_to_planner tool called):
        │   task_summary string passed as arg
        │
        ▼
        Planning Agent
        ├── Reads codebase with tools (read_file, list_directory, search_*)
        ├── Produces PlanOutput (structured JSON):
        │   ├── task_summary: str
        │   ├── implementation_plan: str (narrative)
        │   └── action_checklist: list[PlanStep]
        │       └── PlanStep: id, intent, assigned_agent, task_description,
        │                      input_context, depends_on, expected_output
        │
        ▼
        Supervisor Agent (loop, max 15 iterations)
        ├── Reads action_checklist, filters pending tasks
        ├── If 1 pending → route directly (no LLM needed)
        ├── If N pending → LLM picks next_agent + next_task_id
        │
        ├── Routes to: coding_agent (currently active)
        │             system_agent  (wired in code, routing WIP)
        │             file_agent    (wired in code, routing WIP)
        │             search_agent  (wired in code, routing WIP)
        │
        ├── Sub-agent executes, result saved to completed_tasks
        └── Loop back until all tasks done or iteration limit hit
            │
            ▼
        Format Response Node
        └── Extracts final_response, logs token cost summary
```

---

## 4. Agent Architecture

### Chat Agent (`src/agents/chatagent/chat_agent.py`)

| Property | Value |
|---|---|
| Type | LangChain `create_agent` (ReAct) |
| LLM | `GEMMA_4_31B` — temp=0.7, max_tokens=4096 |
| System prompt | `src/prompts/chat_agent.md` |
| Checkpointer | `InMemorySaver` (per thread_id) |
| State schema | `MainState` |

**Public API:**
```python
class ChatAgent:
    def __init__(self, config: dict)          # config = {"configurable": {"thread_id": str}}
    def chat(self, user_input: str) -> dict   # blocking invoke
    def stream(self, user_input: str)         # generator → yields str token chunks
```

**Stream mode:** `stream_mode="messages"`, `version="v2"` — yields `AIMessageChunk` tokens, filters non-string content.

**Tools available to Chat Agent:**
- `read_file`, `list_directory`, `get_file_info`, `search_files`, `search_content`
- `safe_bash` (allowlist-restricted shell)
- `delegate_to_planner` (triggers complex workflow)
- `create_scheduled_task`, `delete_scheduled_task`, `list_scheduled_tasks`, `modify_scheduled_task`, `toggle_scheduled_task`

---

### Planning Agent (`src/agents/planningagent/planning_agent.py`)

| Property | Value |
|---|---|
| Type | Structured output + optional ReAct |
| LLM | `GEMMA_4_31B` — temp=0.7, max_tokens=8192 |
| System prompt | `src/prompts/planning_agent.md` |
| Output model | `PlanOutput` (Pydantic) |

**PlanOutput schema:**
```python
class PlanStep(BaseModel):
    id: str
    intent: str
    assigned_agent: str        # "coding_agent", "file_agent", "system_agent", "search_agent"
    task_description: str
    input_context: str
    depends_on: list[str]      # IDs of prerequisite steps
    expected_output: str

class PlanOutput(BaseModel):
    task_summary: str
    implementation_plan: str
    action_checklist: list[PlanStep]
```

**Converts `PlanStep` → `TaskItem`** for supervisor consumption.

**Tools available during planning:** `read_file`, `list_directory`, `search_content`, `search_files`, `change_directory`

---

### Supervisor Agent (`src/agents/supervisoragent/supervisor_agent.py`)

| Property | Value |
|---|---|
| Type | Custom orchestrator with loop graph |
| LLM | `GEMMA_4_31B` — temp=0, max_tokens=1024 (routing only) |
| System prompt | `src/prompts/supervisor_agent.md` |
| Max iterations | 15 (`MAX_SUPERVISOR_ITERATIONS`) |

**Routing logic:**
```python
def supervisor_node(state: MainState) -> dict:
    pending = [t for t in action_checklist if t not in completed_ids]
    if not pending: return {"next_agent": "FINISH"}
    if iteration >= 15: return {"next_agent": "FINISH"}
    if len(pending) == 1: return {"next_agent": pending[0].assigned_agent}
    # else: LLM picks with SupervisorRoutingOutput(next_agent, next_task_id)
```

**Sub-graph routing:**
- `coding_agent` → `coding_agent_wrapper()` → invokes `coding_agent_graph`
- `FINISH` → `END`

---

### Code Agent (`src/agents/codeagent/code_agent.py`)

| Property | Value |
|---|---|
| Type | LangGraph ReAct sub-graph |
| LLM | `GEMMA_4_31B` — temp=0.7, max_tokens=4096 |
| State | `CodingState` (not `MainState`) |
| Max iterations | 10 (`MAX_CODING_ITERATIONS`) |
| System prompt | `src/prompts/coding_agent.md` |

**Tools:** `write_code`, `lint_code`, `debug_code`, `read_file`, `list_directory`, `search_files`, `search_content`

**Sub-graph structure:**
```
START → coding_node → [tools_condition] → tools → coding_node
                    ↘ END (no more tool calls)
```

---

### System Agent (`src/agents/systemagent/system_agent.py`)

| Property | Value |
|---|---|
| Type | LangGraph ReAct sub-graph |
| LLM | `GEMINI_FLASH` — temp=0, max_tokens=4096 |
| Status | **Built, not wired into supervisor routing** |
| System prompt | `src/prompts/system_agent.md` |

**Tools:** `bash_exec`, `git_ops`, `install_pkg`, `env_vars`, `process_mgmt`, all file tools

---

### File Agent (`src/agents/fileagent/file_agent.py`)

| Property | Value |
|---|---|
| Type | LangGraph ReAct sub-graph |
| LLM | `GEMINI_FLASH` — temp=0 |
| Status | **Built, not wired into supervisor routing** |
| Max iterations | 10 |

**Tools:** File CRUD tools (read, write, copy, move, delete, list, mkdir, search)

---

### Research/Search Agent (`src/agents/researchagent/search_agent.py`)

| Property | Value |
|---|---|
| Type | LangGraph ReAct sub-graph |
| LLM | `GEMINI_FLASH` — temp=0 |
| Status | **Built, not wired into supervisor routing** |
| Max iterations | 10 |

**Tools:** `search_web` (DuckDuckGo), `browse_web` (URL fetch)

---

## 5. LangGraph Workflow

### Main Graph (`src/workflow.py`)

```python
StateGraph(MainState)
├── Node "planning"       → planning_node()       # invokes planning_agent_graph
├── Node "supervisor"     → supervisor_node()     # invokes supervisor_agent_graph
├── Node "format_response"→ format_response()     # calls format_response_node()
│
├── Edge: START → planning
├── Edge: planning → supervisor
├── Edge: supervisor → format_response
└── Edge: format_response → END

Compiled with: InMemorySaver checkpointer
```

### Supervisor Sub-graph

```python
StateGraph(MainState)
├── Node "supervisor"    → supervisor_node()
├── Node "coding_agent"  → coding_agent_wrapper()
│
├── Edge: START → supervisor
├── ConditionalEdge: supervisor → route_after_supervisor()
│   ├── "coding_agent" → coding_agent
│   └── "FINISH"       → END
└── Edge: coding_agent → supervisor   # always loops back
```

### Coding Sub-graph

```python
StateGraph(CodingState)
├── Node "coding_node"   → coding_node()
├── Node "tools"         → ToolNode(all_coding_tools)
│
├── Edge: START → coding_node
├── ConditionalEdge: coding_node → tools_condition()
│   ├── "tools" → tools
│   └── END
└── Edge: tools → coding_node
```

---

## 6. State Schema

### `MainState` (`src/states/main_state.py`)

```python
class TaskItem(TypedDict):
    id: str
    task_description: str
    assigned_agent: str
    input_context: str
    status: str                    # "pending" | "in_progress" | "completed" | "failed"
    result: str

class MainState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]   # append-only
    user_query: str
    complexity: str                                         # "simple" | "complex"
    implementation_plan: str
    action_checklist: list[TaskItem]
    current_task: TaskItem
    completed_tasks: Annotated[list[TaskItem], operator.add]  # append-only
    final_response: str
    cwd: str                                               # persists across turns
    iteration: int                                         # supervisor loop counter
    next_agent: str                                        # supervisor routing target
    extra_context: Annotated[list[dict], operator.add]    # append-only
```

**Initial state** (set in `ChatAgent.stream()` / `ChatAgent.chat()`):
```python
{
    "messages": [HumanMessage(content=user_input)],
    "user_query": user_input,
    "complexity": "",
    "implementation_plan": "",
    "action_checklist": [],
    "current_task": {},
    "completed_tasks": [],
    "final_response": "",
    "cwd": "/",
    "iteration": 0,
    "next_agent": "",
}
```

### `CodingState` (used only by code agent)

```python
class CodingState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    current_task: TaskItem
    completed_tasks: Annotated[list[TaskItem], operator.add]
    cwd: str
```

---

## 7. Tool Inventory

### File Tools (`src/tools/file_tools/`)

| Tool | Signature | Notes |
|---|---|---|
| `read_file` | `(file_path: str) → str` | Returns file contents or error message |
| `write_file` | `(file_path: str, content: str, overwrite: bool) → str` | Creates parent dirs |
| `list_directory` | `(directory_path: str) → str` | Emoji icons, file sizes |
| `create_directory` | `(dir_path: str) → str` | Recursive mkdir |
| `move_file` | `(src: str, dst: str) → str` | Rename or relocate |
| `copy_file` | `(src: str, dst: str) → str` | Full copy |
| `delete_file` | `(file_path: str) → str` | Permanent delete |
| `get_file_info` | `(file_path: str) → str` | Size, type, permissions, timestamps |
| `search_files` | `(directory: str, query: str, max_results: int, file_extension: Optional[str]) → str` | Glob + name search. Skips: `.git`, `.venv`, `venv`, `node_modules`, `__pycache__`, `.tox`, `.mypy_cache`, `.pytest_cache` |
| `search_content` | `(directory: str, query: str, max_results: int, file_extension: Optional[str]) → str` | Grep-like content search |
| `change_directory` | `(directory_path: str) → str` | Updates `cwd` in agent state |

### Code Tools (`src/tools/code_tools/`)

| Tool | Signature | Notes |
|---|---|---|
| `write_code` | `(file_path: str, code: str, language: str) → str` | Writes code to file |
| `lint_code` | `(file_path: str) → str` | Runs linting (stub implementation) |
| `debug_code` | `(file_path: str, error_msg: str) → str` | Analyzes errors, suggests fixes |

### System Tools (`src/tools/system_tools/`)

| Tool | Signature | Notes |
|---|---|---|
| `bash_exec` | `(command: str, timeout: int) → str` | Full shell execution |
| `safe_bash` | `(command: str, timeout: int) → str` | Allowlist-restricted — Chat Agent only |
| `git_ops` | `(operation: str, args: str, repo_path: str) → str` | Allowed ops: status, log, diff, branch, add, commit, pull, push, checkout, stash, show, remote |
| `install_pkg` | `(package_name: str, package_manager: str) → str` | pip / npm / brew |
| `env_vars` | `(action: str, var_name: str, var_value: str) → str` | get / set / unset |
| `process_mgmt` | `(command: str, process_name: str) → str` | list / kill / info |

### Scheduler Tools (`src/tools/scheduler_tools/scheduler_tools.py`)

| Tool | Signature | Notes |
|---|---|---|
| `create_scheduled_task` | `(task_description, schedule_type, schedule_params, task_plan) → str` | schedule_type: "cron" \| "interval" \| "once" |
| `modify_scheduled_task` | `(task_id, task_description?, schedule_type?, schedule_params?, task_plan?) → str` | Partial updates |
| `toggle_scheduled_task` | `(task_id, enable: bool) → str` | Enable/disable |
| `delete_scheduled_task` | `(task_id) → str` | Permanent |
| `list_scheduled_tasks` | `() → str` | All tasks with status |

### Search Tools (`src/tools/search_tools/`)

| Tool | Signature | Notes |
|---|---|---|
| `search_web` | `(query: str) → str` | DuckDuckGoSearchRun |
| `browse_web` | `(url: str) → str` | Fetches and returns page content |

---

## 8. Voice Pipeline — TTS

### Architecture Overview

```
LLM token stream
      │
      ▼
accumulate_sentences()  [main thread]
      │
      ▼
llm_chunk_queue (Queue)
      │
      ▼
process_tts_stream()  [tts daemon thread]
      │
      ▼
KokoroTTS.synthesize(sentence, word_callback)
      ├── clean_text(sentence)
      ├── KPipeline runs: yields (gs, ps, audio) segments
      ├── Build words_with_offsets: [(word, secs_from_start), ...]
      ├── audio_queue.put(('_on_start', _on_start_fn))
      └── audio_queue.put(audio_array)  × N segments
                    │
                    ▼
            audio_queue (Queue)  [shared between tts thread and audio callback]
                    │
                    ▼
        sounddevice OutputStream callback()  [audio thread]
            ├── Get items from audio_queue
            ├── ('_on_start', fn) → fn()  → spawns word-printer thread
            ├── numpy array → concat to leftover buffer
            └── Write frames to outdata (speaker)
                    │
                    ▼
            word-printer daemon thread  [one per sentence]
                ├── t0 = time.monotonic()  (set when audio starts)
                ├── For each (word, offset) in words_with_offsets:
                │       sleep(max(0, offset - elapsed))
                │       word_callback(word)
                └── _print_word(word) → print(word, end=" ", flush=True)
```

### `KokoroTTS` (`src/voice/kokoro_provider.py`)

```python
class KokoroTTS(BaseTTS):
    voice_name: str = "af_heart"
    sample_rate: int = 24000
    speed: float = 1.3
    audio_queue: queue.Queue          # holds numpy arrays and ('_on_start', fn) tuples
    pipeline: KPipeline               # Kokoro neural TTS pipeline

    def synthesize(text: str, word_callback: Optional[Callable[[str], None]]) -> None:
        # 1. clean_text(text)
        # 2. Run pipeline → collect segments [(gs, audio)]
        # 3. Build word timing offsets per segment
        # 4. Put ('_on_start', fn) into audio_queue
        # 5. Put each audio chunk into audio_queue

    def stream() -> sd.OutputStream:
        # Returns OutputStream with callback that:
        # - Dequeues from audio_queue
        # - Handles ('_on_start', fn) sentinel by calling fn()
        # - Fills outdata with audio frames

    def play(text: str, block: bool) -> None:
        # Blocking playback (used without streaming)
```

**Word timing formula:**
```
segment_cursor = sum of all previous segment durations (seconds)
word_offset = segment_cursor + (word_index / n_words) * segment_duration
```

**Audio queue item types:**
- `numpy.ndarray` — raw float32 audio frames
- `tuple('_on_start', Callable)` — signals start of a new sentence

### Other TTS Providers

**`SupertonicTTS`** (`src/voice/supertonic_provider.py`): Blocking synthesis, no word-sync support.

**`KittenProvider`** (`src/voice/kitten_provider.py`): Blocking synthesis, no word-sync support.

**Active provider is set in `src/config/settings.py`** via `TTS_PROVIDER = "kokoro"`.

### Text Utility: `accumulate_sentences` (`src/utils/text_utils.py`)

```python
def accumulate_sentences(chunks) -> Generator[str, None, None]:
    """Accumulates LLM token stream into sentence-sized chunks for TTS."""
    buffer = ""
    for chunk in chunks:
        for char in chunk:
            buffer += char
            if char in ".!?":          yield buffer.strip(); buffer = ""
            elif char == "," and len(buffer) > 80:   yield buffer.strip(); buffer = ""
            elif char == " " and len(buffer) > 150:  yield buffer.strip(); buffer = ""
    if buffer.strip(): yield buffer.strip()   # flush remainder
```

```python
def clean_text(text: str) -> str:
    """Strips non-ASCII, removes special chars, normalizes whitespace."""
    text = text.encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^a-zA-Z0-9\s,.?!]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
```

---

## 9. Voice Pipeline — ASR

### `ASRStream` (`src/asr/audio_stream.py`)

```python
class ASRStream:
    sample_rate: int = 16000
    chunk_duration_ms: int = 500
    max_silence_chunk: int = 8          # ~4 seconds of silence before transcribing

    def listen() -> str:                # blocking — returns single transcription
    def stream() -> Generator[str]:     # yields transcriptions as they complete
```

**Internal pipeline:**
```
sounddevice.InputStream (16kHz, mono, 500ms chunks)
    │
    ▼ _audio_callback()
    └── audio_queue.put(chunk)
            │
            ▼ listen() / stream()
            ├── VoiceActivityDetector.contains_speech(chunk)
            ├── If speech → append to speech_buffer, reset silence counter
            ├── If silence → increment silence counter
            └── If silence_count >= max_silence_chunk:
                    concat buffer → asr.transcribe(audio)
                    yield result
                    clear buffer
```

### ASR Providers

**`WhisperASR`** (`src/asr/whisper_provider.py`): faster-whisper backend, beam_size=5

**`MLXWhisperASR`** (`src/asr/mlx_provider.py`): Apple Silicon optimized (auto-selected on `Darwin arm`)

**Factory auto-selects** by platform:
```python
if platform.system() == 'Darwin' and platform.processor() == 'arm':
    return MLXWhisperASR(model_path="mlx-community/whisper-base-mlx")
else:
    return WhisperASR(model_size_or_path="base", device="auto")
```

### VAD (`src/asr/vad.py`)

```python
class VoiceActivityDetector:
    threshold: float = 0.5
    model: Silero VAD (loaded from torch hub)

    def contains_speech(audio: np.ndarray, sample_rate: int) -> bool:
        # Converts to torch tensor
        # Runs get_speech_timestamps(audio_tensor, model, threshold, sampling_rate)
        # Returns True if any timestamps found
```

---

## 10. LLM Factory & Registry

### Model Registry (`src/llms/registry.py`)

```python
MODEL_REGISTRY = {
    # Google
    "GEMINI_FLASH":      "google:gemini-2.0-flash",
    "GEMINI_FLASH_LITE": "google:gemini-2.0-flash-lite",
    "GEMMA_4_31B":       "google:gemma-4-31b-it",

    # Groq
    "GROQ_LLAMA_70B":    "groq:llama-3.3-70b-versatile",

    # OpenRouter
    "OR_NEMOTRON":       "openrouter:nvidia/nemotron-3-super-120b-a12b",
    "OR_GEMMA4":         "openrouter:google/gemma-4-31b-it:free",
}
```

`resolve_model(name)` returns `(provider, model_name)`. Supports both aliases and raw `"provider:model"` passthrough.

### LLM Factory (`src/llms/factory.py`)

```python
llm_factory.create(
    model_name="GEMINI_FLASH",    # alias or "provider:model"
    temperature=0,
    max_tokens=None,
    max_retries=2,
    callbacks=None,
    **extra
) -> BaseChatModel
```

Provider builder map:
- `google` → `ChatGoogleGenerativeAI`
- `groq` → `ChatGroq`
- `openrouter` → `ChatOpenRouter`

**`CostTrackerCallback` is automatically attached to every model.**

### Cost Tracker (`src/llms/cost_tracker.py`)

Tracks input/output tokens per model across the session. Printed after every `format_response` call.

```python
cost_tracker.get_summary()
# → formatted table: model | calls | input_tokens | output_tokens | total
```

Token extraction supports multiple provider field name conventions:
`usage_metadata` → `input_tokens` / `prompt_tokens` / `prompt_token_count` / `input_token_count`

---

## 11. Scheduler System

### Task Model (`src/scheduler/models.py`)

```python
@dataclass
class TaskRecord:
    task_id: str              # UUID (auto-generated)
    task_description: str
    schedule_type: str        # "cron" | "interval" | "once"
    schedule_params: dict     # {"hour": 9, "minute": 0} / {"minutes": 30} / {"run_date": "ISO"}
    is_enabled: bool = True
    task_plan: str            # natural language plan for the agent
    last_task_result: str
    last_run_at: Optional[str]   # ISO-8601
    next_run_at: Optional[str]   # ISO-8601
    created_at: str
    updated_at: str
```

### Task Store (`src/scheduler/task_store.py`)

- **Backend:** SQLite at `data/scheduler.sqlite`
- **Thread-safe:** `threading.RLock`
- **Operations:** `create`, `get`, `list_all`, `update` (partial), `delete`, `set_enabled`, `update_last_result`, `find_by_id_prefix`

### Scheduler Manager (`src/scheduler/scheduler_manager.py`)

```python
class SchedulerManager:   # Singleton
    store: TaskStore
    scheduler: BackgroundScheduler   # APScheduler

    # On init: load all enabled tasks from store, schedule each
    # _get_trigger(task) → CronTrigger | IntervalTrigger | DateTrigger
    # _execute_task(task_id): invokes main_graph with unique thread_id
    #   thread_id format: f"sched_{task_id}_{uuid.hex[:8]}"
    # Saves result + timestamps back to store
```

**Trigger types:**
- `"cron"` → `CronTrigger(**schedule_params)` — e.g. `{hour: 9, minute: 0}`
- `"interval"` → `IntervalTrigger(**schedule_params)` — e.g. `{minutes: 30}`
- `"once"` → `DateTrigger(run_date=schedule_params["run_date"])`

**Execution:** APScheduler fires `_execute_task(task_id)` on a background thread. The task invokes `main_graph.invoke(state)` and stores the response.

---

## 12. Threading Model

The runtime uses four concurrent execution contexts:

```
┌──────────────────────────────────────────────────────────────┐
│ Thread 1: Main Thread                                         │
│   - input() loop (blocks waiting for user)                   │
│   - ChatAgent.stream() — yields LLM tokens                   │
│   - process_llm_stream() — accumulates tokens → sentence Q   │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ Thread 2: TTS Daemon Thread (daemon=True)                     │
│   - process_tts_stream() — consumes llm_chunk_queue          │
│   - KokoroTTS.synthesize() — runs Kokoro inference           │
│   - Populates audio_queue with frames + sentinels            │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ Thread 3: Audio Callback Thread (managed by sounddevice)      │
│   - Fires continuously at audio block rate (~21ms per frame)  │
│   - Dequeues from audio_queue                                 │
│   - Calls _on_start sentinels (spawns word-printer threads)   │
│   - Writes audio frames to speaker output                     │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ Thread 4+: Word-Printer Daemon Threads (one per sentence)     │
│   - Spawned by _on_start when audio starts                   │
│   - Sleep until each word's estimated onset time             │
│   - Call word_callback(word) → print to terminal             │
└──────────────────────────────────────────────────────────────┘

Inter-thread queues:
  llm_chunk_queue  — str sentences, Thread 1 → Thread 2
  audio_queue      — numpy arrays + tuples, Thread 2 → Thread 3/4
```

**Important:** `process_tts_stream` is started **before** the REPL loop and runs for the entire session lifetime. It blocks on `llm_chunk_queue.get()` between responses. Sending `None` to the queue is the shutdown signal.

---

## 13. Configuration & Settings

All settings live in `src/config/settings.py`. Change them there — do not hardcode elsewhere.

```python
# Logging destination
LOG_MODE: str = "file"         # "terminal" | "file" | "both"
LOG_FILE_PATH: str             # auto: logs/YYYY-MM-DD.log

# Starting working directory for file tools
DEFAULT_CWD: str = os.getcwd()

# Active TTS engine
TTS_PROVIDER: str = "kokoro"   # "kokoro" | "supertonic" | "kitten"

TTS_CONFIG = {
    "kokoro": {
        "voice_name": "af_heart",
        "sample_rate": 24000,
        "speed": 1.3,
    },
    "supertonic": {
        "voice_name": "F1",
        "sample_rate": 24000,
        "speed": 1.3,
        "total_steps": 30,
    },
    "kitten": {
        "model_name": "KittenML/kitten-tts-mini-0.8",
        "voice_name": "Jasper",
        "sample_rate": 24000,
        "speed": 1.3,
    }
}
```

### Logger (`src/config/logger.py`)

```python
get_logger(name: str) -> logging.Logger
# Returns child of root "beta1" logger
# Example: get_logger("agents.chat_agent") → "beta1.agents.chat_agent"

# Format: "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
# Date:   "YYYY-MM-DD HH:MM:SS"
```

---

## 14. Prompts

Prompts are markdown files loaded via `load_prompt(name)` from `src/prompts/`. They are LRU-cached (maxsize=32).

| File | Purpose |
|---|---|
| `chat_agent.md` | Persona, tone, delegation rules, TTS-optimized speech style |
| `planning_agent.md` | How to read the codebase and produce a structured plan |
| `supervisor_agent.md` | Task routing logic, validation criteria |
| `coding_agent.md` | Code writing, testing, debugging instructions |
| `system_agent.md` | Shell command safety and execution guidelines |

**Chat agent prompt** (`chat_agent.md`) defines Beta-1's full persona:
- Voice: laid-back, direct, witty — like a technically brilliant friend
- Hard bans: no "Certainly!", no AI-distancing phrases, no sycophantic openers
- TTS-aware: short sentences, plain English, minimal markdown in speech
- Delegation rules: clarify vague requests first, auto-delegate once clear

---

## 15. CLI & TUI

### Active: REPL Terminal (`main.py`)

```
[/path/to/cwd] You ▸  <user input>
Beta-1 ▸ <word> <word> <word> ...    (words printed as audio plays)
```

Color scheme (ANSI):
- Prompt path: `GRAY`
- "You ▸": `GREEN + BOLD`
- "Beta-1 ▸": `BLUE + BOLD`
- Response words: `BLUE`

Commands inside the REPL:
- `quit` / `exit` / `q` → exit
- `/voice` → activate ASR voice input (WIP)

### Inactive: Textual TUI (`src/cli/tui.py`)

A full Textual-based GUI is implemented but commented out in `main.py`. To activate, swap `Pipeline().run()` for `TUI().run()`.

**Tabs:** Chat, Settings, Schedules, Tasks, Sessions, Contexts

**Keyboard bindings:** Ctrl+C quit, Ctrl+L live audio, Ctrl+K clear, Ctrl+D theme toggle

**Widgets:**
- `ChatMessage` — styled message bubbles (50% width, user/bot alignment)
- `AudioBars` — real-time audio level visualizer (sounddevice or simulated)

---

## 16. Quick Start

```bash
# 1. Clone and enter directory
cd Beta-1

# 2. Copy env template and fill in API keys
cp .env.example .env

# 3. Install dependencies (requires uv)
uv sync

# 4. Run
python main.py
```

---

## 17. Environment Variables

Required in `.env`:

```
GOOGLE_API_KEY=<your-key>          # For Gemini and Gemma models
GEMINI_API_KEY=<your-key>          # Same key, some providers check this name
OPENROUTER_API_KEY=<your-key>      # For OpenRouter models (OR_NEMOTRON, OR_GEMMA4)
GROQ_API_KEY=<your-key>            # For Groq models (GROQ_LLAMA_70B)
```

Loaded at startup via `python-dotenv` (`load_dotenv()` in `main.py`).

---

## 18. Design Constraints & Known Limitations

### Active Limitations

| Area | Constraint |
|---|---|
| **Supervisor routing** | Only `coding_agent` is wired in. `system_agent`, `file_agent`, `search_agent` are built but not reachable from the supervisor loop yet |
| **Voice input** | ASR + VAD are implemented; `/voice` command stub exists in REPL but does not feed into the chat agent yet |
| **TUI** | Fully implemented but inactive — not wired to `ChatAgent` or `Pipeline` |
| **Word sync accuracy** | Word timing is approximated by distributing words evenly across each Kokoro segment duration. Not phoneme-accurate |
| **TTS word sync on non-Kokoro** | `SupertonicTTS` and `KittenProvider` do not support `word_callback` — no word-level sync |
| **TTS latency** | Kokoro synthesizes eagerly (all segments before queuing) to compute word offsets — adds ~100–400ms vs lazy streaming |
| **clean_text strips non-ASCII** | Non-Latin characters (Hindi, emoji, etc.) are stripped before TTS synthesis. `clean_text_with_hindi` exists but is not wired in |
| **Token cost display** | Shown after complex workflow only (format_response path). Simple Chat Agent responses do not log token cost |
| **Scheduler execution** | Scheduled tasks invoke `main_graph` directly (planning → supervisor → format), not `ChatAgent` — so they always go through the full complex workflow |

### Architecture Decisions

- **`InMemorySaver` in Chat Agent** — conversation history persists within a session (single `thread_id`) but is lost on restart. No persistent memory layer yet.
- **Sentence-level TTS chunking** — `accumulate_sentences` creates natural pause points. Audio latency scales linearly with sentence length; very long sentences block the first audio output.
- **`GEMMA_4_31B` as default everywhere** — chosen for quality. Can be swapped to `GEMINI_FLASH` in any agent's `__init__` for faster/cheaper responses.
- **`safe_bash` vs `bash_exec`** — Chat Agent gets `safe_bash` (allowlist-restricted); Code/System agents get full `bash_exec`. Never expose `bash_exec` to the Chat Agent.
- **Singleton `SchedulerManager`** — ensures only one APScheduler instance and one SQLite connection pool across the process lifetime.
