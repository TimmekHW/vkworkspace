# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **`vkworkspace.formatting.from_markdown()` — Markdown (CommonMark + GFM tables / `~~strike~~`) → a text node tree**, for LLM answers. Bold, headings (→ bold), inline code, fenced and indented code blocks, links, images (→ links), lists, quotes, tables (→ a monospace block with aligned columns), horizontal rules and `@[user_id]` mentions. A link that shows its own URL (`<https://…>`, `[url](url)`) goes as plain text — the clients linkify URLs. Raw HTML in the input stays text. Blank lines between blocks follow the source. Needs the new extra: `pip install "vkworkspace[markdown]"` (`markdown-it-py`).
- **Formatting dialects — the rules of one VK Teams server version in a TOML file:** which styles render in MarkdownV2 / HTML (`yes` / `no` / `untested`), mutually exclusive style pairs, escaping (text, code, URLs), the allowed code-block languages, markup templates, plain-text fallbacks, a style to wrap inline code in (`[highlight]`) and `max_length`. A dialect file can `extends` another one and list only what changed. Built-in:
  - `vkteams-25.4` — VK WorkSpace On-Premise 25.4 (`myteam-config.json`: `api-version` 133, clients 25.4.3.78298). Every style checked live in MarkdownV2 and HTML on a 25.4.3p server, seen the same in the 25.4.3 and 26.1 clients: an unescaped `)` ends a MarkdownV2 link URL (escaped now), `&amp;` in an HTML `href` shows `&` in the text (raw `&` is sent). List markup only for one-line items numbered from 1, otherwise `• item` / `1. item` text. Code-block languages `[A-Za-z0-9+]+` (`c++` included), others dropped. Inline code is wrapped in bold (`[highlight] inline_code = "bold"`): the clients draw it almost like body text. Default for `from_markdown`.
  - `vkteams-docs` — everything the Bot API docs describe, as markup. Default for hand-built nodes.
  - `get_dialect(name_or_path)`, `available_dialects()`, `Dialect`, `DialectError`; `VKT_DIALECT` (a name or a `.toml` path) sets the dialect for the whole process.
- Text builder: every render method takes `dialect=` (`as_markdown`, `as_html`, `as_kwargs`); `Text(..., dialect=...)` binds a subtree (the outermost binding wins, a render-time `dialect=` beats all). A style the dialect does not render becomes its plain-text fallback: `text (url)`, `• item`, `│ quote`, `~strike~`.
- **`vkworkspace.formatting.from_html()` — HTML (the way bots and LLMs write it for VK Teams) → the same node tree.** Supported tags become nodes (`<strong>`/`<em>`/`<ins>`/`<del>` aliases included), `<br>` a line break, `<p>` / `<div>` / headings (→ bold) start a line, tables a monospace block, unknown tags keep their text; GFM code typed into the text (`` `x` ``, ```` ```block``` ````) becomes code and `@[user_id]` a mention, outside `<code>` / `<pre>`. Entities are decoded; a `<` that does not open a known tag stays text (the stdlib parser would drop `a<b` silently). Unclosed tags are closed, stray closing tags dropped. Standard library only.
- `node.as_plain()` — plain text without markup or escaping, for `parse_mode=None` (the retry after a «Format error»).
- `node.split(parse_mode, max_length=None)` — parts that each render within the limit, cut between blocks and lines, never inside markup: a long code block becomes several blocks, a long list several lists (numbering continues), a long bold run several bold runs. Length in UTF-16 code units of the rendered text; the default limit comes from the dialect (4096).
- `OrderedList(*items, start=1)` / `UnorderedList(*items)` nodes.

### Changed
- `Pre` inside `Quote`, a list or an inline style (the docs list `pre` as exclusive with every other style; `<pre>` inside `<blockquote>` is a «Format error» on a live server) now renders each line as inline code instead of a block. Lists inside a quote render as text lines. Other default output of the text builder is unchanged.
- A style nested in itself (a heading containing `**bold**` → `Bold` inside `Bold`, bold inside bold, a quote inside a quote) no longer emits the wrapper twice: `<b><b>…</b></b>` is a «Format error» on a live server. The inner node renders its content without re-applying the style (verified live on 25.4.3p / cloud).
- `Mention` nested in `Code` / `Pre` contributes `@[user_id]` (was an empty string).

