"""
File upload bot — demonstrates all 8 ways to send files + voice conversion.

Commands:
    /disk     — send file from disk
    /bytes    — send file from bytes in memory
    /stream   — send file from BinaryIO stream
    /base64   — send file from base64-encoded string
    /url      — send file downloaded from URL
    /photo    — download photo from URL and send as image
    /fileid   — resend a previously uploaded file by file_id
    /voice    — convert MP3/WAV to OGG/Opus and send as voice message

Usage:
    python examples/features/files.py

Note:
    /voice requires PyAV: pip install av (or: pip install vkworkspace[voice])
"""

import asyncio
import base64
from io import BytesIO
from pathlib import Path

from vkworkspace import Bot, Dispatcher, Router
from vkworkspace.filters import Command
from vkworkspace.types import Message
from vkworkspace.types.input_file import InputFile

router = Router()

# Store last sent file_id for /fileid demo
last_file_id: str | None = None


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "File upload demo:\n"
        "/disk — file from disk\n"
        "/bytes — bytes from memory\n"
        "/stream — BinaryIO stream\n"
        "/base64 — base64-encoded data\n"
        "/url — download from URL and send\n"
        "/photo — photo from URL (JPG/PNG/WEBP)\n"
        "/fileid — resend by file_id\n"
        "/voice — convert & send as voice (requires PyAV)"
    )


# 1. File from disk
@router.message(Command("disk"))
async def cmd_disk(message: Message, bot: Bot) -> None:
    path = Path(__file__).parent / "sample.txt"
    if not path.exists():
        path.write_text("Hello from disk!", encoding="utf-8")

    await bot.send_file(
        chat_id=message.chat.chat_id,
        file=InputFile(path),
        caption="File from disk",
    )


# 2. Bytes from memory
@router.message(Command("bytes"))
async def cmd_bytes(message: Message, bot: Bot) -> None:
    data = b"Generated in memory at runtime"
    await bot.send_file(
        chat_id=message.chat.chat_id,
        file=InputFile(data, filename="memory.txt"),
        caption="File from bytes",
    )


# 3. BinaryIO stream
@router.message(Command("stream"))
async def cmd_stream(message: Message, bot: Bot) -> None:
    buf = BytesIO(b"Data from a stream object")
    await bot.send_file(
        chat_id=message.chat.chat_id,
        file=InputFile(buf, filename="stream.txt"),
        caption="File from BinaryIO",
    )


# 4. Base64
@router.message(Command("base64"))
async def cmd_base64(message: Message, bot: Bot) -> None:
    text = "Decoded from base64"
    b64 = base64.b64encode(text.encode()).decode()

    await bot.send_file(
        chat_id=message.chat.chat_id,
        file=InputFile.from_base64(b64, filename="decoded.txt"),
        caption="File from base64",
    )


# 5. Download from URL
@router.message(Command("url"))
async def cmd_url(message: Message, bot: Bot) -> None:
    file = await InputFile.from_url(
        "https://httpbin.org/robots.txt",
        proxy=bot.proxy,  # uses bot's proxy if configured
    )
    await bot.send_file(
        chat_id=message.chat.chat_id,
        file=file,
        caption="File downloaded from URL",
    )


# 6. Download photo from URL and send as image
@router.message(Command("photo"))
async def cmd_photo(message: Message, bot: Bot) -> None:
    photo = await InputFile.from_url(
        "https://http.cat/images/200.jpg",
        proxy=bot.proxy,
    )
    await bot.send_file(
        chat_id=message.chat.chat_id,
        file=photo,
        caption="HTTP 200 OK cat",
    )


# 7. Resend by file_id (no re-upload)
@router.message(Command("fileid"))
async def cmd_fileid(message: Message, bot: Bot) -> None:
    global last_file_id
    if last_file_id is None:
        await message.answer("Send any file first, then use /fileid to resend it.")
        return

    await bot.send_file(
        chat_id=message.chat.chat_id,
        file_id=last_file_id,
        caption="Resent by file_id (no re-upload)",
    )


# 8. Convert audio to voice message (OGG/Opus)
@router.message(Command("voice"))
async def cmd_voice(message: Message, bot: Bot) -> None:
    try:
        from vkworkspace.utils.voice import convert_to_ogg_opus
    except ImportError:
        await message.answer("PyAV not installed. Run: pip install av")
        return

    # Example: generate a silent WAV and convert to OGG/Opus
    import struct
    import wave

    buf = BytesIO()
    sample_rate = 16000
    n_samples = sample_rate  # 1 second
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{n_samples}h", *([0] * n_samples)))

    ogg_data = convert_to_ogg_opus(buf.getvalue())
    await bot.send_voice(
        chat_id=message.chat.chat_id,
        file=InputFile(ogg_data, filename="voice.ogg"),
    )


# Capture file_id from any incoming file
@router.message()
async def capture_file_id(message: Message) -> None:
    global last_file_id
    parts = getattr(message, "parts", None)
    if parts:
        for part in parts:
            payload = getattr(part, "payload", None)
            file_id = getattr(payload, "file_id", None) if payload else None
            if file_id:
                last_file_id = file_id
                await message.answer(f"Saved file_id: {file_id}\nUse /fileid to resend.")
                return


async def main() -> None:
    bot = Bot(
        token="YOUR_BOT_TOKEN",
        api_url="https://myteam.mail.ru/bot/v1",
    )
    dp = Dispatcher()
    dp.include_router(router)

    print("File upload bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
