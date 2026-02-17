"""Tests for CallbackDataFactory — structured callback data."""

from types import SimpleNamespace

import pytest

from vkworkspace.filters.callback_data import CallbackDataFactory

# ── Test subclasses ─────────────────────────────────────────────────


class ProductCB(CallbackDataFactory, prefix="product"):
    action: str
    id: int


class SimpleCB(CallbackDataFactory, prefix="btn"):
    value: str


class CustomSepCB(CallbackDataFactory, prefix="x", sep="|"):
    a: str
    b: int


# ── Subclass creation ───────────────────────────────────────────────


class TestSubclassCreation:
    def test_prefix_required(self):
        with pytest.raises(TypeError, match="must define a prefix"):

            class Bad(CallbackDataFactory):
                pass

    def test_prefix_stored(self):
        assert ProductCB.__callback_prefix__ == "product"

    def test_custom_sep(self):
        assert CustomSepCB.__callback_sep__ == "|"

    def test_default_sep(self):
        assert ProductCB.__callback_sep__ == ":"


# ── pack / unpack ───────────────────────────────────────────────────


class TestPackUnpack:
    def test_pack(self):
        cb = ProductCB(action="buy", id=42)
        assert cb.pack() == "product:buy:42"

    def test_str(self):
        cb = ProductCB(action="info", id=7)
        assert str(cb) == "product:info:7"

    def test_unpack(self):
        cb = ProductCB.unpack("product:buy:42")
        assert cb.action == "buy"
        assert cb.id == 42

    def test_roundtrip(self):
        original = ProductCB(action="delete", id=99)
        restored = ProductCB.unpack(original.pack())
        assert restored.action == original.action
        assert restored.id == original.id

    def test_simple_pack(self):
        assert SimpleCB(value="yes").pack() == "btn:yes"

    def test_custom_sep_pack(self):
        assert CustomSepCB(a="foo", b=3).pack() == "x|foo|3"

    def test_custom_sep_unpack(self):
        cb = CustomSepCB.unpack("x|bar|5")
        assert cb.a == "bar"
        assert cb.b == 5

    def test_unpack_wrong_prefix(self):
        with pytest.raises(ValueError, match="Invalid prefix"):
            ProductCB.unpack("wrong:buy:42")

    def test_unpack_wrong_field_count(self):
        with pytest.raises(ValueError, match="expected 2 values"):
            ProductCB.unpack("product:buy")

    def test_unpack_extra_fields(self):
        with pytest.raises(ValueError, match="expected 2 values"):
            ProductCB.unpack("product:buy:42:extra")

    def test_unpack_validation_error(self):
        with pytest.raises((ValueError, TypeError)):
            ProductCB.unpack("product:buy:not_a_number")


# ── filter ──────────────────────────────────────────────────────────


def _make_event(callback_data: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(callback_data=callback_data)


class TestFilter:
    @pytest.mark.asyncio
    async def test_matches_prefix(self):
        f = ProductCB.filter()
        result = await f(_make_event("product:buy:42"))
        assert isinstance(result, dict)
        assert result["callback_data"].action == "buy"
        assert result["callback_data"].id == 42

    @pytest.mark.asyncio
    async def test_no_match_wrong_prefix(self):
        f = ProductCB.filter()
        result = await f(_make_event("other:buy:42"))
        assert result is False

    @pytest.mark.asyncio
    async def test_no_match_none(self):
        f = ProductCB.filter()
        result = await f(_make_event(None))
        assert result is False

    @pytest.mark.asyncio
    async def test_no_match_malformed(self):
        f = ProductCB.filter()
        result = await f(_make_event("product:buy"))
        assert result is False

    @pytest.mark.asyncio
    async def test_filter_with_magic_rule(self):
        from vkworkspace import F

        f = ProductCB.filter(F.action == "buy")
        # Matches
        result = await f(_make_event("product:buy:42"))
        assert isinstance(result, dict)
        assert result["callback_data"].id == 42

        # Doesn't match rule
        result = await f(_make_event("product:info:42"))
        assert result is False

    @pytest.mark.asyncio
    async def test_filter_no_callback_data_attr(self):
        f = ProductCB.filter()
        event = SimpleNamespace()  # no callback_data attribute
        result = await f(event)
        assert result is False

    @pytest.mark.asyncio
    async def test_custom_sep_filter(self):
        f = CustomSepCB.filter()
        result = await f(_make_event("x|hello|10"))
        assert isinstance(result, dict)
        assert result["callback_data"].a == "hello"
        assert result["callback_data"].b == 10
