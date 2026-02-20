"""Pagination helper for inline keyboards.

Splits a list of items into pages and adds navigation buttons
(``◀`` / ``▶``) automatically.

Example::

    from vkworkspace.utils.paginator import Paginator, PaginationCB

    @router.message(Command("catalog"))
    async def cmd_catalog(message: Message):
        items = ["Apple", "Banana", "Cherry", "Date", "Elderberry",
                 "Fig", "Grape", "Honeydew", "Kiwi", "Lemon"]

        paginator = Paginator(data=items, per_page=3, current_page=0, name="fruits")

        builder = InlineKeyboardBuilder()
        for i, fruit in enumerate(paginator.page_data, paginator.offset + 1):
            builder.button(text=f"{i}. {fruit}", callback_data=f"fruit:{fruit}")
        builder.adjust(1)
        paginator.add_nav_row(builder)

        await message.answer("Fruits:", inline_keyboard_markup=builder.as_markup())

    @router.callback_query(PaginationCB.filter())
    async def on_page(query: CallbackQuery, callback_data: PaginationCB):
        page = callback_data.page
        # rebuild keyboard for new page ...
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from vkworkspace.filters.callback_data import CallbackDataFactory
from vkworkspace.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton


class PaginationCB(CallbackDataFactory, prefix="pag"):
    """Built-in callback data for page navigation buttons.

    Attributes:
        name: Paginator instance name (to distinguish multiple paginators).
        page: Target page number (0-indexed).
    """

    name: str
    page: int


class Paginator:
    """Slice data into pages and generate navigation buttons.

    Args:
        data: Full list of items to paginate.
        per_page: Items per page (default 5).
        current_page: Current page, 0-indexed (default 0).
        name: Unique name for this paginator — used in ``PaginationCB``
            to distinguish multiple paginators in the same chat.

    Example::

        paginator = Paginator(data=products, per_page=5, current_page=0, name="shop")
        paginator.page_data        # items for current page
        paginator.total_pages      # total number of pages
        paginator.has_next         # True if there's a next page
        paginator.add_nav_row(builder)  # adds [◀] [2/5] [▶] to builder
    """

    def __init__(
        self,
        data: Sequence[Any],
        per_page: int = 5,
        current_page: int = 0,
        name: str = "page",
    ) -> None:
        self.data = data
        self.per_page = max(1, per_page)
        self.current_page = max(0, current_page)
        self.name = name

    @property
    def total_pages(self) -> int:
        """Total number of pages."""
        return max(1, math.ceil(len(self.data) / self.per_page))

    @property
    def offset(self) -> int:
        """Start index of the current page (0-based)."""
        return self.current_page * self.per_page

    @property
    def page_data(self) -> Sequence[Any]:
        """Items for the current page."""
        start = self.offset
        return self.data[start : start + self.per_page]

    @property
    def has_prev(self) -> bool:
        """``True`` if there is a previous page."""
        return self.current_page > 0

    @property
    def has_next(self) -> bool:
        """``True`` if there is a next page."""
        return self.current_page < self.total_pages - 1

    def nav_buttons(self) -> list[InlineKeyboardButton]:
        """Build navigation buttons: ``[◀] [2/5] [▶]``.

        Returns an empty list if there is only one page.
        """
        if self.total_pages <= 1:
            return []

        buttons: list[InlineKeyboardButton] = []

        if self.has_prev:
            buttons.append(
                InlineKeyboardButton(
                    text="◀",
                    callback_data=PaginationCB(
                        name=self.name,
                        page=self.current_page - 1,
                    ).pack(),
                )
            )

        buttons.append(
            InlineKeyboardButton(
                text=f"{self.current_page + 1}/{self.total_pages}",
                callback_data=PaginationCB(
                    name=self.name,
                    page=self.current_page,
                ).pack(),
            )
        )

        if self.has_next:
            buttons.append(
                InlineKeyboardButton(
                    text="▶",
                    callback_data=PaginationCB(
                        name=self.name,
                        page=self.current_page + 1,
                    ).pack(),
                )
            )

        return buttons

    def add_nav_row(self, builder: InlineKeyboardBuilder) -> InlineKeyboardBuilder:
        """Append a navigation row to an existing keyboard builder.

        Does nothing if there is only one page.

        Args:
            builder: The keyboard builder to add navigation to.

        Returns:
            The same builder (for chaining).
        """
        buttons = self.nav_buttons()
        if buttons:
            builder.row(*buttons)
        return builder
