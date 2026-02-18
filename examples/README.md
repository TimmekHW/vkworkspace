# Examples

## Quick Start

```bash
python examples/echo_bot.py
```

[echo_bot.py](echo_bot.py) — minimal bot in 15 lines. Start here.

## Features

"How do I add keyboards / FSM / files?"

| Example | What it shows |
|---------|---------------|
| [keyboards.py](features/keyboards.py) | Inline keyboards, callbacks, `CallbackDataFactory`, pagination |
| [formatting.py](features/formatting.py) | `md.*`, `html.*`, `Bold(...)`, `FormatBuilder`, `split_text` |
| [fsm.py](features/fsm.py) | Finite State Machine for multi-step dialogs |
| [files.py](features/files.py) | 8 ways to send files + voice conversion |
| [typing_actions.py](features/typing_actions.py) | `@typing_action`, `message.typing()`, `answer_chat_action()` |
| [middleware.py](features/middleware.py) | Custom middleware for logging and access control |
| [multi_router.py](features/multi_router.py) | Sub-routers, chat events, modular code organization |
| [error_handling.py](features/error_handling.py) | `@router.error()`, lifecycle hooks, edited-as-message |
| [custom_prefix.py](features/custom_prefix.py) | `Command` filter with custom prefixes (`!`, `#`) and argument parsing |
| [proxy.py](features/proxy.py) | Corporate proxy, rate limiting, retry, SSL control |

## Integrations

"How do I call the bot from PHP / Grafana / FastAPI?"

| Example | What it shows |
|---------|---------------|
| [server_with_bot.py](integrations/server_with_bot.py) | `BotServer` — HTTP API for non-Python systems (PHP, Go, N8N) |
| [fastapi_bot.py](integrations/fastapi_bot.py) | Bot inside FastAPI with shared `Bot` instance and DI middleware |
| [redis_listener.py](integrations/redis_listener.py) | `RedisListener` — consume tasks from Redis Streams |
| [zabbix_alert.py](integrations/zabbix_alert.py) | Zabbix alerts with feedback chain (FSM + BotServer) |
| [chatops.py](integrations/chatops.py) | ChatOps with RBAC, Scheduler, audit log, Docker healthcheck |
| [report.py](integrations/report.py) | BI reports: `run_sync()` for Oracle/pandas, Scheduler with DI |

## Learning Path

1. **echo_bot.py** — Bot, Dispatcher, Router, `@router.message`
2. **features/keyboards.py** — inline buttons and callbacks
3. **features/fsm.py** — multi-step dialogs with state
4. **features/middleware.py** — request pipeline and DI
5. **integrations/server_with_bot.py** — expose bot as HTTP service
6. **integrations/fastapi_bot.py** — embed bot in existing web app
