"""Tool: lint_code — Run basic linting checks on code content."""

from langchain_core.tools import tool


@tool
def lint_code(code: str, language: str = "python") -> str:
    """Perform basic lint / syntax checks on a code snippet.

    Args:
        code: The code content to lint.
        language: Programming language of the code.

    Returns:
        Lint results or error description.
    """
    if language.lower() == "python":
        try:
            compile(code, "<lint_check>", "exec")
            return "✅ Python syntax check passed — no syntax errors found."
        except SyntaxError as e:
            return (
                f"❌ Python syntax error on line {e.lineno}:\n"
                f"  {e.text.strip() if e.text else '(unknown)'}\n"
                f"  Error: {e.msg}"
            )
    else:
        return f"⚠️ Lint not yet implemented for language: {language}"
