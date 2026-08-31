"""In-memory conversation history."""

from .llm import Message, ToolCall, ToolResult


class Conversation:
    def __init__(self) -> None:
        self._messages: list[Message] = []

    def add_user(self, text: str) -> None:
        self._messages.append(Message(role="user", content=text))

    def add_assistant(self, text: str) -> None:
        self._messages.append(Message(role="assistant", content=text))

    def add_assistant_with_tool_calls(self, text: str, calls: list[ToolCall]) -> None:
        self._messages.append(Message(role="assistant", content=text, tool_calls=list(calls)))

    def add_tool_results(self, results: list[ToolResult]) -> None:
        self._messages.append(Message(role="tool", tool_results=list(results)))

    def messages(self) -> list[Message]:
        return list(self._messages)

    def remove_last(self) -> Message | None:
        """Remove the most recent message when a turn fails before completion."""
        return self._messages.pop() if self._messages else None

    def truncate(self, size: int) -> None:
        """Roll the conversation back to a previously recorded size."""
        if size < 0 or size > len(self._messages):
            raise ValueError("invalid conversation size")
        del self._messages[size:]

    def __len__(self) -> int:
        return len(self._messages)