## [1.12.1] - 2026-10-30

### Fixed
- **MarkdownV2 inline code / pre:** `Code(...)`, `Pre(...)`, `md.code()` and `md.pre()` now escape special characters inside the content. VK Teams applies its rule «every special character that is not a style marker must be backslash-escaped» inside code too: before this fix `` Code("get_user()") `` or `` Code("a-b") `` was rejected with «Format error», a backtick in the content terminated the span, and a lone backslash was consumed (`` Code("C:\logs") `` showed `C:logs`).
- `Code(...)` / `Pre(...)` with nested nodes rendered the nested node as **HTML inside MarkdownV2** (`` `<b>x</b>` ``). Nested nodes now contribute plain text (code cannot contain other styles).

### Docs
- Text builder: a backtick typed inside a plain string is **literal text** (it is escaped) — monospace is the `Code(...)` / `Pre(...)` node. `str(node)` / f-strings render HTML; use `as_markdown()` / `as_kwargs("MarkdownV2")` for MD.
- Tests for the text builder's MarkdownV2 / HTML rendering (`tests/test_text_builder.py`) — there were none.

## [1.12.0] - 2026-10-15

### Added
- **`mincifry` — one switch to trust the Минцифры root CA (Russian Trusted Root CA).** `Bot(mincifry=True)`, `verify_ssl="mincifry"`, or the `VKT_MINCIFRY=1` environment variable. The root certificate ships inside the package (`vkworkspace/certs/`) and is loaded **on top of** the defaults. Same switch on `InputFile.from_url(mincifry=...)` and `create_session(mincifry=...)`.
- `vkworkspace.client.ssl_utils.MINCIFRY_DEFAULT` — build-time default for the switch (off in the public package).
- `make_ssl_context()` options `system_store`, `certifi_bundle`, `mincifry`; `default_ssl_context()`, `vendored_ca_pem()`.

### Changed
- **`verify_ssl=True` now trusts the OS trust store *and* the `certifi` bundle.** Plain httpx uses certifi only, so a CA installed into Windows, Linux (`/etc/pki/ca-trust`, `ca-certificates`) or a Docker image was silently ignored — that is why servers kept failing with `CERTIFICATE_VERIFY_FAILED` after "installing the certificate". `SSL_CERT_FILE` / `SSL_CERT_DIR` are honoured. Every httpx client the library creates (`Bot`, `InputFile.from_url`, `create_session`) uses this trust.
- `SSLVerificationError` text now says exactly how to enable Минцифры trust when it is off, and what else to check when it is on (private CA, missing Sub CA, intercepting proxy).

## [1.11.0] - 2026-10-15

### Added
- **User resolving: `user_id` ⇄ name ⇄ mention.**
  - `bot.get_user(user_id_or_nick)` → `UserInfo` (`full_name`, `mention`, `first_name`, `last_name`, `nick`, `is_bot`, `uin`) via `chats/getInfo`. Results are cached for the bot's lifetime (`cache=False` to bypass, `bot.clear_user_cache()` to reset).
  - `bot.get_user_name(user_id_or_nick)` → `"Имя Фамилия"`.
  - Nick lookup yields `user_id` = numeric `uin` parsed from the avatar URL (`targetSn=…`, the ID VK Teams uses for bots).
- **`full_name` / `mention` / `mention_md` properties** on every user-like object: `User`, `Contact` (`message.from_user`), `ChatMember`, `BotInfo`, `ChatInfo`, `MentionPayload`. `mention` renders `@[user_id]`, `mention_md` the MarkdownV2-escaped form.
- **`message.mentioned_user_ids`** — IDs of everyone @mentioned in a message (mention → `user_id`).
- **`VKT_PROXY` environment variable** — used as the Bot API proxy when `Bot(proxy=...)` is not given.

