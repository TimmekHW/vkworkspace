# vkworkspace — Complete LLM Reference

> Async Python framework for VK Teams (VK Workspace) bots, inspired by aiogram 3.
> Version 1.6.0 · Python 3.11+ · `pip install vkworkspace`

**Этот файл — полная справка по фреймворку vkworkspace.**
Отдайте его целиком в ChatGPT, Claude или любую другую LLM и попросите написать бота — модель сможет использовать все возможности фреймворка без дополнительной документации.

> Пример промпта: *«Вот справка по фреймворку vkworkspace (llm_full.md). Напиши бота, который принимает номер договора и возвращает список документов из базы данных.»*

---

## Quick Start

```python
import asyncio
from vkworkspace import Bot, Dispatcher, Router, F
from vkworkspace.filters import Command
from vkworkspace.types import Message

router = Router()

@router.message(Command("start"))
async def start(message: Message):
    await message.answer("Hello!")

@router.message(F.text)
async def echo(message: Message):
    assert message.text is not None
    await message.reply(message.text)

async def main():
    bot = Bot(token="TOKEN", api_url="https://myteam.mail.ru/bot/v1")
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)

asyncio.run(main())
```

---

## Bot — API Client

```python
from vkworkspace import Bot

bot = Bot(
    token="TOKEN_FROM_METABOT",
    api_url="https://myteam.mail.ru/bot/v1",  # on-premise URL
    rate_limit=5,          # max 5 req/sec (token-bucket)
    proxy="http://proxy:8535",  # corporate proxy
    parse_mode="HTML",     # default for all messages
    retry_on_5xx=3,        # auto-retry on server errors
    verify_ssl=True,       # False for self-signed certs
)
```

### Bot Methods

| Method | API Endpoint | Description |
|--------|-------------|-------------|
| `await bot.get_me()` | `self/get` | Bot info → `BotInfo` |
| `await bot.send_text(chat_id, text, ...)` | `messages/sendText` | Send message → `APIResponse` |
| `await bot.edit_text(chat_id, msg_id, text, ...)` | `messages/editText` | Edit message |
| `await bot.delete_messages(chat_id, msg_id)` | `messages/deleteMessages` | Delete message |
| `await bot.send_file(chat_id, file=InputFile(...))` | `messages/sendFile` | Upload file/image |
| `await bot.send_voice(chat_id, file=InputFile(...))` | `messages/sendVoice` | Send voice (OGG/Opus) |
| `await bot.answer_callback_query(query_id, text)` | `messages/answerCallbackQuery` | Answer button press |
| `await bot.send_actions(chat_id, "typing")` | `chats/sendActions` | Show typing indicator |
| `await bot.get_chat_info(chat_id)` | `chats/getInfo` | Chat info → `ChatInfo` |
| `await bot.get_chat_admins(chat_id)` | `chats/getAdmins` | Admin list |
| `await bot.pin_message(chat_id, msg_id)` | `chats/pinMessage` | Pin message |
| `await bot.set_chat_title(chat_id, title)` | `chats/setTitle` | Set chat title |
| `await bot.block_user(chat_id, user_id)` | `chats/blockUser` | Block user |
| `await bot.add_chat_members(chat_id, members)` | `chats/members/add` | Add members |
| `await bot.threads_add(chat_id, msg_id)` | `threads/add` | Create thread |

### send_text Parameters

```python
await bot.send_text(
    chat_id="user@company.ru",
    text="Hello!",
    reply_msg_id="123",                    # reply to message
    forward_chat_id="chat@company.ru",     # forward from
    forward_msg_id="456",                  # forward message ID
    inline_keyboard_markup=builder.as_markup(),  # inline keyboard
    parse_mode="HTML",                     # "HTML" / "MarkdownV2" / None
    format_=format_builder.build(),        # offset/length formatting
    parent_topic=parent_msg,               # send in thread
    request_id="unique-id",               # idempotency key
)
```

---

## Dispatcher & Router

