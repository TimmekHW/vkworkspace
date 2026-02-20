#!/usr/bin/env python3
"""Generate llm_full.md — comprehensive LLM reference for vkworkspace.

Reads source files, extracts public API (methods, types, enums),
and assembles a single Markdown reference that any LLM can use
to write VK Teams bots without reading the docs.

Usage:
    python scripts/gen_llm_ref.py
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "vkworkspace"
OUTPUT = ROOT / "llm_full.md"


# ── Extractors ────────────────────────────────────────────────────────


def get_version() -> str:
    """Read __version__ from __meta__.py."""
    text = (SRC / "__meta__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else "0.0.0"


def _first_line_docstring(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Extract the first line of a function/method docstring."""
    ds = ast.get_docstring(node)
    if not ds:
        return ""
    return ds.split("\n")[0].strip()


def _extract_endpoint(docstring: str) -> str:
    """Extract API endpoint from docstring like 'Send text. ``messages/sendText``'."""
    m = re.search(r"``([a-zA-Z]+/[a-zA-Z/.]+)``", docstring)
    return m.group(1) if m else ""


def _return_annotation(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Get return type annotation as string."""
    if node.returns is None:
        return ""
    return ast.unparse(node.returns)


_SKIP_BOT_METHODS = {"get_session", "close", "get_events"}

# Fallback endpoints for methods whose docstrings lack ``endpoint`` markup
_ENDPOINT_FALLBACK: dict[str, str] = {
    "answer_callback_query": "messages/answerCallbackQuery",
}


def extract_bot_methods() -> list[dict[str, str]]:
    """Parse bot.py → public async methods with name, endpoint, description, return type."""
    tree = ast.parse((SRC / "client" / "bot.py").read_text(encoding="utf-8"))
    methods: list[dict[str, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "Bot":
            continue
        for item in node.body:
            if not isinstance(item, ast.AsyncFunctionDef):
                continue
            if item.name.startswith("_") or item.name in _SKIP_BOT_METHODS:
                continue

            doc = _first_line_docstring(item)
            endpoint = _extract_endpoint(doc) or _ENDPOINT_FALLBACK.get(item.name, "")
            # Strip endpoint from description
            desc = re.sub(r"\s*``[^`]+``\s*", "", doc).strip().rstrip(".")
            ret = _return_annotation(item)

            methods.append(
                {
                    "name": item.name,
                    "endpoint": endpoint,
                    "description": desc,
                    "return": ret,
                }
            )
    return methods


def extract_bot_init_params() -> list[dict[str, str]]:
    """Extract Bot.__init__ parameters with defaults."""
    tree = ast.parse((SRC / "client" / "bot.py").read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "Bot":
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef) or item.name != "__init__":
                continue
            params: list[dict[str, str]] = []
            args = item.args
            # Skip 'self'
            all_args = args.args[1:]
            defaults_offset = len(all_args) - len(args.defaults)
            for i, arg in enumerate(all_args):
                name = arg.arg
                ann = ast.unparse(arg.annotation) if arg.annotation else ""
                default_idx = i - defaults_offset
                default = ""
                if default_idx >= 0 and default_idx < len(args.defaults):
                    default = ast.unparse(args.defaults[default_idx])
                params.append({"name": name, "type": ann, "default": default})
            return params
    return []


def extract_send_text_params() -> list[dict[str, str]]:
    """Extract send_text parameters."""
    tree = ast.parse((SRC / "client" / "bot.py").read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "Bot":
            continue
        for item in node.body:
            if not isinstance(item, ast.AsyncFunctionDef) or item.name != "send_text":
                continue
            params: list[dict[str, str]] = []
            args = item.args
            all_args = args.args[1:]  # skip self
            defaults_offset = len(all_args) - len(args.defaults)
            for i, arg in enumerate(all_args):
                name = arg.arg
                ann = ast.unparse(arg.annotation) if arg.annotation else ""
                default_idx = i - defaults_offset
                default = ""
                if default_idx >= 0 and default_idx < len(args.defaults):
                    raw = ast.unparse(args.defaults[default_idx])
                    if raw != "_UNSET":
                        default = raw
                params.append({"name": name, "type": ann, "default": default})
            return params
    return []


def extract_router_observers() -> list[dict[str, str]]:
    """Extract event observer names and comments from router.py."""
    tree = ast.parse((SRC / "dispatcher" / "router.py").read_text(encoding="utf-8"))

    # Get observer descriptions from the docstring
    descriptions: dict[str, str] = {
        "message": "any message",
        "edited_message": "edited messages",
        "deleted_message": "deleted messages",
        "callback_query": "inline button presses",
        "new_chat_members": "user joined",
        "left_chat_members": "user left",
        "pinned_message": "message pinned",
        "unpinned_message": "message unpinned",
        "changed_chat_info": "chat info changed",
        "error": "unhandled exceptions",
    }

    observers: list[dict[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "Router":
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef) or item.name != "__init__":
                continue
            for stmt in item.body:
                if not isinstance(stmt, ast.Assign):
                    continue
                for target in stmt.targets:
                    if not isinstance(target, ast.Attribute):
                        continue
                    name = target.attr
                    if name in descriptions:
                        observers.append(
                            {
                                "name": name,
                                "description": descriptions[name],
                            }
                        )
    return observers


def extract_enum_members(filename: str) -> list[dict[str, str]]:
    """Extract enum class members from a file."""
    tree = ast.parse((SRC / "enums" / filename).read_text(encoding="utf-8"))
    members: list[dict[str, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        val = ast.unparse(item.value) if item.value else ""
                        members.append({"name": target.id, "value": val})
    return members


def extract_all_enums() -> dict[str, list[dict[str, str]]]:
    """Extract all enum classes with their members."""
    enum_files = [
        ("ChatAction", "chat_action.py"),
        ("ChatType", "chat_type.py"),
        ("ParseMode", "parse_mode.py"),
        ("EventType", "event_type.py"),
        ("ButtonStyle", "button_style.py"),
        ("PartType", "part_type.py"),
        ("StyleType", "style_type.py"),
    ]
    result: dict[str, list[dict[str, str]]] = {}
    for class_name, filename in enum_files:
        result[class_name] = extract_enum_members(filename)
    return result


def extract_types_exports() -> list[str]:
    """Get all exported type names from types/__init__.py."""
    tree = ast.parse((SRC / "types" / "__init__.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "__all__"
                    and isinstance(node.value, ast.List)
                ):
                    return [ast.literal_eval(elt) for elt in node.value.elts]
    return []


# ── Template sections ─────────────────────────────────────────────────


def section_header(version: str) -> str:
    return f"""\
# vkworkspace — Complete LLM Reference

> Async Python framework for VK Teams (VK Workspace) bots, inspired by aiogram 3.
> Version {version} · Python 3.11+ · `pip install vkworkspace`

**Этот файл — полная справка по фреймворку vkworkspace.**
Отдайте его целиком в ChatGPT, Claude или любую другую LLM и попросите написать бота — модель сможет использовать все возможности фреймворка без дополнительной документации.

> Пример промпта: *«Вот справка по фреймворку vkworkspace (llm_full.md). Напиши бота, который принимает номер договора и возвращает список документов из базы данных.»*

---"""


QUICK_START = """\

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

---"""


def section_bot(
    init_params: list[dict[str, str]],
    methods: list[dict[str, str]],
    send_text_params: list[dict[str, str]],
) -> str:
    # Param descriptions (static, curated)
    param_comments: dict[str, str] = {
        "token": "Bot token from MetaBot",
        "api_url": "on-premise URL",
        "timeout": "HTTP timeout in seconds",
        "poll_time": "long-poll timeout",
        "rate_limit": "max req/sec (token-bucket), None = unlimited",
        "proxy": "corporate proxy URL",
        "parse_mode": "default for all messages",
        "retry_on_5xx": "auto-retry on server errors",
        "verify_ssl": "False for self-signed certs",
    }

    ctor_display_lines = ["bot = Bot("]
    for p in init_params:
        comment = param_comments.get(p["name"], "")
        default = p["default"]
        if not default:
            line = f'    {p["name"]}="TOKEN_FROM_METABOT",'
        else:
            val = default.replace("'", '"')
            line = f"    {p['name']}={val},"
        if comment:
            line += f"  # {comment}"
        ctor_display_lines.append(line)
    ctor_display_lines.append(")")
    ctor_display = "\n".join(ctor_display_lines)

    # Methods table
    table_lines = ["| Method | API Endpoint | Description |"]
    table_lines.append("|--------|-------------|-------------|")
    for m in methods:
        name = m["name"]
        endpoint = m["endpoint"]
        desc = m["description"]
        ret = m["return"]
        ret_str = f" → `{ret}`" if ret else ""
        ep_str = f"`{endpoint}`" if endpoint else ""
        table_lines.append(f"| `await bot.{name}(...)`{ret_str} | {ep_str} | {desc} |")
    methods_table = "\n".join(table_lines)

    # send_text params
    st_lines = ["await bot.send_text("]
    st_comments: dict[str, str] = {
        "chat_id": "target chat ID",
        "text": "message text",
        "reply_msg_id": "reply to message",
        "forward_chat_id": "forward from",
        "forward_msg_id": "forward message ID",
        "inline_keyboard_markup": "inline keyboard",
        "parse_mode": '"HTML" / "MarkdownV2" / None',
        "format_": "offset/length formatting",
        "parent_topic": "send in thread",
        "request_id": "idempotency key",
    }
    for p in send_text_params:
        comment = st_comments.get(p["name"], "")
        default = p["default"]
        if p["name"] == "chat_id":
            val = '"user@company.ru"'
        elif p["name"] == "text":
            val = '"Hello!"'
        elif default:
            val = default.replace("'", '"')
        else:
            val = "..."
        line = f"    {p['name']}={val},"
        if comment:
            line += f"  # {comment}"
        st_lines.append(line)
    st_lines.append(")")
    send_text_display = "\n".join(st_lines)

    return f"""\

## Bot — API Client

```python
from vkworkspace import Bot

{ctor_display}
```

### Bot Methods

{methods_table}

### send_text Parameters

```python
{send_text_display}
```

### send_file Parameters

```python
await bot.send_file(
    chat_id="user@company.ru",  # target chat ID
    file_id=None,                # resend by file_id (instant, no re-upload)
    file=None,                   # InputFile or BinaryIO for upload
    caption=None,                # caption text
    reply_msg_id=None,           # reply to message
    forward_chat_id=None,        # forward from chat
    forward_msg_id=None,         # forward message ID
    inline_keyboard_markup=None, # inline keyboard
    parse_mode=...,              # "HTML" / "MarkdownV2" / None
    format_=None,                # offset/length formatting
    parent_topic=None,           # send in thread
    request_id=None,             # idempotency key
)
```

### edit_text Parameters

```python
await bot.edit_text(
    chat_id="user@company.ru",  # target chat ID
    msg_id="message_id",         # message to edit
    text="Updated text",         # new message text
    inline_keyboard_markup=None, # inline keyboard
    parse_mode=...,              # "HTML" / "MarkdownV2" / None
    format_=None,                # offset/length formatting
)
```

### Proxy & Rate Limiting

```python
# Corporate proxy (only affects Bot API requests)
bot = Bot(
    token="TOKEN",
    api_url="https://myteam.mail.ru/bot/v1",
    proxy="http://proxy-server:8535",
    verify_ssl=False,          # self-signed certs on on-premise
)

# Rate limiting: max 5 requests/sec (token-bucket)
bot = Bot(token="TOKEN", api_url="...", rate_limit=5)

# Auto-retry on 5xx errors (default: 3 retries with exponential backoff)
bot = Bot(token="TOKEN", api_url="...", retry_on_5xx=3)  # None or 0 = no retry
```

---"""


def section_dispatcher(observers: list[dict[str, str]]) -> str:
    decorator_lines = []
    for obs in observers:
        name = obs["name"]
        desc = obs["description"]
        # Add example filter for message
        if name == "message":
            decorator_lines.append(f"@router.{name}()                    # {desc}")
            decorator_lines.append(f'@router.{name}(Command("start"))    # /start command')
            decorator_lines.append(f"@router.{name}(F.text)              # messages with text")
        else:
            decorator_lines.append(f"@router.{name}(){' ' * max(1, 25 - len(name))}# {desc}")
    decorators = "\n".join(decorator_lines)

    return f"""\

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

{decorators}
```

---"""


FILTERS = """\

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
@router.message(Command(re.compile(r"cmd_\\d+")))  # regex
@router.message(Command("menu", prefix=("!", "/")))  # !menu or /menu
@router.message(Command())                     # any command

# Access parsed command in handler:
@router.message(Command("greet"))
async def greet(message: Message, command: CommandObject):
    name = command.args or "World"    # /greet John → args="John"
    await message.answer(f"Hello, {name}!")
```

### CommandObject Fields

```python
command.prefix   # str — "/" (or custom prefix)
command.command   # str — command name without prefix ("start")
command.args     # str — everything after the command ("arg1 arg2")
command.raw_text # str — original full text ("/start arg1 arg2")
command.match    # re.Match | None — regex match (when using regex commands)
```

### Other Filters

```python
# Chat type
@router.message(ChatTypeFilter("private"))     # DM only
@router.message(ChatTypeFilter("group"))       # group only

# FSM state
@router.message(StateFilter(Form.waiting_name))

# Regex
@router.message(RegexpFilter(r"\\d{4}-\\d{2}-\\d{2}"))  # date pattern

# Callback data (exact or regex)
@router.callback_query(CallbackData("confirm"))
@router.callback_query(CallbackData(re.compile(r"^action_\\d+$")))

# Reply / Forward
@router.message(ReplyFilter())     # message is a reply
@router.message(ForwardFilter())   # message is forwarded

# Combine filters
@router.message(Command("start"), ChatTypeFilter("private"))  # AND
@router.message(Command("a") | Command("b"))                  # OR
@router.message(~Command("start"))                             # NOT
```

### Custom Filters

```python
from vkworkspace.filters.base import BaseFilter

class AdminFilter(BaseFilter):
    def __init__(self, admin_ids: list[str]):
        self.admin_ids = admin_ids

    async def __call__(self, event, **kwargs) -> bool:
        user = getattr(event, "from_user", None)
        if user is None:
            return False
        return user.user_id in self.admin_ids

# Usage
admins = AdminFilter(["admin@corp.ru", "boss@corp.ru"])
@router.message(Command("ban"), admins)
async def cmd_ban(message: Message):
    await message.answer("User banned.")

# Return dict to inject kwargs into handler
class ExtractEmail(BaseFilter):
    async def __call__(self, event, **kwargs) -> bool | dict:
        text = getattr(event, "text", None) or ""
        import re
        m = re.search(r"[\\w.+-]+@[\\w-]+\\.[\\w.]+", text)
        if not m:
            return False
        return {"email": m.group(0)}  # injected as handler kwarg

@router.message(ExtractEmail())
async def on_email(message: Message, email: str):  # `email` auto-injected
    await message.answer(f"Got email: {email}")
```

---"""


MESSAGE_OBJECT = """\

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

---"""


CALLBACK_QUERY = """\

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

---"""


KEYBOARDS = """\

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

---"""


CALLBACK_DATA_FACTORY = """\

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

---"""


PAGINATOR = """\

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

---"""


FSM = """\

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

---"""


MIDDLEWARE = """\

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

### Dispatcher-Level Middleware

```python
# Applies to ALL routers included in dp
dp.message.middleware.register(LoggingMiddleware())
dp.callback_query.middleware.register(LoggingMiddleware())
```

---"""


TYPING_ACTIONS = """\

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

---"""


TEXT_FORMATTING = """\

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
    Bold("Welcome"), ", ", Italic("user"), "!\\n",
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

---"""


FILE_HANDLING = """\

## File Handling

```python
from vkworkspace.types import InputFile

# Upload from disk
await bot.send_file(chat_id, file=InputFile("report.pdf"))
await bot.send_file(chat_id, file=InputFile(Path("/tmp/photo.jpg")))

# From bytes
await bot.send_file(chat_id, file=InputFile(b"\\x89PNG...", filename="image.png"))

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

---"""


ERROR_HANDLING = """\

## Error Handling & Lifecycle

### Unhandled Exceptions

```python
@router.error()
async def on_error(error: Exception, bot, raw_event, **kwargs):
    logging.exception("Unhandled error: %s", error)
    await bot.send_text("admin@corp.ru", f"Bot error: {type(error).__name__}")
```

### Lifecycle Hooks

```python
@dp.on_startup
async def setup():
    # Runs once before polling starts
    global db_pool
    db_pool = await create_pool(DSN)
    scheduler.start(bot, db=db_pool)

@dp.on_shutdown
async def cleanup():
    # Runs on SIGINT/SIGTERM (Ctrl+C)
    await scheduler.stop()
    await db_pool.close()
```

### Graceful Shutdown

```python
async def main():
    bot = Bot(token="TOKEN", api_url="https://myteam.mail.ru/bot/v1")
    dp = Dispatcher()
    dp.include_router(router)
    # Blocks until Ctrl+C; on_shutdown hooks run automatically
    await dp.start_polling(bot)

asyncio.run(main())
```

### Edited Messages as Regular Messages

```python
dp = Dispatcher(handle_edited_as_message=True)
# edited_message events now routed to @router.message() handlers
```

---"""


THREADS = """\

## Threads

```python
# Create a thread under a message
thread = await bot.threads_add(chat_id, msg_id, title="Discussion")

# Send message inside a thread
await bot.send_text(chat_id, "In thread", parent_topic=parent_msg)

# Reply inside a thread (auto-propagates parent_topic)
await message.answer_thread("Starting a thread here!")

# Check if message is from a thread
if message.is_thread_message:
    topic = message.parent_topic  # ParentMessage(chat_id, message_id, type)
    await message.answer("Replying inside the thread")

# Thread subscribers
subs = await bot.threads_get_subscribers(chat_id, thread_msg_id)
# subs.subscribers → list[Subscriber]

# Auto-subscribe new members to a thread
await bot.threads_autosubscribe(chat_id, thread_msg_id, enable=True)
```

---"""


BOT_SERVER = """\

## BotServer — HTTP Service for Non-Python Integrations

**Not a webhook receiver.** BotServer exposes HTTP endpoints so that
external systems (PHP, Go, N8N, Grafana, Zabbix — any language) can
call the bot via simple HTTP requests. For Python apps, use `Bot` directly.

```python
from vkworkspace import BotServer, Bot

server = BotServer(
    token="TOKEN",
    api_url="https://myteam.mail.ru/bot/v1",
    port=8080,
    # api_key="secret",       # require X-Api-Key header
    # proxy="http://proxy:8535",
)

# HTTP endpoint: POST /send {"email": "...", "text": "..."}
@server.route("/send")
async def send(bot: Bot, data: dict):
    await bot.send_text(data["email"], data["text"])

# GET endpoint
@server.route("/status", methods=["GET"])
async def status(bot: Bot, data: dict):
    return {"ok": True, "bot": (await bot.get_me()).nick}

server.run()  # blocking; or `await server.start()` for async
```

### HTTP + VK Teams Polling in One Process

```python
from vkworkspace import BotServer, Router, F
from vkworkspace.filters import Command
from vkworkspace.types import Message

server = BotServer(token="TOKEN", api_url="...")
router = Router()

@server.route("/notify")
async def notify(bot, data):
    await bot.send_text(data["email"], data["text"])

@router.message(Command("start"))
async def start(message: Message):
    await message.answer("Hello!")

server.include_router(router)  # enables polling alongside HTTP
server.run()  # runs both HTTP server and VK Teams polling
```

### Built-in Features

- `GET /health` — health check (returns routes list and polling status)
- `api_key="secret"` — require `X-Api-Key` header on all requests
- POST handlers receive parsed JSON body, GET handlers receive query params
- Return a dict from handler → sent as JSON response; return None → `{"ok": true}`

### For Python Apps (no BotServer needed)

```python
# Standalone — just use Bot directly
from vkworkspace import Bot
bot = Bot(token="TOKEN", api_url="https://myteam.mail.ru/bot/v1")
await bot.send_text("user@corp.ru", "Hello!")

# Background polling in async app (FastAPI, Quart)
import asyncio
from vkworkspace import Bot, Dispatcher
bot = Bot(token="TOKEN", api_url="...")
dp = Dispatcher()
dp.include_router(router)
asyncio.create_task(dp.start_polling(bot))  # runs in background
```

---"""


SCHEDULER = """\

## Scheduler — Periodic Tasks

Zero dependencies, pure asyncio. No APScheduler needed.

```python
from vkworkspace import Scheduler

scheduler = Scheduler()

@scheduler.interval(seconds=300)
async def check_cpu(bot):
    cpu = await get_cpu_usage()
    if cpu > 90:
        await bot.send_text(ONCALL_CHAT, f"CPU: {cpu}%")

@scheduler.daily(hour=9, minute=0)
async def morning_report(bot):
    await bot.send_text(TEAM_CHAT, build_report())

@scheduler.weekly(weekday=4, hour=18)  # Friday 18:00
async def weekly_summary(bot):
    await bot.send_text(TEAM_CHAT, build_weekly())

# Start in on_startup hook
@dp.on_startup
async def setup():
    scheduler.start(bot, db=oracle_pool, config=app_config)
    # Jobs receive only kwargs matching their signature:
    # check_cpu(bot) gets bot only
    # A job with def report(bot, db): gets bot + db

@dp.on_shutdown
async def teardown():
    await scheduler.stop()
```

### Decorator Options

```python
@scheduler.interval(seconds=60)           # every 60s, runs immediately
@scheduler.interval(seconds=60, run_at_start=False)  # waits 60s first
@scheduler.daily(hour=9, minute=30)       # daily at 09:30 (local time)
@scheduler.weekly(weekday=0, hour=8)      # Monday 08:00
```

### DI — Extra Dependencies

```python
# scheduler.start() accepts **kwargs — injected by parameter name
scheduler.start(bot, db=pool, config=cfg)

@scheduler.interval(seconds=300)
async def job(bot, db):        # gets bot + db (config filtered out)
    ...

@scheduler.interval(seconds=300)
async def job(bot, **kwargs):  # gets bot + all extras (db, config)
    ...
```

---"""


REDIS_LISTENER = """\

## RedisListener — Consume Tasks from Redis

Listen for tasks via Redis Streams. For non-Python producers that push
jobs into Redis for the bot to process.

```python
from vkworkspace import RedisListener, Router, F
from vkworkspace.filters import Command
from vkworkspace.types import Message

router = Router()
listener = RedisListener(
    redis_url="redis://localhost:6379",
    stream="bot:tasks",             # Redis Stream key
    group="bot-workers",            # consumer group
    consumer="worker-1",            # consumer name
)

@listener.on_task("send_message")
async def handle_send(bot, data: dict):
    await bot.send_text(data["chat_id"], data["text"])

@listener.on_task("send_file")
async def handle_file(bot, data: dict):
    await bot.send_file(data["chat_id"], file_id=data["file_id"])

# Combine with bot handlers
listener.include_router(router)
listener.run(token="TOKEN", api_url="https://myteam.mail.ru/bot/v1")
```

### Producer Side (any language)

```bash
# Add task to Redis Stream
redis-cli XADD bot:tasks '*' type send_message chat_id user@corp.ru text "Hello!"
```

---"""


RUN_SYNC = """\

## run_sync — Blocking Code in Async Handlers

Run synchronous / blocking functions (database queries, pandas, file I/O)
without blocking the event loop. Pure stdlib, zero dependencies.

```python
from vkworkspace.utils.sync import run_sync, sync_to_async

# 1. Wrap any blocking call
@router.message(Command("report"))
async def cmd_report(message: Message):
    df = await run_sync(pd.read_sql, "SELECT * FROM sales", conn)
    await message.answer(f"Rows: {len(df)}")

# 2. Decorator — converts sync function to async
@sync_to_async
def heavy_query(db, month: str) -> list[dict]:
    return db.execute(
        "SELECT * FROM kpi WHERE month = :m", {"m": month}
    ).fetchall()

@router.message(Command("kpi"))
async def cmd_kpi(message: Message, db):
    rows = await heavy_query(db, "2026-01")
    await message.answer(format_kpi(rows))
```

### When to Use

- **cx_Oracle / psycopg2** — synchronous DB drivers
- **pandas** — `read_sql`, `to_excel`, `DataFrame` operations
- **openpyxl / xlsxwriter** — Excel generation
- **subprocess** — calling external commands
- Any function that blocks for >50 ms

---"""


def section_enums(all_enums: dict[str, list[dict[str, str]]]) -> str:
    lines = ["\n## Enums\n\n```python\nfrom vkworkspace.enums import ("]
    lines.extend(f"    {class_name}," for class_name in all_enums)
    lines.append(")\n```\n")

    # Show values for key enums
    show_values = ["ChatAction", "ChatType", "ParseMode", "ButtonStyle", "StyleType"]
    for class_name in show_values:
        members = all_enums.get(class_name, [])
        if members:
            vals = ", ".join(m["name"] for m in members)
            lines.append(f"- **{class_name}**: {vals}")

    lines.append("\n---")
    return "\n".join(lines)


def section_types(types_list: list[str]) -> str:
    # Curated table with key fields (static — changes rarely)
    curated: dict[str, tuple[str, str]] = {
        "Message": (
            "vkworkspace.types",
            "msg_id, text, chat, from_user, parts, format, parent_topic",
        ),
        "CallbackQuery": ("vkworkspace.types", "query_id, callback_data, from_user, message"),
        "Chat": ("vkworkspace.types", "chat_id, type, title"),
        "Contact": ("vkworkspace.types.user", "user_id, first_name, last_name, nick"),
        "ChatInfo": ("vkworkspace.types", "type, title, about, rules, is_public"),
        "InputFile": ("vkworkspace.types", "file, filename; from_url(), from_base64()"),
        "APIResponse": ("vkworkspace.types", "ok, msg_id, file_id"),
        "Part": (
            "vkworkspace.types.message",
            "type, payload; as_mention, as_reply, as_forward, as_file",
        ),
        "FormatSpan": ("vkworkspace.types.message", "offset, length, url"),
        "ParentMessage": ("vkworkspace.types.message", "chat_id, message_id, type"),
    }

    lines = ["\n## Types Reference\n"]
    lines.append("| Type | Module | Key Fields |")
    lines.append("|------|--------|------------|")
    for name, (module, fields) in curated.items():
        lines.append(f"| `{name}` | `{module}` | {fields} |")

    # List any exported types not in the curated table
    extra = [t for t in types_list if t not in curated and t != "VKTeamsObject"]
    if extra:
        lines.append(f"\nOther exported types: {', '.join(f'`{t}`' for t in extra)}")

    lines.append("\n---")
    return "\n".join(lines)


COMPLETE_EXAMPLE = """\

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
            f"Order: {product}\\nConfirm?",
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

---"""


INSTALLATION = """\

## Installation

```bash
pip install vkworkspace                # core
pip install vkworkspace[redis]         # + Redis FSM storage
pip install vkworkspace[voice]         # + audio conversion (PyAV)
pip install vkworkspace[all]           # everything
```"""


def section_key_imports() -> str:
    return """\

## Key Imports

```python
from vkworkspace import Bot, BotServer, Dispatcher, RedisListener, Router, Scheduler, F, BaseMiddleware
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
from vkworkspace.utils.sync import run_sync, sync_to_async
from vkworkspace.utils.scheduler import Scheduler
from vkworkspace.enums import ButtonStyle, ChatAction, ParseMode, ChatType
```"""


# ── Main ──────────────────────────────────────────────────────────────


def generate() -> str:
    """Assemble all sections into the final reference."""
    version = get_version()
    bot_init = extract_bot_init_params()
    bot_methods = extract_bot_methods()
    send_text_params = extract_send_text_params()
    observers = extract_router_observers()
    all_enums = extract_all_enums()
    types_list = extract_types_exports()

    sections = [
        section_header(version),
        QUICK_START,
        section_bot(bot_init, bot_methods, send_text_params),
        section_dispatcher(observers),
        FILTERS,
        MESSAGE_OBJECT,
        CALLBACK_QUERY,
        KEYBOARDS,
        CALLBACK_DATA_FACTORY,
        PAGINATOR,
        FSM,
        MIDDLEWARE,
        TYPING_ACTIONS,
        TEXT_FORMATTING,
        FILE_HANDLING,
        ERROR_HANDLING,
        THREADS,
        BOT_SERVER,
        REDIS_LISTENER,
        SCHEDULER,
        RUN_SYNC,
        section_enums(all_enums),
        section_types(types_list),
        COMPLETE_EXAMPLE,
        INSTALLATION,
        section_key_imports(),
    ]

    return "\n".join(sections) + "\n"


def main() -> None:
    text = generate()
    OUTPUT.write_text(text, encoding="utf-8")
    line_count = text.count("\n")
    print(f"Generated {OUTPUT.name} ({len(text):,} chars, {line_count} lines)")


if __name__ == "__main__":
    main()
