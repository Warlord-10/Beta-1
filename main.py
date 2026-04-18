"""Beta-1 — Personal Assistant entry point.

Run:
    python main.py
"""

from dotenv import load_dotenv

load_dotenv()

import uuid
from pprint import pprint

from langchain_core.messages import HumanMessage

from src.agents.chatagent.chat_agent import chat
from src.config.logger import get_logger
from src.config.settings import settings
from src.scheduler import scheduler_manager
from src.workflow import main_graph

logger = get_logger("cli")

class Colors:
    RESET      = "\033[0m"
    BOLD       = "\033[1m"
    DIM        = "\033[2m"

    GREEN      = "\033[38;5;114m"     # soft green for user
    BLUE       = "\033[38;5;111m"     # soft blue for bot
    CYAN       = "\033[38;5;80m"      # accent color
    GRAY       = "\033[38;5;245m"     # muted gray
    WHITE      = "\033[38;5;255m"     # bright white
    YELLOW     = "\033[38;5;222m"     # warm yellow


def print_banner():
    """Print a styled ASCII art banner on startup."""
    banner = f"""
{Colors.CYAN}{Colors.BOLD}
╔════════════════════════════════════════════════╗
║                                                ║
║   ██████  ███████ ████████  █████     ████     ║
║   ██   ██ ██         ██    ██   ██      ██     ║
║   ██████  █████      ██    ███████  ██  ██     ║
║   ██   ██ ██         ██    ██   ██      ██     ║
║   ██████  ███████    ██    ██   ██    ██████   ║
║                                                ║
╚════════════════════════════════════════════════╝
{Colors.RESET}
{Colors.DIM}Personal AI Assistant • by Deepanshu Joshi{Colors.RESET}
{Colors.GRAY}Type your request below  •  'quit' to exit{Colors.RESET}
"""
    print(banner)


def main():
    """Interactive loop — chat with Beta-1 in the terminal."""
    print_banner()

    # Persistent state across turns
    cwd = settings.DEFAULT_CWD

    # Generate a unique thread ID for this CLI session
    # This enables InMemorySaver to accumulate messages across turns
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    logger.info("Session started — thread_id: %s", thread_id)
    
    # Scheduler was started recursively when importing scheduler_manager
    logger.info("Scheduler integrated into main loop.")

    while True:
        try:
            prompt = f"{Colors.GRAY}[{cwd}]{Colors.RESET} {Colors.GREEN}{Colors.BOLD}You ▸{Colors.RESET} "
            user_input = input(prompt).strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{Colors.YELLOW}👋 Goodbye!{Colors.RESET}")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print(f"{Colors.YELLOW}👋 Goodbye!{Colors.RESET}")
            break
        if user_input.lower() == "/settings":
            print(f"{Colors.GREEN}{Colors.BOLD}Settings:{Colors.RESET}")
            pprint(settings)
            continue

        logger.info("User input: %s", user_input)

        result = main_graph.invoke(
            {
                "messages": [HumanMessage(content=user_input)],
                "user_query": user_input,
                "complexity": "",
                "implementation_plan": "",
                "action_checklist": [],
                "current_task": {},
                "completed_tasks": [],
                "final_response": "",
                "cwd": cwd,
                "iteration": 0,
                "next_agent": "",
            },
            config=config,
        )

        # Update cwd from agent's response (it may have changed)
        cwd = result.get("cwd", cwd)

        # Get the final response
        final_response = result.get("final_response", "")
        if not final_response:
            # Fallback: last message content
            final_response = result["messages"][-1].content if result.get("messages") else "No response."

        logger.info("AI response: %s", final_response[:200])
        print(f"\n{Colors.BLUE}{Colors.BOLD}Beta-1 ▸{Colors.RESET} {Colors.BLUE}{final_response}{Colors.RESET}\n")

        # Play TTS if available
        if tts_engine:
            # We don't block by default so user can start typing the next prompt
            # but sounddevice.play runs as async automatically unless we call sd.wait()
            try:
                tts_engine.play(final_response, block=False)
            except Exception as e:
                logger.error("TTS playback failed: %s", e)

    # Shutdown gracefully
    scheduler_manager.shutdown()


def speak(text):
    if tts_engine:
        tts_engine.play(text, block=False)

def stream_output(gen):
    for chunk in gen:
        print(chunk, end="", flush=True)
        speak(chunk)

def main_v2():
    from src.agents.chatagent.chat_agent import ChatAgent
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    chat_agent = ChatAgent(config=config)

    while True:
        s = input("User: ")
        if s.lower() in ("quit", "exit", "q"):
            break
        
        res = chat_agent.stream(s)
        stream_output(res)


if __name__ == "__main__":
    # Lazy initialization of TTS if user installed the dependencies
    try:
        from src.voice import get_tts_engine
        
        provider_name = settings.TTS_PROVIDER
        provider_config = settings.TTS_CONFIG.get(provider_name, {})
        
        print(f"{Colors.DIM}Loading {provider_name.capitalize()} TTS framework...{Colors.RESET}")
        tts_engine = get_tts_engine(provider_name, provider_config)
    except Exception as e:
        logger.warning("TTS Engine failed to initialize: %s", e)
        tts_engine = None
        
    main_v2()