```python
from vkworkspace import Dispatcher, Router

# Create routers (order = priority)
admin_router = Router(name="admin")
user_router = Router(name="user")

# Dispatcher = root router + polling loop
dp = Dispatcher(
    storage=MemoryStorage(),      # FSM backend (or RedisStorage)
    session_timeout=300,          # auto-clear FSM after 5 min
    handle_edited_as_message=False,  # route edits to message handlers
)
dp.include_routers(admin_router, user_router)

# Lifecycle hooks
@dp.on_startup
async def setup():
    print("Bot starting...")

@dp.on_shutdown
async def cleanup():
    await db.close()

# Start polling (blocks until SIGINT/SIGTERM)
await dp.start_polling(bot)
```

### Handler Decorators

```python
router = Router()

@router.message()                    # any message
@router.message(Command("start"))    # /start command
@router.message(F.text)              # messages with text
@router.edited_message()             # edited messages
@router.deleted_message()            # deleted messages
@router.callback_query()             # inline button presses
@router.new_chat_members()           # user joined
@router.left_chat_members()          # user left
@router.pinned_message()             # message pinned
@router.unpinned_message()           # message unpinned
@router.changed_chat_info()          # chat info changed
@router.error()                      # unhandled exceptions
```

---

## Filters

```python
from vkworkspace import F
from vkworkspace.filters import Command, ChatTypeFilter, CallbackData, CallbackDataFactory
from vkworkspace.filters.state import StateFilter
from vkworkspace.filters.regexp import RegexpFilter
from vkworkspace.filters.message_parts import ReplyFilter, ForwardFilter
```

### Magic Filter (F)

```python
@router.message(F.text)                        # has text
@router.message(F.text.startswith("hello"))     # text starts with
@router.message(F.from_user.user_id == "admin@corp.ru")  # specific user
@router.callback_query(F.callback_data == "confirm")      # exact callback
@router.callback_query(F.callback_data.startswith("action_"))  # prefix
```

### Command Filter

```python
@router.message(Command("start"))              # /start
@router.message(Command("help", "info"))       # /help OR /info
@router.message(Command(re.compile(r"cmd_\d+")))  # regex
@router.message(Command("menu", prefix=("!", "/")))  # !menu or /menu
@router.message(Command())                     # any command

# Access parsed command in handler:
@router.message(Command("greet"))
async def greet(message: Message, command: CommandObject):
    name = command.args or "World"    # /greet John → args="John"
    await message.answer(f"Hello, {name}!")
```

### Other Filters

```python
# Chat type
@router.message(ChatTypeFilter("private"))     # DM only
@router.message(ChatTypeFilter("group"))       # group only

# FSM state
@router.message(StateFilter(Form.waiting_name))

# Regex
@router.message(RegexpFilter(r"\d{4}-\d{2}-\d{2}"))  # date pattern

# Callback data (exact or regex)
@router.callback_query(CallbackData("confirm"))
@router.callback_query(CallbackData(re.compile(r"^action_\d+$")))

# Reply / Forward
@router.message(ReplyFilter())     # message is a reply
@router.message(ForwardFilter())   # message is forwarded

# Combine filters
@router.message(Command("start"), ChatTypeFilter("private"))  # AND
@router.message(Command("a") | Command("b"))                  # OR
@router.message(~Command("start"))                             # NOT
```

---

## Message Object

```python
@router.message()
async def handler(message: Message):
    # Properties
    message.msg_id          # str — message ID
    message.text            # str | None — message text
    message.chat            # Chat — chat object
    message.chat.chat_id    # str — chat ID (email-like)
    message.chat.type       # "private" | "group" | "channel"
    message.from_user       # Contact | None — sender
    message.from_user.user_id  # str — sender ID
    message.timestamp       # int | None — unix timestamp
    message.parts           # list[Part] — mentions, files, etc.
    message.format          # MessageFormat | None — formatting
    message.parent_topic    # ParentMessage | None — thread info
    message.is_thread_message  # bool

    # Convenience accessors
    message.mentions        # list[MentionPayload]
    message.reply_to        # ReplyMessagePayload | None
    message.forwards        # list[ReplyMessagePayload]
    message.files           # list[FilePayload]

    # Actions
    await message.answer("text")              # reply in same chat
    await message.reply("quoted reply")       # reply with quote
    await message.answer_thread("in thread")  # create/reply in thread
    await message.edit_text("new text")       # edit this message
    await message.delete()                    # delete this message
    await message.pin()                       # pin
    await message.unpin()                     # unpin
    await message.answer_file(file=InputFile("doc.pdf"))
    await message.answer_voice(file=InputFile(ogg_bytes, filename="voice.ogg"))
    await message.answer_chat_action()        # one-shot "typing..."

    # Typing indicator while processing
    async with message.typing():
        result = await slow_computation()
    await message.answer(result)
```

