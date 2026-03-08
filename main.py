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
                "user_query": user_input,
                "complexity": "",
                "plan": [],
                "results": [],
                "final_response": "",
                "cwd": cwd,
            }
        )

        # Update cwd from agent's response (it may have changed)
        cwd = result.get("cwd", cwd)

        # Get the final response
        final_response = result.get("final_response", "")
        if not final_response:
            # Fallback: last message content
            final_response = result["messages"][-1].content if result.get("messages") else "No response."

        logger.info("AI response: %s", final_response[:200])
        print(f"\nBeta-1: {final_response}\n")


if __name__ == "__main__":
    main()
