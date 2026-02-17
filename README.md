# vkworkspace

**Fully asynchronous** framework for building bots on **VK Teams** (VK Workspace / VK SuperApp), inspired by [aiogram 3](https://github.com/aiogram/aiogram).

A modern replacement for the official [mail-ru-im/bot-python](https://github.com/mail-ru-im/bot-python) (`mailru-im-bot`) library.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/TimmekHW/vkworkspace/blob/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/vkworkspace.svg)](https://pypi.org/project/vkworkspace/)

> **[README на русском языке](https://github.com/TimmekHW/vkworkspace/blob/main/README_RU.md)**

## Table of Contents

- [vkworkspace vs mailru-im-bot](#vkworkspace-vs-mailru-im-bot)
- [Why async?](#why-async)
- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Bot Configuration](#bot-configuration)
- [Dispatcher](#dispatcher)
- [Router & Event Types](#router--event-types)
- [Filters](#filters)
- [Text Formatting](#text-formatting)
- [Inline Keyboards](#inline-keyboards)
- [FSM (Finite State Machine)](#fsm-finite-state-machine)
- [Custom Middleware](#custom-middleware)
- [Message Methods](#message-methods)
- [Bot API Methods](#bot-api-methods)
- [Handler Dependency Injection](#handler-dependency-injection)
- [Mini-Apps + Bots](#mini-apps--bots)
- [Testing](#testing)
- [Examples](#examples)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [License](#license)

## vkworkspace vs mailru-im-bot

The official [mailru-im-bot](https://github.com/mail-ru-im/bot-python) library is synchronous, based on `requests`, and has not been updated in years. **vkworkspace** is a ground-up async rewrite with a modern developer experience.

### Feature Comparison

| | mailru-im-bot | vkworkspace |
|---|:---:|:---:|
| **HTTP client** | `requests` (sync) | `httpx` (async) |
| **Models** | raw `dict` | Pydantic v2 |
| **Router / Dispatcher** | — | aiogram-style |
| **Magic filters (`F`)** | — | `F.text`, `F.chat.type == "private"` |
| **FSM (state machine)** | — | Memory + Redis backends |
| **Middleware pipeline** | — | inner/outer, per-event type |
| **Inline keyboard builder** | — | `InlineKeyboardBuilder` |
| **Rate limiter** | — | built-in token-bucket |
| **Retry on 5xx** | — | exponential backoff |
| **SSL control** | — | `verify_ssl=False` |
| **Proxy support** | — | `proxy=` parameter |
| **Handler DI** | — | auto-inject `bot`, `state`, `command` |
| **Custom command prefixes** | — | `prefix=("/", "!", "")` |
| **Error handlers** | — | `@router.error()` |
| **Type hints** | partial | full |

### Speed Benchmarks

Tested on Python 3.11, VK Teams corporate instance. 5 rounds per discipline, median values:

```
                          mailru-im-bot    vkworkspace     winner
                          (requests sync)  (httpx async)
 Bot Info (self/get)         34 ms            33 ms        ~tie
 Send Text                   82 ms           109 ms        mailru-im-bot
 Send Keyboard               97 ms            90 ms        vkworkspace
 Edit Message                57 ms            44 ms        vkworkspace
 Delete Message              33 ms            38 ms        mailru-im-bot
 Chat Info                   43 ms            42 ms        ~tie
 Send Actions                30 ms            28 ms        vkworkspace
 BURST (10 msgs)           1110 ms           335 ms        vkworkspace (3.3x!)
                          ───────────────────────────────────────────
 Score                        2                4           vkworkspace wins
```

**Key takeaway:** For single sequential requests, both libraries are within network noise (~1 ms difference). But when you need to send multiple messages or handle concurrent users, async wins decisively — **3.3x faster** on burst operations via `asyncio.gather()`.

The framework overhead is **zero** in real conditions. Network latency dominates 99%+ of total time.

## Why async?

VK Teams bots spend 99% of their time waiting for the network. Synchronous frameworks (`requests`) block the entire process on every API call. **vkworkspace** uses `httpx.AsyncClient` and `asyncio` — while one request waits for a response, the bot handles other messages.

## Features

- **100% async** — `httpx` + `asyncio`, zero blocking calls, real concurrency
- **Aiogram-like API** — `Router`, `Dispatcher`, `F` magic filters, middleware, FSM
- **Type-safe** — Pydantic v2 models for all API types, full type hints
- **Flexible filtering** — `Command`, `StateFilter`, `ChatTypeFilter`, `CallbackData`, `ReplyFilter`, `ForwardFilter`, regex, magic filters
- **Custom command prefixes** — `Command("start", prefix=("/", "!", ""))` for any prefix style
- **FSM** — Finite State Machine with Memory and Redis storage backends
- **Middleware** — inner/outer middleware pipeline for logging, auth, throttling
- **Text formatting** — `md`, `html` helpers for MarkdownV2/HTML + `FormatBuilder` for offset/length + `split_text` for long messages
- **Keyboard builder** — fluent API for inline keyboards with button styles
- **Rate limiter** — built-in request throttling (`rate_limit=5` = max 5 req/sec)
- **Retry on 5xx** — automatic retry with exponential backoff on server errors
- **SSL control** — disable SSL verification for on-premise with self-signed certs
- **FSM session timeout** — auto-clear abandoned FSM forms after configurable inactivity
- **Proxy support** — route API requests through corporate proxy
- **Edited message routing** — `handle_edited_as_message=True` to process edits as new messages
- **Lifecycle hooks** — `on_startup` / `on_shutdown` for init/cleanup logic
- **Error handlers** — `@router.error()` to catch exceptions from any handler
- **Multi-bot polling** — `dp.start_polling(bot1, bot2)` to poll multiple bots
- **9 event types** — message, edited, deleted, pinned, unpinned, members join/leave, chat info, callbacks
- **Python 3.11 — 3.14** support (free-threaded / no-GIL build not yet tested)

## Installation

```bash
pip install vkworkspace
```

With Redis FSM storage:

```bash
pip install vkworkspace[redis]
```

## Quick Start

```python
import asyncio
from vkworkspace import Bot, Dispatcher, Router, F
from vkworkspace.filters import Command
from vkworkspace.types import Message

router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer("Hello! I'm your bot.")

@router.message(F.text)
async def echo(message: Message) -> None:
    await message.answer(message.text)

async def main() -> None:
    bot = Bot(token="YOUR_TOKEN", api_url="https://myteam.mail.ru/bot/v1")
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)

asyncio.run(main())
```

> **API URL:** Each company has its own VK Teams API endpoint. Check with your IT/integrator for the correct URL. Common examples:
> - `https://myteam.mail.ru/bot/v1` (Mail.ru default)
> - `https://api.teams.yourcompany.ru/bot/v1` (on-premise)
> - `https://agent.mail.ru/bot/v1` (SaaS variant)
>
> Even SaaS deployments may have custom URLs — always verify with your administrator.

## Bot Configuration

```python
bot = Bot(
    token="YOUR_TOKEN",
    api_url="https://myteam.mail.ru/bot/v1",
    timeout=30.0,               # Request timeout (seconds)
    poll_time=60,               # Long-poll timeout (seconds)
    rate_limit=5.0,             # Max 5 requests/sec (None = unlimited)
    proxy="http://proxy:8080",  # HTTP proxy for corporate networks
    parse_mode="HTML",          # Default parse mode for all messages (None = plain text)
    retry_on_5xx=3,             # Retry up to 3 times on 5xx errors (None = disabled)
    verify_ssl=True,            # Set False for self-signed certs (on-premise)
)
```

### Rate Limiter

Built-in token-bucket rate limiter prevents API throttling:

```python
# Max 10 requests per second — framework queues the rest automatically
bot = Bot(token="TOKEN", api_url="URL", rate_limit=10)
```

### Proxy

Corporate networks often require a proxy. The `proxy` parameter applies only to API calls:

```python
bot = Bot(
    token="TOKEN",
    api_url="https://api.internal.corp/bot/v1",
    proxy="http://corp-proxy.internal:3128",
)
```

### Retry on 5xx

Automatic retry with exponential backoff (1s, 2s, 4s, max 8s) on server errors:

```python
bot = Bot(token="TOKEN", api_url="URL", retry_on_5xx=3)   # 3 retries (default)
bot = Bot(token="TOKEN", api_url="URL", retry_on_5xx=None) # Disabled
```

### SSL Verification

On-premise installations with self-signed certificates can disable SSL verification:

```python
bot = Bot(token="TOKEN", api_url="https://internal.corp/bot/v1", verify_ssl=False)
```

### Default Parse Mode

`parse_mode` can be set in **two places** — globally on `Bot`, or per-message on `answer()` / `reply()` / `send_text()`:

```python
from vkworkspace.enums import ParseMode

# ── 1. Global default on Bot ──────────────────────────────────────
# Applies to ALL send_text / answer / reply / edit_text / send_file
bot = Bot(
    token="TOKEN",
    api_url="https://myteam.mail.ru/bot/v1",
    parse_mode=ParseMode.HTML,  # or ParseMode.MARKDOWNV2
)

# parse_mode="HTML" is sent automatically — no need to pass it
await message.answer(f"{html.bold('Hello')}, world!")

# ── 2. Override per message ───────────────────────────────────────
await message.answer("*bold*", parse_mode=ParseMode.MARKDOWNV2)

# ── 3. Disable for a single message ──────────────────────────────
await message.answer("plain text", parse_mode=None)
```

> **Tip:** IDE autocomplete works — type `parse_mode=ParseMode.` and your editor will suggest `HTML` and `MARKDOWNV2`.

## Dispatcher

```python
dp = Dispatcher(
    storage=MemoryStorage(),            # FSM storage (default: MemoryStorage)
    fsm_strategy="user_in_chat",        # FSM key strategy
    handle_edited_as_message=False,     # Route edits to @router.message handlers
)

# Lifecycle hooks
@dp.on_startup
async def on_start():
    print("Bot started!")

@dp.on_shutdown
async def on_stop():
    print("Bot stopped!")

# Include routers
dp.include_router(router)
dp.include_routers(admin_router, user_router)

# Start polling (supports multiple bots)
await dp.start_polling(bot)
await dp.start_polling(bot1, bot2, skip_updates=True)
```

### Edited Message Routing

When `handle_edited_as_message=True`, edited messages are routed to `@router.message` handlers instead of `@router.edited_message`. Useful when you don't need to distinguish between new and edited messages:

```python
dp = Dispatcher(handle_edited_as_message=True)

# This handler fires for BOTH new and edited messages
@router.message(F.text)
async def handle_text(message: Message) -> None:
    await message.answer(f"Got: {message.text}")
```

## Router & Event Types

```python
router = Router(name="my_router")

# All 9 supported event types:
@router.message(...)              # New message
@router.edited_message(...)       # Edited message
@router.deleted_message(...)      # Deleted message
@router.pinned_message(...)       # Pinned message
@router.unpinned_message(...)     # Unpinned message
@router.new_chat_members(...)     # Users joined
@router.left_chat_members(...)    # Users left
@router.changed_chat_info(...)    # Chat info changed
@router.callback_query(...)       # Button clicked

# Error handler — catches exceptions from any handler
@router.error()
async def on_error(event, error: Exception) -> None:
    print(f"Error: {error}")

# Sub-routers for modular code
admin_router = Router(name="admin")
user_router = Router(name="user")
main_router = Router()
main_router.include_routers(admin_router, user_router)
```

## Filters

### Command Filter

```python
from vkworkspace.filters import Command

# Basic
@router.message(Command("start"))
@router.message(Command("help", "info"))     # Multiple commands

# Custom prefixes
@router.message(Command("start", prefix="/"))           # Only /start
@router.message(Command("menu", prefix=("/", "!", ""))) # /menu, !menu, menu

# Regex commands
import re
@router.message(Command(re.compile(r"cmd_\d+")))        # /cmd_1, /cmd_42, ...

# Access command arguments in handler
@router.message(Command("ban"))
async def ban_user(message: Message, command: CommandObject) -> None:
    user_to_ban = command.args  # Text after "/ban "
    await message.answer(f"Banned: {user_to_ban}")
```

`CommandObject` injected into handler:
- `prefix` — matched prefix (`"/"`, `"!"`, etc.)
- `command` — command name (`"ban"`)
- `args` — arguments after command (`"user123"`)
- `raw_text` — full message text
- `match` — `re.Match` if regex pattern was used

### Magic Filter (F)

```python
from vkworkspace import F

@router.message(F.text)                              # Has text
@router.message(F.text == "hello")                   # Exact match
@router.message(F.text.startswith("hi"))             # String methods
@router.message(F.from_user.user_id == "admin@co")   # Nested attrs
@router.message(F.chat.type == "private")            # Private chat
@router.message(F.chat.type.in_(["private", "group"]))
@router.callback_query(F.callback_data == "confirm")
```

### State Filter

```python
from vkworkspace.filters.state import StateFilter

@router.message(StateFilter(Form.name))     # Specific state
@router.message(StateFilter("*"))           # Any state (non-None)
@router.message(StateFilter(None))          # No state (default)
```

### Other Filters

```python
from vkworkspace.filters import (
    CallbackData, ChatTypeFilter, RegexpFilter,
    ReplyFilter, ForwardFilter, RegexpPartsFilter,
)

# Callback data
@router.callback_query(CallbackData("confirm"))
@router.callback_query(CallbackData(re.compile(r"^action_\d+$")))

# Chat type
@router.message(ChatTypeFilter("private"))
@router.message(ChatTypeFilter(["private", "group"]))

# Regex on message text
@router.message(RegexpFilter(r"\d{4}"))

# Reply / Forward detection
@router.message(ReplyFilter())       # Message is a reply
@router.message(ForwardFilter())     # Message contains forwards

# Regex on reply/forward text
@router.message(RegexpPartsFilter(r"urgent|asap"))
async def on_urgent(message: Message, regexp_parts_match) -> None:
    await message.answer("Forwarded message contains urgent text!")

# Combine filters with &, |, ~
@router.message(ChatTypeFilter("private") & Command("secret"))
```

### Custom Filters

```python
from vkworkspace.filters.base import BaseFilter

class IsAdmin(BaseFilter):
    async def __call__(self, event, **kwargs) -> bool:
        admins = await event.bot.get_chat_admins(event.chat.chat_id)
        return any(a.user_id == event.from_user.user_id for a in admins)

@router.message(IsAdmin())
async def admin_only(message: Message) -> None:
    await message.answer("Admin panel")
```

## Text Formatting

VK Teams supports MarkdownV2 and HTML formatting. Use the `md` and `html` helpers to build formatted messages safely:

```python
from vkworkspace.utils.text import md, html, split_text

# ── MarkdownV2 ──
text = f"{md.bold('Status')}: {md.escape(user_input)}"
await message.answer(text, parse_mode="MarkdownV2")

md.bold("text")            # *text*
md.italic("text")          # _text_
md.underline("text")       # __text__
md.strikethrough("text")   # ~text~
md.code("x = 1")           # `x = 1`
md.pre("code", "python")   # ```python\ncode\n```
md.link("Click", "https://example.com")  # [Click](https://example.com)
md.quote("quoted text")    # >quoted text
md.mention("user@company.ru")  # @\[user@company\.ru\]
md.escape("price: $100")   # Escapes special chars

# ── HTML ──
text = f"{html.bold('Status')}: {html.escape(user_input)}"
await message.answer(text, parse_mode="HTML")

html.bold("text")           # <b>text</b>
html.italic("text")         # <i>text</i>
html.underline("text")      # <u>text</u>
html.strikethrough("text")  # <s>text</s>
html.code("x = 1")          # <code>x = 1</code>
html.pre("code", "python")  # <pre><code class="python">code</code></pre>
html.link("Click", "https://example.com")  # <a href="...">Click</a>
html.quote("quoted text")   # <blockquote>quoted text</blockquote>
html.mention("user@company.ru")  # @[user@company.ru]
html.ordered_list(["a", "b"])    # <ol><li>a</li><li>b</li></ol>
html.unordered_list(["a", "b"]) # <ul><li>a</li><li>b</li></ul>

# ── Split long text ──
# VK Teams may lag on messages > 4096 chars; split_text breaks them up
for chunk in split_text(long_text):
    await message.answer(chunk)

# Custom limit
for chunk in split_text(long_text, max_length=2000):
    await message.answer(chunk)
```

### Text Builder (aiogram-style)

Composable formatting nodes with auto-escaping and automatic `parse_mode`. No need to think about which parse mode to use — `as_kwargs()` handles it:

```python
from vkworkspace.utils.text import Text, Bold, Italic, Code, Link, Pre, Quote, Mention

# Compose text from nodes — strings are auto-escaped
content = Text(
    Bold("Order #42"), "\n",
    "Status: ", Italic("processing"), "\n",
    "Total: ", Code("$99.99"),
)
await message.answer(**content.as_kwargs())  # text + parse_mode="HTML" auto

# Nesting works
content = Bold(Italic("bold italic"))           # <b><i>bold italic</i></b>

# Operator chaining
content = "Hello, " + Bold("World") + "!"      # Text node
await message.answer(**content.as_kwargs())

# Render as MarkdownV2 instead
await message.answer(**content.as_kwargs("MarkdownV2"))
```

Available nodes: `Text`, `Bold`, `Italic`, `Underline`, `Strikethrough`, `Code`, `Pre`, `Link`, `Mention`, `Quote`, `Raw`

> **Warning:** Do not mix string helpers (`md.*` / `html.*`) with node builder — raw strings inside nodes get auto-escaped, so `Text(md.bold("x"))` produces literal `*x*`, not bold. Use `Bold("x")` instead.

### Format Builder (offset/length)

VK Teams also supports formatting via the `format` parameter — a JSON dict with offset/length ranges instead of markup. `FormatBuilder` makes it easy:

```python
from vkworkspace.utils import FormatBuilder

# By offset/length
fb = FormatBuilder("Hello, World! Click here.")
fb.bold(0, 5)                               # "Hello" bold
fb.italic(7, 6)                              # "World!" italic
fb.link(14, 10, url="https://example.com")   # "Click here" as link
await bot.send_text(chat_id, fb.text, format_=fb.build())

# By substring (auto-find offset)
fb = FormatBuilder("Order #42 is ready! Visit https://shop.com")
fb.bold_text("Order #42")
fb.italic_text("ready")
fb.link_text("https://shop.com", url="https://shop.com")
await bot.send_text(chat_id, fb.text, format_=fb.build())
```

Supported styles: `bold`, `italic`, `underline`, `strikethrough`, `link`, `mention`, `inline_code`, `pre`, `ordered_list`, `unordered_list`, `quote`. All methods support chaining.

## Inline Keyboards

```python
from vkworkspace.utils.keyboard import InlineKeyboardBuilder
from vkworkspace.enums import ButtonStyle

builder = InlineKeyboardBuilder()
builder.button(text="Yes", callback_data="confirm", style=ButtonStyle.PRIMARY)
builder.button(text="No", callback_data="cancel", style=ButtonStyle.ATTENTION)
builder.button(text="Maybe", callback_data="maybe")
builder.adjust(2, 1)  # Row 1: 2 buttons, Row 2: 1 button

await message.answer("Are you sure?", inline_keyboard_markup=builder.as_markup())

# Copy & modify
builder2 = builder.copy()
builder2.button(text="Extra", callback_data="extra")
```

## FSM (Finite State Machine)

```python
from vkworkspace.fsm import StatesGroup, State, FSMContext
from vkworkspace.filters.state import StateFilter
from vkworkspace.fsm.storage.memory import MemoryStorage

class Form(StatesGroup):
    name = State()
    age = State()

@router.message(Command("start"))
async def start(message: Message, state: FSMContext) -> None:
    await state.set_state(Form.name)
    await message.answer("What is your name?")

@router.message(StateFilter(Form.name), F.text)
async def process_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text)
    await state.set_state(Form.age)
    await message.answer("How old are you?")

@router.message(StateFilter(Form.age), F.text)
async def process_age(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(f"Name: {data['name']}, Age: {message.text}")
    await state.clear()

# Storage backends
dp = Dispatcher(storage=MemoryStorage())          # In-memory (dev)

from vkworkspace.fsm.storage.redis import RedisStorage
dp = Dispatcher(storage=RedisStorage())           # Redis (prod)
```

FSMContext methods:
- `await state.get_state()` — current state (or `None`)
- `await state.set_state(Form.name)` — transition to state
- `await state.get_data()` — get stored data dict
- `await state.update_data(key=value)` — merge into data
- `await state.set_data({...})` — replace data entirely
- `await state.clear()` — clear state and data

### FSM Session Timeout

Prevent users from getting stuck in abandoned FSM forms. When enabled, the middleware automatically clears expired FSM sessions:

```python
dp = Dispatcher(
    storage=MemoryStorage(),
    session_timeout=300,  # 5 minutes — clear FSM if user is inactive
)
```

If a user starts a form and doesn't finish within 5 minutes, the next message clears the state and goes through as a normal message — no more "Enter your age" after 3 days of silence.

Disabled by default (`session_timeout=None`).

## Custom Middleware

```python
from vkworkspace import BaseMiddleware

class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        print(f"Event from: {event.from_user.user_id}")
        result = await handler(event, data)
        print(f"Handled OK")
        return result

class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self.last: dict[str, float] = {}

    async def __call__(self, handler, event, data):
        import time
        uid = getattr(event, "from_user", None)
        uid = uid.user_id if uid else "unknown"
        now = time.monotonic()
        if now - self.last.get(uid, 0) < self.delay:
            return None  # Skip handler — too fast
        self.last[uid] = now
        return await handler(event, data)

# Register on specific event observer
router.message.middleware.register(LoggingMiddleware())
router.message.middleware.register(ThrottleMiddleware(delay=0.5))
router.callback_query.middleware.register(LoggingMiddleware())
```

## Message Methods

```python
# In handler:
await message.answer("Hello!")                                # Send to same chat
await message.reply("Reply to you!")                          # Reply to this message
await message.edit_text("Updated text")                       # Edit this message
await message.delete()                                        # Delete this message
await message.pin()                                           # Pin this message
await message.unpin()                                         # Unpin this message
await message.answer_file(file=InputFile("photo.jpg"))        # Send file
await message.answer_voice(file=InputFile("audio.ogg"))       # Send voice
```

## Bot API Methods

```python
bot = Bot(token="TOKEN", api_url="URL")

# Self
await bot.get_me()

# Messages
await bot.send_text(chat_id, "Hello!", parse_mode="HTML")
await bot.send_text(chat_id, "Hi", reply_msg_id=msg_id)               # Reply
await bot.send_text(chat_id, "Hi", reply_msg_id=[id1, id2])           # Multi-reply
await bot.send_text(chat_id, "Hi", forward_chat_id=cid, forward_msg_id=mid)  # Forward
await bot.send_text(chat_id, "Hi", request_id="unique-123")           # Idempotent send
await bot.send_text_with_deeplink(chat_id, "Open", deeplink="payload")  # Deeplink
await bot.edit_text(chat_id, msg_id, "Updated")
await bot.delete_messages(chat_id, msg_id)
await bot.send_file(chat_id, file=InputFile("photo.jpg"), caption="Look!")
await bot.send_voice(chat_id, file=InputFile("voice.ogg"))
await bot.answer_callback_query(query_id, "Done!", show_alert=True)

# Chat management
await bot.get_chat_info(chat_id)
await bot.get_chat_admins(chat_id)
await bot.get_chat_members(chat_id)
await bot.get_blocked_users(chat_id)
await bot.get_pending_users(chat_id)
await bot.set_chat_title(chat_id, "New Title")
await bot.set_chat_about(chat_id, "Description")
await bot.set_chat_rules(chat_id, "Rules")
await bot.set_chat_avatar(chat_id, file=InputFile("avatar.png"))
await bot.block_user(chat_id, user_id, del_last_messages=True)
await bot.unblock_user(chat_id, user_id)
await bot.resolve_pending(chat_id, approve=True, user_id=uid)
await bot.add_chat_members(chat_id, members=[uid1, uid2])              # Add members
await bot.delete_chat_members(chat_id, members=[uid1, uid2])           # Remove members
await bot.pin_message(chat_id, msg_id)
await bot.unpin_message(chat_id, msg_id)
await bot.send_actions(chat_id, "typing")

# Files & Threads
await bot.get_file_info(file_id)
await bot.threads_add(chat_id, msg_id)
await bot.threads_get_subscribers(thread_id)
await bot.threads_autosubscribe(chat_id, enable=True)
```

## Handler Dependency Injection

Handlers receive only the parameters they declare. The framework inspects the signature and injects available values:

```python
@router.message(Command("info"))
async def full_handler(
    message: Message,              # The message object
    bot: Bot,                      # Bot instance
    state: FSMContext,             # FSM context (if storage configured)
    command: CommandObject,        # Parsed command (from Command filter)
    raw_event: dict,               # Raw VK Teams event dict
    event_type: str,               # "message", "callback_query", etc.
) -> None:
    ...

# Minimal — only take what you need
@router.message(F.text)
async def simple(message: Message) -> None:
    await message.answer(message.text)
```

## Mini-Apps + Bots

VK Teams mini-apps (WebView apps inside the client) **cannot send notifications or messages** to users. The official recommendation is to use a bot as the notification channel.

Typical pattern:

1. Bot sends a message with a **mini-app link** (with parameters for deep-linking)
2. Mini-app opens, identifies the user via `GetSelfId` / `GetAuth` (JS Bridge)
3. Mini-app communicates with its own backend (can be the same server as the bot)
4. For notifications back to the user — the **bot sends messages** via the Bot API

```python
# Bot sends a deep-link to a mini-app
miniapp_url = "https://u.myteam.mail.ru/miniapp/my-app-id?order=42"
await message.answer(
    f"Open your order: {miniapp_url}",
)
```

> Mini-apps are registered via **Metabot** (`/newapp`) — the same bot used for bot management (`/newbot`).

## Testing

The project includes two types of tests:

### Unit Tests (mocked)

```bash
pip install -e ".[dev]"
pytest tests/test_bot_api.py -v
```

98 tests covering all Bot API methods and FSM with mocked HTTP transport — no real API calls.

### Live API Tests

Run against a real VK Teams instance to verify all methods work in your environment:

```bash
python tests/test_bot_live.py \
    --token "YOUR_BOT_TOKEN" \
    --api-url "https://myteam.mail.ru/bot/v1" \
    --chat "GROUP_CHAT_ID"
```

Or via environment variables:

```bash
export VKWS_TOKEN="..."
export VKWS_API_URL="https://myteam.mail.ru/bot/v1"
export VKWS_CHAT_ID="12345@chat.agent"
python tests/test_bot_live.py
```

The live test sends real messages, tests all endpoints, and cleans up after itself. Methods unsupported on your installation (e.g. threads) are automatically skipped.

## Examples

| Example | Description |
|---------|-------------|
| [echo_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/echo_bot.py) | Basic commands + text echo |
| [keyboard_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/keyboard_bot.py) | Inline keyboards + callback handling |
| [fsm_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/fsm_bot.py) | Multi-step dialog with FSM + session timeout |
| [middleware_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/middleware_bot.py) | Custom middleware (logging, access control) |
| [formatting_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/formatting_bot.py) | MarkdownV2/HTML formatting + Text builder + FormatBuilder |
| [proxy_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/proxy_bot.py) | Corporate proxy + rate limiter + retry on 5xx + SSL control |
| [error_handling_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/error_handling_bot.py) | Error handlers, lifecycle hooks, edited message routing |
| [custom_prefix_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/custom_prefix_bot.py) | Custom command prefixes, regex commands, argument parsing |
| [multi_router_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/multi_router_bot.py) | Modular sub-routers, chat events, ReplyFilter, ForwardFilter |
| [event_logger_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/event_logger_bot.py) | Logs all 9 event types to JSONL file |

## Project Structure

```
vkworkspace/
├── client/          # Async HTTP client (httpx), rate limiter, proxy
├── types/           # Pydantic v2 models (Message, Chat, User, CallbackQuery, ...)
├── enums/           # EventType, ChatType, ParseMode, ButtonStyle, ...
├── dispatcher/      # Dispatcher, Router, EventObserver, Middleware pipeline
├── filters/         # Command, StateFilter, CallbackData, ChatType, Regexp
├── fsm/             # StatesGroup, State, FSMContext, Memory/Redis storage
└── utils/           # InlineKeyboardBuilder, magic filter (F), text formatting (md, html, split_text)
```

## Requirements

- Python 3.11+
- httpx >= 0.28.1
- pydantic >= 2.6
- magic-filter >= 1.0.12

## License

MIT [LICENSE](https://github.com/TimmekHW/vkworkspace/blob/main/LICENSE).

---

<sub>**Keywords:** VK Teams bot, VK Workspace bot, VK WorkSpace, VK SuperApp, vkteams, workspace.vk.ru, workspacevk, vkworkspace, myteam.mail.ru, agent.mail.ru, mail-ru-im-bot, mailru-im-bot, bot-python, VK Teams API, VK Teams framework, async bot framework, Python bot VK Teams, aiogram VK Teams, httpx bot, Pydantic bot framework</sub>