---

## CallbackQuery Object

```python
@router.callback_query(F.callback_data == "confirm")
async def on_confirm(query: CallbackQuery):
    query.query_id          # str — unique query ID
    query.callback_data     # str — data from button
    query.from_user         # Contact — who pressed
    query.message           # Message | None — original message

    await query.answer("Done!")                    # toast notification
    await query.answer("Sure?", show_alert=True)   # popup alert
    await query.answer(url="https://example.com")  # open URL

    # Edit the message that had the button
    if query.message:
        await query.message.edit_text("Updated!")
```

---

## Inline Keyboards

```python
from vkworkspace.utils.keyboard import InlineKeyboardBuilder
from vkworkspace.enums import ButtonStyle

builder = InlineKeyboardBuilder()
builder.button(text="Yes", callback_data="yes")
builder.button(text="No", callback_data="no")
builder.button(text="Delete", callback_data="del", style=ButtonStyle.ATTENTION)
builder.button(text="Docs", url="https://example.com/docs")
builder.adjust(2, 1)  # row 1: 2 buttons, row 2: 1 button

await message.answer("Choose:", inline_keyboard_markup=builder.as_markup())
```

### ButtonStyle

```python
ButtonStyle.BASE       # default gray
ButtonStyle.PRIMARY    # blue (default)
ButtonStyle.ATTENTION  # red
```

---

## CallbackDataFactory — Typed Callback Data

No more manual string parsing. Define fields once, pack/unpack automatically.

```python
from vkworkspace.filters import CallbackDataFactory

class ProductCB(CallbackDataFactory, prefix="product"):
    action: str   # "buy", "info", "fav"
    id: int       # product ID

# Pack into callback_data string
cb = ProductCB(action="buy", id=42)
cb.pack()  # "product:buy:42"

# Unpack from string
parsed = ProductCB.unpack("product:buy:42")
parsed.action  # "buy"
parsed.id      # 42

# Use as filter (with magic-filter rule)
@router.callback_query(ProductCB.filter(F.action == "buy"))
async def on_buy(query: CallbackQuery, callback_data: ProductCB):
    await query.answer(f"Buying product #{callback_data.id}")

# Filter without rule (match any ProductCB callback)
@router.callback_query(ProductCB.filter())
async def on_any_product(query: CallbackQuery, callback_data: ProductCB):
    ...

# Custom separator
class MyCB(CallbackDataFactory, prefix="my", sep="|"):
    field: str
# MyCB(field="val").pack() → "my|val"
```

---

## Paginator — Keyboard Pagination

```python
from vkworkspace.utils.paginator import Paginator, PaginationCB

ITEMS = ["Apple", "Banana", "Cherry", "Date", "Elderberry",
         "Fig", "Grape", "Honeydew", "Kiwi", "Lemon"]

def build_page(page: int):
    paginator = Paginator(data=ITEMS, per_page=3, current_page=page, name="fruits")

    builder = InlineKeyboardBuilder()
    for item in paginator.page_data:
        builder.button(text=item, callback_data=f"pick:{item}")
    builder.adjust(1)
    paginator.add_nav_row(builder)  # adds ◀ 2/4 ▶

    text = f"Page {page + 1}/{paginator.total_pages}"
    return text, builder.as_markup()

@router.message(Command("fruits"))
async def cmd_fruits(message: Message):
    text, markup = build_page(0)
    await message.answer(text, inline_keyboard_markup=markup)

@router.callback_query(PaginationCB.filter(F.name == "fruits"))
async def on_page(query: CallbackQuery, callback_data: PaginationCB):
    text, markup = build_page(callback_data.page)
    if query.message:
        await query.message.edit_text(text, inline_keyboard_markup=markup)
    await query.answer()
```

