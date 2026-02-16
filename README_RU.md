# vkworkspace

**Полностью асинхронный** фреймворк для создания ботов для **VK Teams** (VK WorkSpace / VK SuperApp), вдохновлённый [aiogram 3](https://github.com/aiogram/aiogram).

Современная замена официальной библиотеке [mail-ru-im/bot-python](https://github.com/mail-ru-im/bot-python) (`mailru-im-bot`).

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/TimmekHW/vkworkspace/blob/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/vkworkspace.svg)](https://pypi.org/project/vkworkspace/)

> **[README in English](https://github.com/TimmekHW/vkworkspace/blob/main/README.md)**

## vkworkspace vs mailru-im-bot

Официальная библиотека [mailru-im-bot](https://github.com/mail-ru-im/bot-python) — синхронная, основана на `requests` и не обновлялась годами. **vkworkspace** — полностью асинхронная переработка с нуля с современным опытом разработки.

### Сравнение возможностей

| | mailru-im-bot | vkworkspace |
|---|:---:|:---:|
| **HTTP-клиент** | `requests` (sync) | `httpx` (async) |
| **Модели данных** | сырые `dict` | Pydantic v2 |
| **Router / Dispatcher** | — | aiogram совместимые|
| **Магические фильтры (`F`)** | — | `F.text`, `F.chat.type == "private"` |
| **FSM (автомат состояний)** | — | бэкенды Memory + Redis |
| **Middleware** | — | inner/outer, per-event |
| **Конструктор клавиатур** | — | `InlineKeyboardBuilder` |
| **Rate limiter** | — | встроенный token-bucket |
| **Прокси** | — | параметр `proxy=` |
| **Инъекция зависимостей** | — | авто-инжект `bot`, `state`, `command` |
| **Кастомные префиксы** | — | `prefix=("/", "!", "")` |
| **Обработка ошибок** | — | `@router.error()` |
| **Type hints** | частично | полные |

### Бенчмарк скорости

Тесты на Python 3.11, корпоративный инстанс VK Teams. 5 раундов на дисциплину, значения — медиана:

```
                          mailru-im-bot    vkworkspace     победитель
                          (requests sync)  (httpx async)
 Bot Info (self/get)         34 мс            33 мс        ~ничья
 Send Text                   82 мс           109 мс        mailru-im-bot
 Send Keyboard               97 мс            90 мс        vkworkspace
 Edit Message                57 мс            44 мс        vkworkspace
 Delete Message              33 мс            38 мс        mailru-im-bot
 Chat Info                   43 мс            42 мс        ~ничья
 Send Actions                30 мс            28 мс        vkworkspace
 BURST (10 сообщ.)         1110 мс           335 мс        vkworkspace (3.3x!)
                          ───────────────────────────────────────────
 Счёт                         2                4           побеждает vkworkspace
```

**Главный вывод:** На одиночных последовательных запросах обе библиотеки в пределах шума сети (~1 мс разницы). Но когда нужно отправить несколько сообщений или обработать параллельных пользователей, async побеждает с разгромом — **в 3.3 раза быстрее** на burst-операциях через `asyncio.gather()`.

Framework overhead — **НОЛЬ** в реальных условиях. Сетевая задержка доминирует на 99%+ от общего времени.

## Зачем async?

Боты VK Teams 99% времени ждут сеть. Синхронные фреймворки (`requests`) блокируют весь процесс на каждом API-вызове. **vkworkspace** использует `httpx.AsyncClient` и `asyncio` — пока один запрос ждёт ответ, бот обрабатывает другие сообщения.

## Возможности

- **100% async** — `httpx` + `asyncio`, ноль блокирующих вызовов, реальная конкурентность
- **API как в aiogram** — `Router`, `Dispatcher`, магический фильтр `F`, middleware, FSM
- **Типобезопасность** — Pydantic v2 модели для всех типов API, полные type hints
- **Гибкая фильтрация** — `Command`, `StateFilter`, `ChatTypeFilter`, `CallbackData`, regex, магические фильтры
- **Кастомные префиксы команд** — `Command("start", prefix=("/", "!", ""))` для любого стиля
- **FSM** — конечный автомат состояний с бэкендами Memory и Redis
- **Middleware** — пайплайн inner/outer для логирования, авторизации, троттлинга
- **Форматирование текста** — хелперы `md`, `html` для MarkdownV2/HTML + `split_text` для длинных сообщений
- **Конструктор клавиатур** — fluent API для inline-клавиатур со стилями кнопок
- **Rate limiter** — встроенный ограничитель запросов (`rate_limit=5` = макс. 5 запросов/сек)
- **Прокси** — маршрутизация API-запросов через корпоративный прокси
- **Роутинг отредактированных сообщений** — `handle_edited_as_message=True` для обработки правок как новых сообщений
- **Хуки жизненного цикла** — `on_startup` / `on_shutdown` для инициализации и очистки
- **Обработка ошибок** — `@router.error()` для перехвата исключений
- **Мульти-бот polling** — `dp.start_polling(bot1, bot2)` для нескольких ботов
- **9 типов событий** — сообщения, правки, удаления, закрепления, вход/выход участников, инфо чата, callback
- **Python 3.11 — 3.14** (free-threaded / no-GIL билд пока не тестировался)

## Установка

```bash
pip install vkworkspace
```

С Redis хранилищем для FSM:

```bash
pip install vkworkspace[redis]
```

## Быстрый старт

```python
import asyncio
from vkworkspace import Bot, Dispatcher, Router, F
from vkworkspace.filters import Command
from vkworkspace.types import Message

router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer("Привет! Я твой бот.")

@router.message(F.text)
async def echo(message: Message) -> None:
    await message.answer(message.text)

async def main() -> None:
    bot = Bot(token="ТВОЙ_ТОКЕН", api_url="https://myteam.mail.ru/bot/v1")
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)

asyncio.run(main())
```

> **API URL:** У каждой компании свой URL для API VK Teams (VK WorkSpace). Уточняйте у своего интегратора или IT-отдела. Примеры:
> - `https://myteam.mail.ru/bot/v1` (Mail.ru по умолчанию)
> - `https://api.workspace.company.com/bot/v1` (on-premise)

> Даже в SaaS-инсталляциях URL может отличаться — всегда уточняйте у администратора.

## Настройка бота

```python
bot = Bot(
    token="ТВОЙ_ТОКЕН",
    api_url="https://myteam.mail.ru/bot/v1",
    timeout=30.0,               # Таймаут запроса (секунды)
    poll_time=60,               # Таймаут long-poll (секунды)
    rate_limit=5.0,             # Макс 5 запросов/сек (None = без ограничений)
    proxy="http://proxy:8080",  # HTTP-прокси для корпоративных сетей
)
```

### Rate Limiter (ограничитель запросов)

Встроенный rate limiter предотвращает блокировку API:

```python
# Макс 10 запросов в секунду — фреймворк ставит остальные в очередь
bot = Bot(token="TOKEN", api_url="URL", rate_limit=10)
```

### Прокси

В корпоративных сетях часто нужен прокси. Параметр `proxy` применяется только к API-запросам:

```python
bot = Bot(
    token="TOKEN",
    api_url="https://api.internal.corp/bot/v1",
    proxy="http://corp-proxy.internal:3128",
)
```

## Диспетчер

```python
dp = Dispatcher(
    storage=MemoryStorage(),            # Хранилище FSM (по умолчанию: MemoryStorage)
    fsm_strategy="user_in_chat",        # Стратегия ключей FSM
    handle_edited_as_message=False,     # Роутить правки в @router.message
)

# Хуки жизненного цикла
@dp.on_startup
async def on_start():
    print("Бот запущен!")

@dp.on_shutdown
async def on_stop():
    print("Бот остановлен!")

# Подключение роутеров
dp.include_router(router)
dp.include_routers(admin_router, user_router)

# Запуск polling (поддерживает несколько ботов)
await dp.start_polling(bot)
await dp.start_polling(bot1, bot2, skip_updates=True)
```

### Роутинг отредактированных сообщений

При `handle_edited_as_message=True` отредактированные сообщения попадают в хендлеры `@router.message` вместо `@router.edited_message`. Удобно, когда нужно получать обновление данные:

```python
dp = Dispatcher(handle_edited_as_message=True)

# Этот хендлер срабатывает И на новые, И на отредактированные сообщения
@router.message(F.text)
async def handle_text(message: Message) -> None:
    await message.answer(f"Получил: {message.text}")
```

## Роутер и типы событий

```python
router = Router(name="my_router")

# Все 9 поддерживаемых типов событий:
@router.message(...)              # Новое сообщение
@router.edited_message(...)       # Отредактированное сообщение
@router.deleted_message(...)      # Удалённое сообщение
@router.pinned_message(...)       # Закреплённое сообщение
@router.unpinned_message(...)     # Откреплённое сообщение
@router.new_chat_members(...)     # Пользователи вошли
@router.left_chat_members(...)    # Пользователи вышли
@router.changed_chat_info(...)    # Изменилась информация о чате
@router.callback_query(...)       # Нажата кнопка

# Обработчик ошибок — ловит исключения из любого хендлера
@router.error()
async def on_error(event, error: Exception) -> None:
    print(f"Ошибка: {error}")

# Подроутеры для модульного кода
admin_router = Router(name="admin")
user_router = Router(name="user")
main_router = Router()
main_router.include_routers(admin_router, user_router)
```

## Фильтры

### Фильтр команд

```python
from vkworkspace.filters import Command

# Базовое использование
@router.message(Command("start"))
@router.message(Command("help", "info"))     # Несколько команд

# Кастомные префиксы
@router.message(Command("start", prefix="/"))           # Только /start
@router.message(Command("menu", prefix=("/", "!", ""))) # /menu, !menu, menu

# Regex-команды
import re
@router.message(Command(re.compile(r"cmd_\d+")))        # /cmd_1, /cmd_42, ...

# Доступ к аргументам команды в хендлере
@router.message(Command("ban"))
async def ban_user(message: Message, command: CommandObject) -> None:
    user_to_ban = command.args  # Текст после "/ban "
    await message.answer(f"Забанен: {user_to_ban}")
```

`CommandObject` инжектится в хендлер:
- `prefix` — совпавший префикс (`"/"`, `"!"`, и т.д.)
- `command` — имя команды (`"ban"`)
- `args` — аргументы после команды (`"user123"`)
- `raw_text` — полный текст сообщения
- `match` — `re.Match`, если использовался regex-паттерн

### Магический фильтр (F)

```python
from vkworkspace import F

@router.message(F.text)                              # Есть текст
@router.message(F.text == "привет")                  # Точное совпадение
@router.message(F.text.startswith("ку"))             # Методы строк
@router.message(F.from_user.user_id == "admin@co")   # Вложенные атрибуты
@router.message(F.chat.type == "private")            # Личный чат
@router.message(F.chat.type.in_(["private", "group"]))
@router.callback_query(F.callback_data == "confirm")
```

### Фильтр состояний

```python
from vkworkspace.filters.state import StateFilter

@router.message(StateFilter(Form.name))     # Конкретное состояние
@router.message(StateFilter("*"))           # Любое состояние (не None)
@router.message(StateFilter(None))          # Нет состояния (по умолчанию)
```

### Другие фильтры

```python
from vkworkspace.filters import CallbackData, ChatTypeFilter, RegexpFilter

# Callback data
@router.callback_query(CallbackData("confirm"))
@router.callback_query(CallbackData(re.compile(r"^action_\d+$")))

# Тип чата
@router.message(ChatTypeFilter("private"))
@router.message(ChatTypeFilter(["private", "group"]))

# Regex по тексту сообщения
@router.message(RegexpFilter(r"\d{4}"))

# Комбинирование фильтров через &, |, ~
@router.message(ChatTypeFilter("private") & Command("secret"))
```

### Свои фильтры

```python
from vkworkspace.filters.base import BaseFilter

class IsAdmin(BaseFilter):
    async def __call__(self, event, **kwargs) -> bool:
        admins = await event.bot.get_chat_admins(event.chat.chat_id)
        return any(a.user_id == event.from_user.user_id for a in admins)

@router.message(IsAdmin())
async def admin_only(message: Message) -> None:
    await message.answer("Панель администратора")
```

## Форматирование текста

VK Teams поддерживает форматирование в MarkdownV2 и HTML. Используйте хелперы `md` и `html` для безопасного формирования сообщений:

```python
from vkworkspace.utils.text import md, html, split_text

# ── MarkdownV2 ──
text = f"{md.bold('Статус')}: {md.escape(user_input)}"
await message.answer(text, parse_mode="MarkdownV2")

md.bold("текст")            # *текст*
md.italic("текст")          # _текст_
md.underline("текст")       # __текст__
md.strikethrough("текст")   # ~текст~
md.code("x = 1")            # `x = 1`
md.pre("код", "python")     # ```python\nкод\n```
md.link("Ссылка", "https://example.com")  # [Ссылка](https://example.com)
md.quote("цитата")          # >цитата
md.escape("цена: $100")     # Экранирует спецсимволы

# ── HTML ──
text = f"{html.bold('Статус')}: {html.escape(user_input)}"
await message.answer(text, parse_mode="HTML")

html.bold("текст")           # <b>текст</b>
html.italic("текст")         # <i>текст</i>
html.underline("текст")      # <u>текст</u>
html.strikethrough("текст")  # <s>текст</s>
html.code("x = 1")           # <code>x = 1</code>
html.pre("код", "python")    # <pre><code class="python">код</code></pre>
html.link("Ссылка", "https://example.com")  # <a href="...">Ссылка</a>
html.quote("цитата")         # <blockquote>цитата</blockquote>
html.ordered_list(["а", "б"])    # <ol><li>а</li><li>б</li></ol>
html.unordered_list(["а", "б"]) # <ul><li>а</li><li>б</li></ul>

# ── Разбиение длинного текста ──
# VK Teams может лагать на сообщениях > 4096 символов; split_text разбивает их
for chunk in split_text(long_text):
    await message.answer(chunk)

# Кастомный лимит
for chunk in split_text(long_text, max_length=2000):
    await message.answer(chunk)
```

## Inline-клавиатуры

```python
from vkworkspace.utils.keyboard import InlineKeyboardBuilder
from vkworkspace.enums import ButtonStyle

builder = InlineKeyboardBuilder()
builder.button(text="Да", callback_data="confirm", style=ButtonStyle.PRIMARY)
builder.button(text="Нет", callback_data="cancel", style=ButtonStyle.ATTENTION)
builder.button(text="Может быть", callback_data="maybe")
builder.adjust(2, 1)  # Ряд 1: 2 кнопки, Ряд 2: 1 кнопка

await message.answer("Вы уверены?", inline_keyboard_markup=builder.as_markup())

# Копирование и модификация
builder2 = builder.copy()
builder2.button(text="Ещё", callback_data="extra")
```

## FSM (конечный автомат состояний)

FSM позволяет строить многошаговые диалоги: бот задаёт вопросы, сохраняет ответы пользователя и переходит между состояниями.

```python
from vkworkspace.fsm import StatesGroup, State, FSMContext
from vkworkspace.filters.state import StateFilter
from vkworkspace.fsm.storage.memory import MemoryStorage

# 1. Определяем состояния
class Form(StatesGroup):
    name = State()
    age = State()

# 2. Стартовый хендлер — устанавливает состояние
@router.message(Command("start"))
async def start(message: Message, state: FSMContext) -> None:
    await state.set_state(Form.name)
    await message.answer("Как тебя зовут?") #Данил Колбосенко

# 3. Хендлер для состояния Form.name
@router.message(StateFilter(Form.name), F.text)
async def process_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text)     # Сохраняем имя
    await state.set_state(Form.age)                # Переходим к следующему
    await message.answer("Сколько тебе лет?") #6

# 4. Хендлер для состояния Form.age
@router.message(StateFilter(Form.age), F.text)
async def process_age(message: Message, state: FSMContext) -> None:
    data = await state.get_data()                  # Получаем все данные
    await message.answer(f"Имя: {data['name']}, Возраст: {message.text}")
    await state.clear()                            # Очищаем состояние

# 5. Подключаем хранилище
dp = Dispatcher(storage=MemoryStorage())          # В памяти (для разработки)

from vkworkspace.fsm.storage.redis import RedisStorage
dp = Dispatcher(storage=RedisStorage())           # Redis (для продакшена)
```

Методы FSMContext:
- `await state.get_state()` — текущее состояние (или `None`)
- `await state.set_state(Form.name)` — перейти в состояние
- `await state.get_data()` — получить сохранённые данные (dict)
- `await state.update_data(key=value)` — добавить/обновить данные
- `await state.set_data({...})` — заменить все данные
- `await state.clear()` — очистить состояние и данные

## Middleware (промежуточное ПО)

Middleware — это обёртка вокруг хендлера. Можно добавить логику до и после обработки события.

```python
from vkworkspace import BaseMiddleware

class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        print(f"Событие от: {event.from_user.user_id}")
        result = await handler(event, data)   # Вызываем хендлер
        print(f"Обработано")
        return result

class ThrottleMiddleware(BaseMiddleware):
    """Антифлуд: игнорирует сообщения чаще чем раз в delay секунд."""
    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self.last: dict[str, float] = {}

    async def __call__(self, handler, event, data):
        import time
        uid = getattr(event, "from_user", None)
        uid = uid.user_id if uid else "unknown"
        now = time.monotonic()
        if now - self.last.get(uid, 0) < self.delay:
            return None  # Пропускаем — слишком часто
        self.last[uid] = now
        return await handler(event, data)

# Регистрация на конкретном типе событий
router.message.middleware.register(LoggingMiddleware())
router.message.middleware.register(ThrottleMiddleware(delay=0.5))
router.callback_query.middleware.register(LoggingMiddleware())
```

## Методы объекта Message

```python
# В хендлере:
await message.answer("Привет!")                              # Отправить в тот же чат
await message.reply("Ответ на ваше сообщение!")              # Ответить с цитатой
await message.edit_text("Обновлённый текст")                 # Отредактировать это сообщение
await message.delete()                                       # Удалить это сообщение
await message.pin()                                          # Закрепить это сообщение
await message.unpin()                                        # Открепить это сообщение
await message.answer_file(file=InputFile("фото.jpg"))        # Отправить файл
await message.answer_voice(file=InputFile("голос.ogg"))      # Отправить голосовое
```

## Все методы Bot API

```python
bot = Bot(token="TOKEN", api_url="URL")

# Информация о боте
await bot.get_me()

# Сообщения
await bot.send_text(chat_id, "Привет!", parse_mode="HTML")
await bot.edit_text(chat_id, msg_id, "Обновлено")
await bot.delete_messages(chat_id, msg_id)
await bot.send_file(chat_id, file=InputFile("фото.jpg"), caption="Смотри!")
await bot.send_voice(chat_id, file=InputFile("голос.ogg"))
await bot.answer_callback_query(query_id, "Готово!", show_alert=True)

# Управление чатом
await bot.get_chat_info(chat_id)
await bot.get_chat_admins(chat_id)
await bot.get_chat_members(chat_id)
await bot.get_blocked_users(chat_id)
await bot.get_pending_users(chat_id)
await bot.set_chat_title(chat_id, "Новое название")
await bot.set_chat_about(chat_id, "Описание")
await bot.set_chat_rules(chat_id, "Правила")
await bot.set_chat_avatar(chat_id, file=InputFile("avatar.png"))
await bot.block_user(chat_id, user_id, del_last_messages=True)
await bot.unblock_user(chat_id, user_id)
await bot.resolve_pending(chat_id, approve=True, user_id=uid)
await bot.delete_chat_members(chat_id, members=[uid1, uid2])
await bot.pin_message(chat_id, msg_id)
await bot.unpin_message(chat_id, msg_id)
await bot.send_actions(chat_id, "typing")

# Файлы и треды
await bot.get_file_info(file_id)
await bot.threads_add(chat_id, msg_id)
await bot.threads_get_subscribers(thread_id)
await bot.threads_autosubscribe(chat_id, enable=True)
```

## Инъекция зависимостей в хендлеры

Хендлеры получают только те параметры, которые объявляют. Фреймворк проверяет сигнатуру и инжектит доступные значения:

```python
@router.message(Command("info"))
async def full_handler(
    message: Message,              # Объект сообщения
    bot: Bot,                      # Экземпляр бота
    state: FSMContext,             # Контекст FSM (если настроено хранилище)
    command: CommandObject,        # Распарсенная команда (от фильтра Command)
    raw_event: dict,               # Сырой event из VK Teams API
    event_type: str,               # "message", "callback_query", и т.д.
) -> None:
    ...

# Минимальный вариант — берём только что нужно
@router.message(F.text)
async def simple(message: Message) -> None:
    await message.answer(message.text)
```

## Примеры

| Пример | Описание |
|--------|----------|
| [echo_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/echo_bot.py) | Базовые команды + эхо-бот |
| [keyboard_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/keyboard_bot.py) | Inline-клавиатуры + обработка callback |
| [fsm_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/fsm_bot.py) | Многошаговый диалог с FSM |
| [middleware_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/middleware_bot.py) | Middleware (логирование, контроль доступа) |
| [proxy_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/proxy_bot.py) | Корпоративный прокси + rate limiter |
| [error_handling_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/error_handling_bot.py) | Обработка ошибок, хуки жизненного цикла, роутинг правок |
| [custom_prefix_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/custom_prefix_bot.py) | Кастомные префиксы команд, regex, парсинг аргументов |
| [multi_router_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/multi_router_bot.py) | Модульные подроутеры, события чата (вход/выход/закреп) |
| [formatting_bot.py](https://github.com/TimmekHW/vkworkspace/blob/main/examples/formatting_bot.py) | Форматирование MarkdownV2/HTML + split_text для длинных сообщений |

## Структура проекта

```
vkworkspace/
├── client/          # Асинхронный HTTP-клиент (httpx), rate limiter, прокси
├── types/           # Pydantic v2 модели (Message, Chat, User, CallbackQuery, ...)
├── enums/           # EventType, ChatType, ParseMode, ButtonStyle, ...
├── dispatcher/      # Dispatcher, Router, EventObserver, Middleware pipeline
├── filters/         # Command, StateFilter, CallbackData, ChatType, Regexp
├── fsm/             # StatesGroup, State, FSMContext, Memory/Redis хранилища
└── utils/           # InlineKeyboardBuilder, магический фильтр (F), форматирование текста (md, html, split_text)
```

## Требования

- Python 3.11+
- httpx >= 0.28.1
- pydantic >= 2.6
- magic-filter >= 1.0.12

## Лицензия

MIT [LICENSE](https://github.com/TimmekHW/vkworkspace/blob/main/LICENSE).

---

<sub>**Ключевые слова:** VK Teams бот, VK Workspace бот, VK WorkSpace, VK SuperApp, vkteams, workspace.vk.ru, workspacevk, vkworkspace, myteam.mail.ru, agent.mail.ru, mail-ru-im-bot, mailru-im-bot, bot-python, VK Teams API, VK Teams фреймворк, асинхронный бот фреймворк, Python бот VK Teams, aiogram VK Teams, httpx бот, бот для ВК Тимс, VK Workspace Python, ВК Воркспейс</sub>
