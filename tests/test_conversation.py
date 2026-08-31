from mewcode.conversation import Conversation
from mewcode.llm import Message


def test_messages_preserve_turn_order_and_return_a_copy() -> None:
    conversation = Conversation()
    conversation.add_user("hello")
    conversation.add_assistant("hi")
    conversation.add_user("follow up")

    messages = conversation.messages()

    assert [(message.role, message.content) for message in messages] == [
        ("user", "hello"),
        ("assistant", "hi"),
        ("user", "follow up"),
    ]
    messages.clear()
    assert len(conversation.messages()) == 3


def test_remove_last_supports_rolling_back_a_failed_turn() -> None:
    conversation = Conversation()
    conversation.add_user("failed")

    removed = conversation.remove_last()

    assert removed is not None
    assert removed.content == "failed"
    assert conversation.messages() == []


def test_truncate_rolls_back_a_partial_turn() -> None:
    conversation = Conversation()
    conversation.add_user("keep")
    checkpoint = len(conversation)
    conversation.add_assistant("partial")
    conversation.add_user("discard")

    conversation.truncate(checkpoint)

    assert conversation.messages() == [Message("user", "keep")]