### Paginator Properties

```python
p = Paginator(data=items, per_page=5, current_page=0, name="my")
p.total_pages   # int — total page count
p.page_data     # slice of data for current page
p.offset        # int — start index
p.has_prev      # bool
p.has_next      # bool
p.nav_buttons() # list of InlineKeyboardButton (◀, 1/3, ▶)
p.add_nav_row(builder)  # appends nav row to builder
```

---

## FSM — Finite State Machine

Multi-step dialogs with state persistence.

```python
from vkworkspace.fsm import FSMContext, State, StatesGroup
from vkworkspace.fsm.storage.memory import MemoryStorage
from vkworkspace.filters.state import StateFilter

class RegistrationForm(StatesGroup):
    waiting_name = State()
    waiting_age = State()
    confirm = State()

@router.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext):
    await state.set_state(RegistrationForm.waiting_name)
    await message.answer("What is your name?")

@router.message(StateFilter(RegistrationForm.waiting_name), F.text)
async def got_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(RegistrationForm.waiting_age)
    await message.answer("How old are you?")

@router.message(StateFilter(RegistrationForm.waiting_age), F.text)
async def got_age(message: Message, state: FSMContext):
    data = await state.get_data()  # {"name": "John"}
    await state.clear()            # reset state + data
    await message.answer(f"Done! {data['name']}, age {message.text}")

@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Cancelled.")
```

### FSMContext Methods

```python
await state.set_state(Form.step)    # set state
await state.get_state()             # get current state string | None
await state.update_data(key=val)    # merge data
await state.get_data()              # get all data dict
await state.set_data({"k": "v"})    # replace all data
await state.clear()                 # clear state + data
```

### Storage Backends

```python
# In-memory (default, lost on restart)
dp = Dispatcher(storage=MemoryStorage())

# Redis (persistent, multi-process safe)
from vkworkspace.fsm.storage.redis import RedisStorage
dp = Dispatcher(storage=RedisStorage(url="redis://localhost:6379"))

# Session timeout (auto-clear after inactivity)
dp = Dispatcher(storage=MemoryStorage(), session_timeout=300)  # 5 min
```

---

## Middleware

```python
from vkworkspace import BaseMiddleware

class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        print(f"Event: {event}")
        result = await handler(event, data)  # call next handler
        print(f"Result: {result}")
        return result

class AdminOnlyMiddleware(BaseMiddleware):
    def __init__(self, admin_ids: list[str]):
        self.admin_ids = admin_ids

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user and user.user_id not in self.admin_ids:
            await event.answer("Access denied.")
            return None
        return await handler(event, data)

# Register on specific observer
router.message.middleware.register(LoggingMiddleware())
router.message.middleware.register(AdminOnlyMiddleware(["admin@corp.ru"]))
```

### DI via Middleware (inject custom objects)

```python
class InjectAPIMiddleware(BaseMiddleware):
    def __init__(self, api_client):
        self.api = api_client

    async def __call__(self, handler, event, data):
        data["api"] = self.api          # inject into handler kwargs
        return await handler(event, data)

@router.message(Command("data"))
async def get_data(message: Message, api):  # `api` auto-injected
    result = await api.fetch()
    await message.answer(str(result))
```

---

## Typing Actions

Show "Bot is typing..." while processing.

```python
from vkworkspace.utils.actions import typing_action, ChatActionSender
from vkworkspace.enums import ChatAction

# 1. Decorator — simplest way
@router.message(Command("slow"))
@typing_action
async def cmd_slow(message: Message):
    await asyncio.sleep(3)  # user sees "typing..."
    await message.answer("Done!")

# With custom action
@router.message(Command("look"))
@typing_action(action=ChatAction.LOOKING)
async def cmd_look(message: Message):
    await asyncio.sleep(2)
    await message.answer("Done looking!")

# 2. Context manager — explicit control
@router.message(Command("report"))
async def cmd_report(message: Message):
    async with message.typing():
        result = await slow_computation()
    await message.answer(result)

# 3. One-shot
@router.message(Command("ping"))
async def cmd_ping(message: Message):
    await message.answer_chat_action()  # sends "typing" once
    await asyncio.sleep(1)
    await message.answer("pong!")
```

