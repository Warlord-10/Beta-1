"""Beta-1 — Personal Assistant entry point.

Run:
    python main.py
"""

from langchain_core.messages import HumanMessage

from src.main import main_graph


def main():
    """Interactive loop — chat with Beta-1 in the terminal."""
    print("🤖 Beta-1 Personal Assistant")
    print("=" * 40)
    print("Type your request (or 'quit' to exit)\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n👋 Goodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("👋 Goodbye!")
            break

        result = main_graph.invoke(
            {"messages": [HumanMessage(content=user_input)]}
        )

        # The last message is the AI's final response
        ai_response = result["messages"][-1].content
        print(f"\nBeta-1: {ai_response}\n")


if __name__ == "__main__":
    main()
