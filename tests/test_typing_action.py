"""Tests for @typing_action decorator and ChatActionSender."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from vkworkspace.enums.chat_action import ChatAction
from vkworkspace.utils.actions import ChatActionSender, typing_action


def _make_event(chat_id: str = "chat-1") -> SimpleNamespace:
    bot = SimpleNamespace(send_actions=AsyncMock())
    chat = SimpleNamespace(chat_id=chat_id)
    return SimpleNamespace(chat=chat, bot=bot)


class TestTypingAction:
    @pytest.mark.asyncio
    async def test_sends_typing_during_handler(self):
        event = _make_event()

        @typing_action
        async def handler(ev: SimpleNamespace) -> str:
            await asyncio.sleep(0.05)
            return "done"

        result = await handler(event)
        assert result == "done"
        event.bot.send_actions.assert_called_with("chat-1", "typing")

    @pytest.mark.asyncio
    async def test_custom_action(self):
        event = _make_event()

        @typing_action(action=ChatAction.LOOKING)
        async def handler(ev: SimpleNamespace) -> str:
            await asyncio.sleep(0.05)
            return "ok"

        await handler(event)
        event.bot.send_actions.assert_called_with("chat-1", "looking")

    @pytest.mark.asyncio
    async def test_stops_after_handler_completes(self):
        event = _make_event()

        @typing_action(interval=0.01)
        async def handler(ev: SimpleNamespace) -> str:
            await asyncio.sleep(0.05)
            return "ok"

        await handler(event)
        # Give time for cancelled task to settle
        await asyncio.sleep(0.02)
        call_count = event.bot.send_actions.call_count
        # Should not keep growing after handler returns
        await asyncio.sleep(0.05)
        assert event.bot.send_actions.call_count == call_count

    @pytest.mark.asyncio
    async def test_stops_on_exception(self):
        event = _make_event()

        @typing_action(interval=0.01)
        async def handler(ev: SimpleNamespace) -> None:
            await asyncio.sleep(0.03)
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await handler(event)

        # Task should be cancelled even on error
        await asyncio.sleep(0.05)
        final_count = event.bot.send_actions.call_count
        await asyncio.sleep(0.05)
        assert event.bot.send_actions.call_count == final_count

    @pytest.mark.asyncio
    async def test_no_chat_skips_action(self):
        event = SimpleNamespace(bot=SimpleNamespace(send_actions=AsyncMock()))

        @typing_action
        async def handler(ev: SimpleNamespace) -> str:
            return "no chat"

        result = await handler(event)
        assert result == "no chat"
        event.bot.send_actions.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_bot_skips_action(self):
        event = SimpleNamespace(chat=SimpleNamespace(chat_id="c1"))

        @typing_action
        async def handler(ev: SimpleNamespace) -> str:
            return "no bot"

        result = await handler(event)
        assert result == "no bot"

    @pytest.mark.asyncio
    async def test_passes_kwargs(self):
        event = _make_event()

        @typing_action
        async def handler(ev: SimpleNamespace, state: str = "") -> str:
            return state

        result = await handler(event, state="active")
        assert result == "active"


class TestChatActionSender:
    @pytest.mark.asyncio
    async def test_sends_typing_in_context(self):
        bot = SimpleNamespace(send_actions=AsyncMock())
        async with ChatActionSender(bot=bot, chat_id="c1"):  # type: ignore[arg-type]
            await asyncio.sleep(0.05)
        bot.send_actions.assert_called_with("c1", "typing")

    @pytest.mark.asyncio
    async def test_custom_action(self):
        bot = SimpleNamespace(send_actions=AsyncMock())
        async with ChatActionSender(
            bot=bot,
            chat_id="c1",
            action=ChatAction.LOOKING,  # type: ignore[arg-type]
        ):
            await asyncio.sleep(0.05)
        bot.send_actions.assert_called_with("c1", "looking")

    @pytest.mark.asyncio
    async def test_stops_after_exit(self):
        bot = SimpleNamespace(send_actions=AsyncMock())
        async with ChatActionSender(bot=bot, chat_id="c1", interval=0.01):  # type: ignore[arg-type]
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.02)
        count = bot.send_actions.call_count
        await asyncio.sleep(0.05)
        assert bot.send_actions.call_count == count

    @pytest.mark.asyncio
    async def test_stops_on_exception(self):
        bot = SimpleNamespace(send_actions=AsyncMock())
        with pytest.raises(ValueError, match="boom"):
            async with ChatActionSender(bot=bot, chat_id="c1", interval=0.01):  # type: ignore[arg-type]
                await asyncio.sleep(0.03)
                raise ValueError("boom")
        await asyncio.sleep(0.05)
        count = bot.send_actions.call_count
        await asyncio.sleep(0.05)
        assert bot.send_actions.call_count == count

    @pytest.mark.asyncio
    async def test_typing_classmethod(self):
        bot = SimpleNamespace(send_actions=AsyncMock())
        async with ChatActionSender.typing(bot=bot, chat_id="c1"):  # type: ignore[arg-type]
            await asyncio.sleep(0.05)
        bot.send_actions.assert_called_with("c1", "typing")

    @pytest.mark.asyncio
    async def test_looking_classmethod(self):
        bot = SimpleNamespace(send_actions=AsyncMock())
        async with ChatActionSender.looking(bot=bot, chat_id="c1"):  # type: ignore[arg-type]
            await asyncio.sleep(0.05)
        bot.send_actions.assert_called_with("c1", "looking")

    @pytest.mark.asyncio
    async def test_reentrant(self):
        """Can be used multiple times."""
        bot = SimpleNamespace(send_actions=AsyncMock())
        sender = ChatActionSender(bot=bot, chat_id="c1")  # type: ignore[arg-type]
        async with sender:
            await asyncio.sleep(0.02)
        bot.send_actions.reset_mock()
        async with sender:
            await asyncio.sleep(0.02)
        bot.send_actions.assert_called()


class TestMessageTyping:
    @pytest.mark.asyncio
    async def test_message_typing(self):
        from vkworkspace.types.message import Message

        bot = SimpleNamespace(send_actions=AsyncMock())
        msg = Message(msgId="1", chat={"chatId": "chat-1", "type": "group"})  # type: ignore[arg-type]
        msg.set_bot(bot)  # type: ignore[arg-type]

        async with msg.typing():
            await asyncio.sleep(0.05)
        bot.send_actions.assert_called_with("chat-1", "typing")

    @pytest.mark.asyncio
    async def test_message_typing_looking(self):
        from vkworkspace.types.message import Message

        bot = SimpleNamespace(send_actions=AsyncMock())
        msg = Message(msgId="1", chat={"chatId": "c1", "type": "private"})  # type: ignore[arg-type]
        msg.set_bot(bot)  # type: ignore[arg-type]

        async with msg.typing(action=ChatAction.LOOKING):
            await asyncio.sleep(0.05)
        bot.send_actions.assert_called_with("c1", "looking")

    @pytest.mark.asyncio
    async def test_answer_chat_action_default(self):
        from vkworkspace.types.message import Message

        bot = SimpleNamespace(send_actions=AsyncMock())
        msg = Message(msgId="1", chat={"chatId": "chat-1", "type": "group"})  # type: ignore[arg-type]
        msg.set_bot(bot)  # type: ignore[arg-type]

        await msg.answer_chat_action()
        bot.send_actions.assert_called_once_with("chat-1", "typing")

    @pytest.mark.asyncio
    async def test_answer_chat_action_looking(self):
        from vkworkspace.types.message import Message

        bot = SimpleNamespace(send_actions=AsyncMock())
        msg = Message(msgId="1", chat={"chatId": "c1", "type": "private"})  # type: ignore[arg-type]
        msg.set_bot(bot)  # type: ignore[arg-type]

        await msg.answer_chat_action(action=ChatAction.LOOKING)
        bot.send_actions.assert_called_once_with("c1", "looking")