---

## Text Formatting

```python
from vkworkspace.utils.text import html, md, Text, Bold, Italic, Code, Link

# HTML helpers
html.bold("text")               # <b>text</b>
html.italic("text")             # <i>text</i>
html.code("x = 1")             # <code>x = 1</code>
html.pre("code block")         # <pre>code block</pre>
html.link("click", "https://..") # <a href="...">click</a>
html.escape("<script>")        # &lt;script&gt;

# MarkdownV2 helpers
md.bold("text")                 # *text*
md.code("x = 1")              # `x = 1`

# Text builder (auto-escaping, composable)
content = Text(
    Bold("Welcome"), ", ", Italic("user"), "!\n",
    "Click ", Link("here", "https://example.com"),
)
await message.answer(**content.as_kwargs())  # auto parse_mode

# Split long text
from vkworkspace.utils.text import split_text
chunks = split_text(long_text, max_length=4096)
for chunk in chunks:
    await bot.send_text(chat_id, chunk)
```

### FormatBuilder (offset/length)

```python
from vkworkspace.utils.format_builder import FormatBuilder

fb = FormatBuilder()
fb.add("Hello, ")
fb.bold("World")
fb.add("! Visit ")
fb.link("our site", "https://example.com")

await bot.send_text(chat_id, fb.text, format_=fb.build())
```

---

## File Handling

```python
from vkworkspace.types import InputFile

# Upload from disk
await bot.send_file(chat_id, file=InputFile("report.pdf"))
await bot.send_file(chat_id, file=InputFile(Path("/tmp/photo.jpg")))

# From bytes
await bot.send_file(chat_id, file=InputFile(b"\x89PNG...", filename="image.png"))

# From URL (async download)
photo = await InputFile.from_url("https://http.cat/200.jpg")
await bot.send_file(chat_id, file=photo, caption="200 OK")

# From base64
file = InputFile.from_base64(b64_string, filename="avatar.png")

# Resend by file_id (instant, no re-upload)
await bot.send_file(chat_id, file_id="previously_uploaded_file_id")

# Voice (OGG/Opus recommended)
from vkworkspace.utils.voice import convert_to_ogg_opus
ogg = convert_to_ogg_opus("recording.mp3")  # requires pip install vkworkspace[voice]
await bot.send_voice(chat_id, file=InputFile(ogg, filename="voice.ogg"))

# Via message shortcut
await message.answer_file(file=InputFile("doc.pdf"), caption="Here!")
await message.answer_voice(file=InputFile(ogg, filename="voice.ogg"))
```

---

## Error Handling

```python
@router.error()
async def on_error(error: Exception, bot, raw_event, **kwargs):
    logging.exception("Unhandled error: %s", error)
    # Optionally notify admin
    await bot.send_text("admin@corp.ru", f"Bot error: {error}")
```

---

## Threads

```python
# Send message in a thread
await bot.send_text(chat_id, "In thread", parent_topic=parent_msg)

# Create a thread under a message
await message.answer_thread("Starting a thread here!")

# Check if message is from a thread
if message.is_thread_message:
    # message.parent_topic has thread info
    ...
```

---

## Enums

```python
from vkworkspace.enums import (
    ChatAction,    # TYPING, LOOKING
    ChatType,      # PRIVATE, GROUP, CHANNEL
    EventType,     # NEW_MESSAGE, CALLBACK_QUERY, ...
    ParseMode,     # MARKDOWNV2, HTML
    ButtonStyle,   # BASE, PRIMARY, ATTENTION
    PartType,      # EMAIL, MENTION, LINK, ...
    StyleType,     # BOLD, ITALIC, CODE, ...
)
```

---

## Types Reference

