# Beta-1 — AI Personal Assistant

A multi-agent personal assistant built with **LangGraph** and **LangChain**. Beta-1 classifies user queries, delegates complex tasks to specialized agents, and coordinates multi-step workflows automatically.

## Architecture

```
User → Chat Agent (classify) → simple → direct response → END
                              → complex → Supervisor → Sub-Agents → Validator → format → END
```

### Flow

1. **Chat Agent** receives every user query and classifies it as **simple** or **complex**.
2. **Simple queries** (greetings, factual Q&A) get a direct response immediately.
3. **Complex queries** are handed to the **Supervisor Agent**, which:
   - Decomposes the task into a plan of discrete sub-tasks
   - Routes each sub-task to the appropriate specialist agent
   - Validates each result (approve / needs revision / failed)
   - Loops until all tasks are done or max iterations reached
4. The final response is formatted and returned to the user.

### Agents

| Agent | Role | Tools |
|-------|------|-------|
| **Chat Agent** | Entry-point classifier — simple vs complex | None |
| **Supervisor Agent** | Task decomposition, routing, and validation | None (orchestrator) |
| **File Agent** | File system operations | read, write, copy, move, delete, search, list, create dir |
| **Code Agent** | Code writing, debugging, linting | write_code, debug_code, lint_code |
| **System Agent** | Shell commands, git, packages, env vars | bash_exec, git_ops, install_pkg, env_vars, process_mgmt |
| **Search Agent** | Web search, URL fetching, docs | web_search, fetch_url, read_docs, scrape_page |

### LLM Module

All agents get their LLM through a centralized factory in `src/llms/`:

- **Registry** (`registry.py`) — maps aliases like `GEMINI_FLASH` to `google:gemini-2.0-flash`
- **Factory** (`factory.py`) — `LLMFactory` class with `llm_factory.create("GEMINI_FLASH", temperature=0)` returning a configured LangChain model
- **Cost Tracker** (`cost_tracker.py`) — automatically tracks input/output token usage per model via LangChain callbacks

---

## Project Structure

```
Beta-1/
├── main.py                          # CLI entry point — interactive REPL
├── pyproject.toml                   # Project config & dependencies
│
├── src/
│   ├── workflow.py                  # Main orchestrator graph (LangGraph)
│   │
│   ├── llms/                        # Centralized LLM management
│   │   ├── __init__.py              # Public API: get_llm, cost_tracker
│   │   ├── registry.py              # Model alias → provider:model mapping
│   │   ├── factory.py               # LLM factory — single point of creation
│   │   └── cost_tracker.py          # Token usage tracking (input/output per model)
│   │
│   ├── agents/                      # All agent implementations
│   │   ├── chatagent/
│   │   │   ├── chat_agent.py        # Classify node + format response node
│   │   │   └── system_prompt.py     # Classification prompt
│   │   │
│   │   ├── supervisoragent/
│   │   │   ├── supervisor_agent.py  # Plan → route → validate loop
│   │   │   └── system_prompt.py     # Planning & validation prompt
│   │   │
│   │   ├── fileagent/
│   │   │   ├── file_agent.py        # ReAct loop with file tools
│   │   │   ├── agent_tools.py       # Tool bindings
│   │   │   └── system_prompt.py
│   │   │
│   │   ├── codeagent/
│   │   │   ├── code_agent.py        # ReAct loop with verify step
│   │   │   ├── agent_tools.py
│   │   │   └── system_prompt.py
│   │   │
│   │   ├── systemagent/
│   │   │   ├── system_agent.py      # ReAct loop with safety check
│   │   │   ├── agent_tools.py
│   │   │   └── system_prompt.py
│   │   │
│   │   └── searchagent/
│   │       ├── search_agent.py      # ReAct loop (no verify — non-destructive)
│   │       ├── agent_tools.py
│   │       └── system_prompt.py
│   │
│   ├── states/                      # LangGraph state schemas
│   │   ├── main_state.py            # MainState — top-level workflow state
│   │   ├── supervisor_state.py      # SupervisorState + TaskItem
│   │   └── agent_state.py           # SubAgentState — shared by all sub-agents
│   │
│   ├── tools/                       # LangChain tool implementations
│   │   ├── file_tools/              # read, write, copy, move, delete, search, list, mkdir
│   │   ├── code_tools/              # write_code, debug_code, lint_code
│   │   ├── system_tools/            # bash_exec, git_ops, install_pkg, env_vars, process_mgmt
│   │   └── search_tools/            # web_search, fetch_url, read_docs, scrape_page
│   │
│   └── config/                      # Configuration
│       ├── settings.py              # Log mode, paths, defaults
│       ├── logger.py                # Logging setup
│       └── agent_registry.py        # Maps agent names → compiled graphs
│
└── logs/                            # Runtime log files (by date)
```

---

## Quick Start

```bash
# 1. Set up environment
cp .env.example .env   # Add your GOOGLE_API_KEY

# 2. Install dependencies
uv sync

# 3. Run
python main.py
```

## Dependencies

- **LangGraph** — agent orchestration and graph-based workflows
- **LangChain** — LLM abstractions, tool framework, callbacks
- **langchain-google-genai** — Google Gemini models
- Python 3.12+
