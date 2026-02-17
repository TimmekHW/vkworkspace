"""Tests for voice conversion utility."""

from unittest.mock import patch

import pytest

from vkworkspace.utils.voice import convert_to_ogg_opus

_has_av = False
try:
    import av  # type: ignore[import-not-found]  # noqa: F401

    _has_av = True
except ImportError:
    pass


class TestWithoutAv:
    """Tests that work even without PyAV installed."""

    def test_import_error_without_av(self):
        with (
            patch("vkworkspace.utils.voice.av", None),
            pytest.raises(ImportError, match="PyAV is required"),
        ):
            convert_to_ogg_opus(b"fake audio")


@pytest.mark.skipif(not _has_av, reason="PyAV not installed")
class TestConversion:
    """Conversion tests — skipped if av is not installed."""

    def _make_wav(self, duration_ms: int = 200) -> bytes:
        """Generate a minimal WAV file in memory."""
        import struct
        import wave
        from io import BytesIO

        buf = BytesIO()
        sample_rate = 16000
        n_samples = int(sample_rate * duration_ms / 1000)
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(struct.pack(f"<{n_samples}h", *([0] * n_samples)))
        return buf.getvalue()

    def test_wav_to_ogg(self):
        wav = self._make_wav()
        ogg = convert_to_ogg_opus(wav)
        assert ogg[:4] == b"OggS"
        assert len(ogg) > 0

    def test_wav_to_ogg_from_path(self, tmp_path):
        wav = self._make_wav()
        p = tmp_path / "test.wav"
        p.write_bytes(wav)

        ogg = convert_to_ogg_opus(str(p))
        assert ogg[:4] == b"OggS"

    def test_wav_to_ogg_from_stream(self):
        from io import BytesIO

        wav = self._make_wav()
        ogg = convert_to_ogg_opus(BytesIO(wav))
        assert ogg[:4] == b"OggS"

    def test_custom_bitrate(self):
        wav = self._make_wav()
        ogg_low = convert_to_ogg_opus(wav, bitrate=16_000)
        ogg_high = convert_to_ogg_opus(wav, bitrate=128_000)
        assert ogg_low[:4] == b"OggS"
        assert ogg_high[:4] == b"OggS"
