"""Audio-to-OGG/Opus converter for voice messages.

Requires the optional ``av`` (PyAV) package::

    pip install av
    # or
    pip install vkworkspace[voice]

Usage::

    from vkworkspace.utils.voice import convert_to_ogg_opus

    # From file on disk
    ogg_bytes = convert_to_ogg_opus("recording.mp3")

    # From bytes in memory
    ogg_bytes = convert_to_ogg_opus(mp3_bytes)

    # Send as voice message
    from vkworkspace.types.input_file import InputFile
    await bot.send_voice(chat_id, file=InputFile(ogg_bytes, filename="voice.ogg"))
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import BinaryIO

try:
    import av  # type: ignore[import-not-found]
except ImportError:
    av = None  # type: ignore[assignment]

_IMPORT_ERROR_MSG = (
    "PyAV is required for audio conversion. "
    "Install it with: pip install av  (or: pip install vkworkspace[voice])"
)


def convert_to_ogg_opus(
    source: str | Path | bytes | BinaryIO,
    *,
    bitrate: int = 64_000,
    sample_rate: int = 48_000,
) -> bytes:
    """Convert an audio file (MP3, MP4/AAC, WAV, FLAC, etc.) to OGG/Opus.

    Args:
        source: Path to a file, raw bytes, or a readable binary stream.
        bitrate: Target bitrate in bps (default 64 kbps — good for voice).
        sample_rate: Output sample rate in Hz (default 48 000 — Opus standard).

    Returns:
        OGG/Opus encoded audio data, ready to send via ``bot.send_voice()``.

    Raises:
        ImportError: If ``av`` (PyAV) is not installed.
    """
    if av is None:
        raise ImportError(_IMPORT_ERROR_MSG)

    # Open input
    if isinstance(source, (str, Path)):
        input_container = av.open(str(source))
    elif isinstance(source, bytes):
        input_container = av.open(BytesIO(source))
    else:
        input_container = av.open(source)

    output_buf = BytesIO()

    try:
        input_stream = input_container.streams.audio[0]

        output_container = av.open(output_buf, mode="w", format="ogg")
        try:
            output_stream = output_container.add_stream("libopus", rate=sample_rate)
            output_stream.bit_rate = bitrate

            resampler = av.AudioResampler(
                format="s16",
                layout="mono",
                rate=sample_rate,
            )

            for frame in input_container.decode(input_stream):
                for resampled in resampler.resample(frame):
                    for packet in output_stream.encode(resampled):
                        output_container.mux(packet)

            # Flush encoder
            for packet in output_stream.encode(None):
                output_container.mux(packet)
        finally:
            output_container.close()
    finally:
        input_container.close()

    return output_buf.getvalue()
