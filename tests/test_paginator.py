"""Tests for Paginator — keyboard pagination helper."""

from vkworkspace.utils.keyboard import InlineKeyboardBuilder
from vkworkspace.utils.paginator import PaginationCB, Paginator


class TestPaginatorProperties:
    def test_total_pages(self):
        p = Paginator(data=list(range(11)), per_page=5)
        assert p.total_pages == 3

    def test_total_pages_exact(self):
        p = Paginator(data=list(range(10)), per_page=5)
        assert p.total_pages == 2

    def test_total_pages_empty(self):
        p = Paginator(data=[], per_page=5)
        assert p.total_pages == 1

    def test_total_pages_one_item(self):
        p = Paginator(data=[1], per_page=5)
        assert p.total_pages == 1

    def test_offset(self):
        p = Paginator(data=list(range(20)), per_page=5, current_page=2)
        assert p.offset == 10

    def test_page_data_first(self):
        data = list(range(12))
        p = Paginator(data=data, per_page=5, current_page=0)
        assert list(p.page_data) == [0, 1, 2, 3, 4]

    def test_page_data_middle(self):
        data = list(range(12))
        p = Paginator(data=data, per_page=5, current_page=1)
        assert list(p.page_data) == [5, 6, 7, 8, 9]

    def test_page_data_last(self):
        data = list(range(12))
        p = Paginator(data=data, per_page=5, current_page=2)
        assert list(p.page_data) == [10, 11]

    def test_has_prev_first_page(self):
        p = Paginator(data=list(range(10)), per_page=5, current_page=0)
        assert p.has_prev is False

    def test_has_prev_second_page(self):
        p = Paginator(data=list(range(10)), per_page=5, current_page=1)
        assert p.has_prev is True

    def test_has_next_last_page(self):
        p = Paginator(data=list(range(10)), per_page=5, current_page=1)
        assert p.has_next is False

    def test_has_next_first_page(self):
        p = Paginator(data=list(range(10)), per_page=5, current_page=0)
        assert p.has_next is True


class TestNavButtons:
    def test_single_page_no_buttons(self):
        p = Paginator(data=[1, 2], per_page=5)
        assert p.nav_buttons() == []

    def test_first_page_no_prev(self):
        p = Paginator(data=list(range(10)), per_page=5, current_page=0)
        buttons = p.nav_buttons()
        texts = [b.text for b in buttons]
        assert texts == ["1/2", "▶"]

    def test_last_page_no_next(self):
        p = Paginator(data=list(range(10)), per_page=5, current_page=1)
        buttons = p.nav_buttons()
        texts = [b.text for b in buttons]
        assert texts == ["◀", "2/2"]

    def test_middle_page_both_arrows(self):
        p = Paginator(data=list(range(15)), per_page=5, current_page=1)
        buttons = p.nav_buttons()
        texts = [b.text for b in buttons]
        assert texts == ["◀", "2/3", "▶"]

    def test_prev_button_callback(self):
        p = Paginator(data=list(range(15)), per_page=5, current_page=1, name="test")
        buttons = p.nav_buttons()
        assert buttons[0].callback_data is not None
        prev_cb = PaginationCB.unpack(buttons[0].callback_data)
        assert prev_cb.name == "test"
        assert prev_cb.page == 0

    def test_next_button_callback(self):
        p = Paginator(data=list(range(15)), per_page=5, current_page=1, name="test")
        buttons = p.nav_buttons()
        assert buttons[2].callback_data is not None
        next_cb = PaginationCB.unpack(buttons[2].callback_data)
        assert next_cb.name == "test"
        assert next_cb.page == 2

    def test_counter_button_callback(self):
        p = Paginator(data=list(range(15)), per_page=5, current_page=1, name="x")
        buttons = p.nav_buttons()
        assert buttons[1].callback_data is not None
        counter_cb = PaginationCB.unpack(buttons[1].callback_data)
        assert counter_cb.page == 1  # same page (no-op)


class TestAddNavRow:
    def test_adds_row_to_builder(self):
        p = Paginator(data=list(range(10)), per_page=5, current_page=0, name="t")
        builder = InlineKeyboardBuilder()
        builder.button(text="Item 1", callback_data="i:1")
        builder.adjust(1)

        p.add_nav_row(builder)
        markup = builder.as_markup()

        assert len(markup) == 2  # 1 item row + 1 nav row
        nav_row = markup[1]
        assert len(nav_row) == 2  # [1/2] [▶]

    def test_no_nav_row_single_page(self):
        p = Paginator(data=[1], per_page=5)
        builder = InlineKeyboardBuilder()
        builder.button(text="Item", callback_data="i:1")
        builder.adjust(1)

        p.add_nav_row(builder)
        markup = builder.as_markup()

        assert len(markup) == 1  # only item row, no nav

    def test_returns_builder_for_chaining(self):
        p = Paginator(data=list(range(10)), per_page=5)
        builder = InlineKeyboardBuilder()
        result = p.add_nav_row(builder)
        assert result is builder


class TestPaginationCB:
    def test_pack_unpack(self):
        cb = PaginationCB(name="shop", page=3)
        packed = cb.pack()
        assert packed == "pag:shop:3"

        restored = PaginationCB.unpack(packed)
        assert restored.name == "shop"
        assert restored.page == 3


class TestEdgeCases:
    def test_per_page_zero_becomes_one(self):
        p = Paginator(data=[1, 2, 3], per_page=0)
        assert p.per_page == 1
        assert p.total_pages == 3

    def test_negative_page_becomes_zero(self):
        p = Paginator(data=[1, 2, 3], per_page=1, current_page=-5)
        assert p.current_page == 0

    def test_page_beyond_last(self):
        p = Paginator(data=[1, 2, 3], per_page=2, current_page=99)
        assert list(p.page_data) == []
        assert p.has_next is False