### Fixed
- `ChatInfo.photos` now reads the API's actual `photo` key (the old `photos` spelling is still accepted). Before this fix the avatar list was always empty on real responses.

## [1.10.0] - 2026-09-25

### Added
- **aiogram‑style download straight off the `Message`:** `message.download(dest=None)`, `message.download_all(dir)`, `message.files[0].download(...)`, `message.attachments`, and `Bot.download(file_or_id, dest=None)`. This is the convenient path for grabbing files a user sent. `dest=None` → `bytes`; a directory → save under the server filename and return the `Path`.
- **`Bot.download_file(file_id, destination=None)`** and **`Bot.download_file_by_url(url, ...)`** — lower‑level file download. Resolves the URL via `files/getInfo` and streams the file from the VK Teams file host. `destination=None` returns `bytes`; a directory saves under the server filename and returns the `Path`; a file path saves there. Retries on 5xx.
  - **Fixes the "download returns HTTP 500" bug.** The signed download URL's `token` query parameter contains a `:` (on‑prem tokens look like `001.123.456:789`). Passing it through `httpx`/`requests` `params=` percent‑encodes `:` → `%3A`, which the file host rejects with **500**. The new methods append the token to the URL *string*, so it is sent verbatim (like `curl`).
- **Минцифры / private‑CA TLS support.** `verify_ssl` now also accepts a **PEM bundle path** (`str`/`Path`) or a ready **`ssl.SSLContext`**, in addition to `bool`. New helper `vkworkspace.make_ssl_context(cafile=..., use_truststore=..., verify=...)` builds a context that trusts the Минцифры chain (from a file or the OS store via the optional `truststore` package — `pip install "vkworkspace[ssl]"`). The certificate is **not** vendored into the package.
- **Friendly SSL errors (in Russian).** A TLS verification failure now raises `SSLVerificationError` with a copy‑paste remedy **на русском** pointing at the Минцифры cert, instead of a bare `httpx.ConnectError` (the library's users are in RU/CIS).
- New exceptions: `SSLVerificationError`, `FileDownloadError`. New optional extra: `vkworkspace[ssl]` (`truststore`).

### Notes
- `File.filename` stays **optional** (the server does not always send it); `download_file` derives the name from `File.filename` → the URL basename → the `file_id`, so a downloaded file always has a name.

## [1.9.0] - 2026-04-26

### Added
- **`Bot.create_chat()`** — `chats/createChat` endpoint (myteam / on-premise only). Creates a new chat with title, description, rules, initial members, public/private flag, join moderation and default role. Includes explicit warning in docstring: may be disabled by the operator on a given installation, cloud myteam.mail.ru bots cannot create chats. Brings vkworkspace to **100% Bot API parity** with the official Mail.ru `bot-python` library.
- **10 new named filter classes** in `vkworkspace.filters`:
  - `FileFilter`, `ImageFilter`, `VideoFilter`, `AudioFilter`, `VoiceFilter` — match messages by attachment kind
  - `StickerFilter` — match sticker messages
  - `MentionFilter(user_id=None)` — match any `@mention` or a specific user
  - `SenderFilter(user_id)` — match by `from_user.user_id` (single ID or list)
  - `URLFilter` — detect `http(s)://` / `www.` links in `text`, captured into handler kwargs as `url`
  - `CallbackDataRegexpFilter(pattern)` — regex match on `callback_data`, captures `re.Match` into handler kwargs as `regexp_match`
- New example: `examples/features/filters.py` — demonstrates all built-in filters and composition.
- Documentation updates: `README.md`, `README_RU.md`, `examples/README.md`, and `llm_full.md` (regenerated via `scripts/gen_llm_ref.py`) all describe the new filters and `create_chat`.

## [1.8.9] - 2026-03-05

### Improved
- After all retry attempts exhausted on `"Server error"`, an **ERROR**-level log is now emitted with method name, attempt count, error description, and request params (token excluded) — makes debugging server-side failures much easier

## [1.8.8] - 2026-03-04

### Fixed
- `_request()` now retries on VK Teams `"Server error"` responses (HTTP 200 + `ok: false`) with the same exponential backoff as 5xx errors — applies to **all** API methods

## [1.8.7] - 2026-03-03

### Added
- `FormatBuilder.validate()` — checks for mutually exclusive style overlaps per VK Teams API rules (e.g. `pre` + `bold`, `link` + `mention`, `orderedList` + `unorderedList`)
- `FormatBuilder.build()` now auto-validates before returning; raises `ValueError` on conflicts
- Tests for `FormatBuilder` (20 test cases)

## [1.8.6] - 2026-02-28

### Added
- `vkworkspace.enable_debug()` — one-liner to enable DEBUG logging for all framework components (adds StreamHandler + sets level)
- `NullHandler` on the `vkworkspace` root logger (PEP best practice for libraries)
- `### Debug Logging` section in README

## [1.8.5] - 2026-02-27

### Fixed
- **Ctrl+C on Linux**: polling tasks are now cancelled immediately on SIGINT/SIGTERM instead of waiting up to 60s for the long-poll to return
- `Dispatcher.stop()` also cancels polling tasks (was only setting `_running = False`)

### Added
- DEBUG logging in `Bot._request()`: logs every API call with endpoint, HTTP status, and elapsed time (`→ send_text` / `← send_text 200 (0.142s)`)
- DEBUG logging in `Dispatcher.feed_update()`: logs event type and sender on every incoming update

## [1.8.4] - 2026-02-20

### Added
- `Part.as_inline_keyboard` — reads keyboard markup from parts (VK Teams echoes the full keyboard back in `callbackQuery` events)
- `Message.inline_keyboard` — shortcut to current keyboard on the message without storing it separately
- `llm_full.md` / `gen_llm_ref.py`: "VK Teams API Quirks" section — verified API behaviours from live event logging (keyboard echo, URL buttons fire no events, `from_user` in callback is the bot, ghost-delete in private chats, thread architecture, channel comments)

## [1.8.3] - 2026-02-20

### Added
- `Message.caption` — caption from file attachment (VK Teams hides it in `parts`, this property normalises it)
- `Message.content` — `text or caption`, universal getter for handlers that deal with both text and file-with-caption
- `Message.is_edited` — `True` when `editedTimestamp` is set; docstring covers VK Teams ghost-delete quirk in private chats
- `Message.sticker` — typed sticker attachment from `parts`
- `Message.voice` — typed voice attachment from `parts`
- `Message.thread_root_chat_id` — original chat ID for thread/comment messages
- `Message.thread_root_message_id` — root message ID (int) for thread/comment messages
- `Message.is_thread_message` — expanded docstring: channel comments are thread messages
- `ReplyMessagePayload.format` — captures formatting of quoted messages
- `Thread.ok` field; `thread_id` default `""` instead of required

### Changed
- `RateLimiter` upgraded from min-interval to **token-bucket** (`burst=5`) — allows short bursts before throttling
- Long-poll reconnects on HTTP 404 in addition to 5xx
- `llm_full.md`: new `Message` properties documented, token-bucket rate limiter description updated
- `README.md` / `README_RU.md`: added Threads section with thread chat ID explanation and channel comments note

## [1.8.2] - 2026-02-20

### Fixed
- `message.answer()` / `reply()` / `answer_thread()` / `answer_file()` / `answer_voice()`: use `model_construct()` instead of `Message(msg_id=...)` — fixes pyright `reportCallIssue` (alias `msgId` vs field name `msg_id`)

## [1.8.1] - 2026-02-20

### Added
- `message.answer()`, `reply()`, `answer_thread()`, `answer_file()`, `answer_voice()` now return a bound `Message` instead of `Any` — enables chaining `.delete()`, `.edit_text()` on the sent message directly
- `examples/echo_bot.py`: added `/vanish` command demonstrating `sent = await message.answer(...); await sent.delete()`

### Changed
- `PRESENTATION.md` added to `.gitignore` — kept out of public repository

## [1.8.0] - 2026-02-18

### Fixed
- **CWE-209**: `BotServer` HTTP 500 response no longer leaks exception details — was `str(exc)`, now generic `"internal server error"`
- `Scheduler.stop()` is now `async` — properly awaits task cancellation with `asyncio.gather` instead of sync cancel
- Double `Scheduler.start()` calls are safely ignored with a warning (was silently duplicating tasks)
- `await scheduler.stop()` in chatops and report examples (was sync call on async method)

### Added
- `Scheduler` exported from root package: `from vkworkspace import Scheduler`
- `Scheduler` exported from `vkworkspace.utils`: `from vkworkspace.utils import Scheduler`
- 14 tests for Scheduler (`test_scheduler.py`): time calculations, lifecycle, DI injection, exception resilience
- `examples/README.md` — learning path, feature/integration tables with links
- `SOLAR_REVIEW.md` — security review of SOLAR appScreener SAST report (15 false positives documented)
- `gen_llm_ref.py`: Scheduler and RedisListener documentation sections
- `llm_full.md` regenerated (884 → 1177 lines) — added Error Handling & Lifecycle, Threads, run_sync, Custom Filters, Proxy & Rate Limiting sections

### Changed
- Examples reorganized into `examples/features/` (10 files) and `examples/integrations/` (6 files) with `echo_bot.py` at root
- Moved `api_capabilities_test.py` and `diagnostic_bot.py` to `scripts/`
- Fixed all ruff errors in examples: unused `noqa` directives, f-strings without placeholders, unsorted imports, `E402` suppressed for intentional late imports

## [1.7.0] - 2026-02-18

### Added
- `BotServer` — HTTP server for running bots as HTTP services: `@server.route()` decorator, GET/POST, JSON parsing, `X-Api-Key` auth, built-in `/health` endpoint
- `BotServer.include_router()` — run HTTP server + VK Teams long-polling in a single process via `asyncio.gather`
- `BotServer.run()` / `BotServer.start()` — blocking and async entry points
- `BotServer` exported from root package: `from vkworkspace import BotServer`
- `server_with_bot.py` example — HTTP routes + FSM incident-bot in one process
- `scripts/gen_llm_ref.py` — auto-generates `llm_full.md` from source (AST-parsed Bot methods, enums, types, router observers)
- `llm_full.md` mention in README and README_RU

## [1.6.0] - 2026-02-18

### Added
- `CallbackDataFactory` — structured, typed callback data (aiogram-style): define fields once, `pack()`/`unpack()` automatically, `filter()` with magic-filter support
- `Paginator` — keyboard pagination helper with `◀`/`▶` navigation, `page_data`, `has_prev`/`has_next`, `add_nav_row()` for InlineKeyboardBuilder
- `PaginationCB` — ready-made callback data for paginator buttons
- `ChatActionSender` — async context manager that sends typing/looking action periodically while a block runs
- `@typing_action` decorator — wraps a handler to show "Bot is typing..." automatically (supports `action=` and `interval=` parameters)
- `Message.typing()` — shortcut returning `ChatActionSender` context manager
- `Message.answer_chat_action()` — one-shot action send (like aiogram's `answer_chat_action`)
- `ButtonStyle.BASE` enum value
- `typing_action_bot.py` example — demonstrates decorator, context manager, and one-shot approaches
- 18 new tests for typing actions (`test_typing_action.py`)
- PyPI download badges in README and README_RU

## [1.5.0] - 2026-02-18

### Added
- `InputFile.from_url()` — async download from URL with auto-detected filename and `max_size` protection (default 50 MB)
- `InputFile.from_base64()` — create InputFile from base64-encoded string
- `vkworkspace.utils.voice` module — `convert_to_ogg_opus()` for audio-to-OGG/Opus conversion (MP3, WAV, FLAC, etc.)
- `voice` optional dependency (`pip install vkworkspace[voice]`) — PyAV for audio conversion
- Comprehensive docstrings with Args, Returns, Raises, Examples across all public API: Bot, Dispatcher, Router, FSMContext, Message, CallbackQuery, InputFile, InlineKeyboardBuilder, FormatBuilder, all types and enums
- Exponential backoff in polling loop (2s → 4s → 8s → … → 60s max) with auto-reconnect and connection restored logging
- Full traceback (`exc_info=True`) on first polling error for easier debugging
- New tests: `test_input_file.py` (17 tests), `test_voice.py` (7 tests)

## [1.4.1] - 2026-02-17

### Fixed
- ReDoS mitigation: regex filters now limit input text to 8192 chars (`RegexpFilter`, `RegexpPartsFilter`)
- Path traversal mitigation: `InputFile.read()` resolves path via `.resolve()` and validates `.is_file()` before opening
- Admin check in `multi_router_bot.py` moved to router-level `AdminFilter` (was inline in handler)
- Added `assert message.text is not None` in examples for type safety with `F.text` filter

### Added
- Table of contents in README and README_RU

## [1.4.0] - 2026-02-17

### Added
- `retry_on_5xx` parameter in `Bot()` — automatic retry with exponential backoff on 5xx errors (default: 3 retries)
- `verify_ssl` parameter in `Bot()` — disable SSL verification for self-signed certificates
- `session_timeout` parameter in `Dispatcher()` and `FSMContextMiddleware` — auto-clear expired FSM sessions
- `ReplyFilter`, `ForwardFilter`, `RegexpPartsFilter` — new filters for reply/forward/regex-in-parts matching
- `FormatBuilder` — programmatic builder for offset/length text formatting (`format_=` parameter)
- FSM session timeout tests (`tests/test_fsm_timeout.py`)
- 504 Gateway Timeout handling in `get_events()` — silent reconnect instead of traceback

### Changed
- Ruff rules expanded: added `C901` (cyclomatic complexity ≤ 12), `PERF`, `RUF`
- Replaced mypy with pyright for stricter type checking
- All CI workflows now use `uv` (astral-sh/setup-uv) for faster dependency installation
- Release workflow builds with `uvx --from build` instead of pip

## [1.3.0] - 2026-02-17

### Added
- Thread support: `parent_topic` parameter in `send_text()`, `send_file()`, `send_voice()` for sending messages inside threads
- `Message.answer_thread()` — create a thread under a message or reply in existing thread
- `Message.answer()` auto-propagates `parent_topic` when replying inside threads
- `Message.is_thread_message` property
- `ParentMessage` model for thread parent references
- `Bot.send_text_with_deeplink()` — send text with deeplink for mini-app / bot-start scenarios
- `Bot.add_chat_members()` — add members to chat (`chats/members/add`)
- `reply_msg_id` and `forward_msg_id` now accept `list[str]` for multi-reply/forward
- `request_id` parameter (idempotency key) in `send_text()`, `send_file()`, `send_voice()`
- Typed message parts: `MentionPayload`, `ReplyPayload`, `ForwardPayload`, `FilePayload` with `Part.as_mention`, `as_reply`, `as_forward`, `as_file` accessors
- Convenience properties on `Message`: `mentions`, `reply_to`, `forwards`, `files`
- `FormatSpan` and `MessageFormat` — typed model for `format` field (offset/length text formatting)
- Typed chat member events: `NewChatMembersEvent`, `LeftChatMembersEvent`, `ChangedChatInfoEvent` (replacing generic `VKTeamsObject`)
- `ChatInfo.phone` and `ChatInfo.photos` fields
- 93 unit tests (`tests/test_bot_api.py`) covering all Bot API methods
- Live API test suite (`tests/test_bot_live.py`) for end-to-end verification
- mypy type checker added to CI (Lint workflow: ruff + mypy)
- Testing section in README with usage instructions

### Fixed
- Resolved all 15 mypy type errors across the codebase (strict type safety)

## [1.2.2] - 2026-02-17

### Fixed
- Graceful shutdown on Windows — handle `asyncio.CancelledError` in polling loop to avoid traceback on Ctrl+C

## [1.2.1] - 2026-02-17

### Improved
- Explicit `ParseMode | str | None` type hints in `Bot.send_text()`, `Bot.edit_text()`, `Bot.send_file()` and `Bot.__init__(parse_mode=...)`
- `Message.answer()`, `reply()`, `edit_text()`, `answer_file()`, `answer_voice()` now expose `parse_mode` and `inline_keyboard_markup` as named parameters (IDE autocomplete)

## [1.2.0] - 2026-02-16

### Added
- Text formatting string helpers: `md` (MarkdownV2) and `html` with `escape`, `bold`, `italic`, `underline`, `strikethrough`, `code`, `pre`, `link`, `quote`, `mention` methods
- Text builder (aiogram-style composable nodes): `Text`, `Bold`, `Italic`, `Underline`, `Strikethrough`, `Code`, `Pre`, `Link`, `Mention`, `Quote`, `Raw` with auto-escaping and `as_kwargs()` for automatic `parse_mode`
- `html.ordered_list()` and `html.unordered_list()` for HTML list formatting
- `split_text()` utility to split long messages into chunks (default 4096 chars), splitting on newlines/spaces
- `Bot(parse_mode=...)` — default parse mode applied to all `send_text`, `edit_text`, `send_file` calls (aiogram-style). Use `parse_mode=None` per-call to override
- `Bot.set_chat_avatar()` method (`chats/avatar/set`)
- Warning log when `send_text` / `edit_text` receive text longer than 4096 chars
- Example: `formatting_bot.py` — demonstrates string helpers, text builder, and split_text

### Changed
- `Message.answer()` now accepts `**kwargs` and forwards them to `Bot.send_text()` — automatically supports new parameters without signature changes

### Fixed
- Fixed `Bot._request()` to use POST with `data=` instead of GET with `params=` — fixes multipart form data (file uploads) and aligns with VK Teams API spec

## [1.1.0] - 2026-02-16

### Fixed
- Fixed middleware chain not passing kwargs to handlers with custom DI parameters (e.g. `api`, `db`), causing `missing required positional argument` errors
- Middleware now wraps the full handler chain including sub-routers, ensuring correct kwargs propagation

## [1.0.1] - 2025-02-14

### Fixed
- Fixed relative links in READMEs breaking on PyPI (now absolute GitHub URLs)
- Fixed tests workflow failing when no tests exist (exit code 5)

## [1.0.0] - 2025-02-14

### Changed
- Upgraded development status from Beta to Production/Stable
- Migrated CI linter from pylint to ruff (faster, already configured)
- Modernized type hints: `Optional[X]` replaced with `X | None` across the codebase
- Improved code quality (replaced `hasattr(__call__)` with `callable()`, added `contextlib.suppress`, etc.)

### Added
- GitHub Actions workflow for automated releases and PyPI publishing (Trusted Publishing)
- GitHub Actions workflow for running tests (pytest, Python 3.11-3.14)

## [0.1.0] - 2025-02-12

### Added
- Fully async VK Teams (VK Workspace) bot framework
- `Bot` client with httpx-based async HTTP session
- `Dispatcher` and `Router` for event handling (inspired by aiogram 3)
- Pydantic v2 models for all API types (Message, CallbackQuery, Chat, User, etc.)
- Filter system: `Command`, `StateFilter`, `ChatTypeFilter`, `RegexpFilter`, `CallbackData`
- `magic-filter` integration (`F` object)
- Finite State Machine (FSM) with `MemoryStorage` and `RedisStorage` backends
- Middleware pipeline (error handling, user context, FSM context)
- Inline keyboard builder utility
- 10 example bots (echo, keyboard, FSM, middleware, proxy, diagnostic, API tester, etc.)

[1.8.0]: https://github.com/TimmekHW/vkworkspace/compare/v1.7.0...v1.8.0
[1.7.0]: https://github.com/TimmekHW/vkworkspace/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/TimmekHW/vkworkspace/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/TimmekHW/vkworkspace/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/TimmekHW/vkworkspace/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/TimmekHW/vkworkspace/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/TimmekHW/vkworkspace/compare/v1.2.2...v1.3.0
[1.2.2]: https://github.com/TimmekHW/vkworkspace/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/TimmekHW/vkworkspace/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/TimmekHW/vkworkspace/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/TimmekHW/vkworkspace/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/TimmekHW/vkworkspace/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/TimmekHW/vkworkspace/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/TimmekHW/vkworkspace/releases/tag/v0.1.0