| Type | Module | Key Fields |
|------|--------|------------|
| `Message` | `vkworkspace.types` | msg_id, text, chat, from_user, parts, format, parent_topic |
| `CallbackQuery` | `vkworkspace.types` | query_id, callback_data, from_user, message |
| `Chat` | `vkworkspace.types` | chat_id, type, title |
| `Contact` | `vkworkspace.types.user` | user_id, first_name, last_name, nick |
| `ChatInfo` | `vkworkspace.types` | type, title, about, rules, is_public |
| `InputFile` | `vkworkspace.types` | file, filename; from_url(), from_base64() |
| `APIResponse` | `vkworkspace.types` | ok, msg_id, file_id |
| `Part` | `vkworkspace.types.message` | type, payload; as_mention, as_reply, as_forward, as_file |
| `FormatSpan` | `vkworkspace.types.message` | offset, length, url |
| `ParentMessage` | `vkworkspace.types.message` | chat_id, message_id, type |

---

## Complete Example: Multi-Step Order Bot

```python
import asyncio
from vkworkspace import Bot, Dispatcher, F, Router
from vkworkspace.filters import Command, CallbackDataFactory
from vkworkspace.filters.state import StateFilter
from vkworkspace.fsm import FSMContext, State, StatesGroup
from vkworkspace.types import CallbackQuery, Message
from vkworkspace.utils.keyboard import InlineKeyboardBuilder

router = Router()

class OrderCB(CallbackDataFactory, prefix="order"):
    action: str
    product_id: int

class OrderForm(StatesGroup):
    choosing = State()
    confirming = State()

PRODUCTS = {1: "Laptop $999", 2: "Phone $699", 3: "Tablet $499"}

@router.message(Command("shop"))
async def cmd_shop(message: Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    for pid, name in PRODUCTS.items():
        builder.button(text=name, callback_data=OrderCB(action="select", product_id=pid).pack())
    builder.adjust(1)
    await state.set_state(OrderForm.choosing)
    await message.answer("Choose a product:", inline_keyboard_markup=builder.as_markup())

@router.callback_query(OrderCB.filter(F.action == "select"))
async def on_select(query: CallbackQuery, callback_data: OrderCB, state: FSMContext):
    product = PRODUCTS[callback_data.product_id]
    await state.update_data(product_id=callback_data.product_id, product=product)
    await state.set_state(OrderForm.confirming)

    builder = InlineKeyboardBuilder()
    builder.button(text="Confirm", callback_data=OrderCB(action="confirm", product_id=callback_data.product_id).pack())
    builder.button(text="Cancel", callback_data=OrderCB(action="cancel", product_id=0).pack())
    builder.adjust(2)

    if query.message:
        await query.message.edit_text(
            f"Order: {product}\nConfirm?",
            inline_keyboard_markup=builder.as_markup(),
        )
    await query.answer()

@router.callback_query(OrderCB.filter(F.action == "confirm"))
async def on_confirm(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    await query.answer(f"Ordered: {data['product']}!", show_alert=True)

@router.callback_query(OrderCB.filter(F.action == "cancel"))
async def on_cancel(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.answer("Order cancelled.")

async def main():
    bot = Bot(token="TOKEN", api_url="https://myteam.mail.ru/bot/v1")
    dp = Dispatcher(session_timeout=300)
    dp.include_router(router)
    await dp.start_polling(bot)

asyncio.run(main())
```

---

## Installation

```bash
pip install vkworkspace                # core
pip install vkworkspace[redis]         # + Redis FSM storage
pip install vkworkspace[voice]         # + audio conversion (PyAV)
pip install vkworkspace[all]           # everything
```

## Key Imports

```python
from vkworkspace import Bot, Dispatcher, Router, F, BaseMiddleware
from vkworkspace.types import Message, CallbackQuery, InputFile
from vkworkspace.filters import Command, CallbackData, CallbackDataFactory, ChatTypeFilter
from vkworkspace.filters.state import StateFilter
from vkworkspace.filters.regexp import RegexpFilter
from vkworkspace.fsm import FSMContext, State, StatesGroup
from vkworkspace.fsm.storage.memory import MemoryStorage
from vkworkspace.utils.keyboard import InlineKeyboardBuilder
from vkworkspace.utils.paginator import Paginator, PaginationCB
from vkworkspace.utils.actions import typing_action, ChatActionSender
from vkworkspace.utils.text import html, md, Text, Bold, Italic, Code, Link, split_text
from vkworkspace.utils.format_builder import FormatBuilder
from vkworkspace.enums import ButtonStyle, ChatAction, ParseMode, ChatType
```
