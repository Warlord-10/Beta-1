"""Beta-1 — Personal Assistant entry point.

Run:
    python main.py
"""

from dotenv import load_dotenv
load_dotenv()

from langchain_core.messages import HumanMessage

from src.config.settings import DEFAULT_CWD
from src.config.logger import get_logger
from src.workflow import main_graph

logger = get_logger("cli")


def main():
    """Interactive loop — chat with Beta-1 in the terminal."""
    print("🤖 Beta-1 Personal Assistant")
    print("=" * 40)
    print("Type your request (or 'quit' to exit)\n")

    # Persistent state across turns
    cwd = DEFAULT_CWD

    while True:
        try:
            user_input = input(f"[{cwd}] You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n👋 Goodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("👋 Goodbye!")
            break

        logger.info("User input: %s", user_input)

        result = main_graph.invoke(
            {
                "messages": [HumanMessage(content=user_input)],
                "cwd": cwd,
            }
        )

        # Update cwd from agent's response (it may have changed)
        cwd = result.get("cwd", cwd)

        # The last message is the AI's final response
        ai_response = result["messages"][-1].content
        logger.info("AI response: %s", ai_response[:200])
        print(f"\nBeta-1: {ai_response}\n")


if __name__ == "__main__":
    main()
