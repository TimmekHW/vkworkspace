# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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

[1.2.2]: https://github.com/TimmekHW/vkworkspace/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/TimmekHW/vkworkspace/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/TimmekHW/vkworkspace/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/TimmekHW/vkworkspace/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/TimmekHW/vkworkspace/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/TimmekHW/vkworkspace/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/TimmekHW/vkworkspace/releases/tag/v0.1.0
