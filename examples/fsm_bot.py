"""
FSM bot — demonstrates Finite State Machine for multi-step dialogs.

Usage:
    python examples/fsm_bot.py
"""

import asyncio

from vkworkspace import Bot, Dispatcher, F, Router
from vkworkspace.filters import Command
from vkworkspace.filters.state import StateFilter
from vkworkspace.fsm import FSMContext, State, StatesGroup
from vkworkspace.fsm.storage.memory import MemoryStorage
from vkworkspace.types import Message
from vkworkspace.utils.keyboard import InlineKeyboardBuilder

router = Router()


# Define states
class RegistrationForm(StatesGroup):
    waiting_name = State()
    waiting_age = State()
    confirm = State()


@router.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext) -> None:
    await state.set_state(RegistrationForm.waiting_name)
    await message.answer("Let's register! What is your name?")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer("Nothing to cancel.")
        return
    await state.clear()
    await message.answer("Registration cancelled.")


@router.message(StateFilter(RegistrationForm.waiting_name), F.text)
async def process_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text)
    await state.set_state(RegistrationForm.waiting_age)
    await message.answer(f"Nice to meet you, {message.text}! How old are you?")


@router.message(StateFilter(RegistrationForm.waiting_age), F.text)
async def process_age(message: Message, state: FSMContext) -> None:
    assert message.text is not None  # guaranteed by F.text filter
    if not message.text.isdigit():
        await message.answer("Please enter a valid number.")
        return

    await state.update_data(age=int(message.text))
    data = await state.get_data()

    builder = InlineKeyboardBuilder()
    builder.button(text="Confirm", callback_data="reg_confirm")
    builder.button(text="Cancel", callback_data="reg_cancel")
    builder.adjust(2)

    await state.set_state(RegistrationForm.confirm)
    await message.answer(
        f"Please confirm your data:\n"
        f"Name: {data['name']}\n"
        f"Age: {data['age']}",
        inline_keyboard_markup=builder.as_markup(),
    )


@router.callback_query(F.callback_data == "reg_confirm")
async def confirm_registration(query, state: FSMContext) -> None:
    data = await state.get_data()
    await query.answer(f"Registered! Welcome, {data['name']}!")
    await state.clear()


@router.callback_query(F.callback_data == "reg_cancel")
async def cancel_registration(query, state: FSMContext) -> None:
    await state.clear()
    await query.answer("Registration cancelled.")


async def main() -> None:
    bot = Bot(
        token="YOUR_BOT_TOKEN",
        api_url="https://myteam.mail.ru/bot/v1",
    )
    dp = Dispatcher(
        storage=MemoryStorage(),
        session_timeout=300,  # Auto-clear FSM after 5 min of inactivity
    )
    dp.include_router(router)

    print("FSM bot is running (session_timeout=300s)...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
