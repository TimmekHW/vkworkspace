from __future__ import annotations

import json

from vkworkspace.enums.button_style import ButtonStyle


class InlineKeyboardButton:
    """Single inline keyboard button.

    Args:
        text: Button label shown to the user.
        callback_data: Data sent to bot when button is pressed.
            Handle with ``@router.callback_query()``.
        url: URL to open when button is pressed (instead of callback).
        style: Visual style — ``"primary"`` (blue) or ``"attention"`` (red).
    """

    def __init__(
        self,
        text: str,
        callback_data: str | None = None,
        url: str | None = None,
        style: str | ButtonStyle = ButtonStyle.PRIMARY,
    ) -> None:
        self.text = text
        self.callback_data = callback_data
        self.url = url
        self.style = str(style)

    def to_dict(self) -> dict[str, str]:
        result: dict[str, str] = {"text": self.text}
        if self.callback_data is not None:
            result["callbackData"] = self.callback_data
        if self.url is not None:
            result["url"] = self.url
        if self.style:
            result["style"] = self.style
        return result


class InlineKeyboardBuilder:
    """Fluent builder for inline keyboards.

    Chain ``.button()`` calls, then ``.adjust()`` to set row layout,
    and pass ``.as_markup()`` to ``message.answer()``.

    Example::

        builder = InlineKeyboardBuilder()
        builder.button(text="Yes", callback_data="yes")
        builder.button(text="No", callback_data="no")
        builder.adjust(2)  # 2 buttons per row

        await message.answer("Confirm?", inline_keyboard_markup=builder.as_markup())

    With URL buttons::

        builder = InlineKeyboardBuilder()
        builder.button(text="Open docs", url="https://example.com/docs")

    With styles::

        from vkworkspace.enums import ButtonStyle
        builder.button(text="Delete", callback_data="del", style=ButtonStyle.ATTENTION)
    """

    def __init__(self) -> None:
        self._buttons: list[InlineKeyboardButton] = []
        self._rows: list[list[InlineKeyboardButton]] = []

    def button(
        self,
        text: str,
        callback_data: str | None = None,
        url: str | None = None,
        style: str | ButtonStyle = ButtonStyle.PRIMARY,
    ) -> InlineKeyboardBuilder:
        """Add a button. Returns ``self`` for chaining.

        Args:
            text: Button label.
            callback_data: Callback data string (triggers ``callback_query``).
            url: URL to open (mutually exclusive with *callback_data*).
            style: ``"primary"`` (blue, default) or ``"attention"`` (red).
        """
        self._buttons.append(
            InlineKeyboardButton(
                text=text,
                callback_data=callback_data,
                url=url,
                style=style,
            )
        )
        return self

    def row(self, *buttons: InlineKeyboardButton) -> InlineKeyboardBuilder:
        """Add a pre-built row of buttons.

        For most cases, use ``.button()`` + ``.adjust()`` instead.
        """
        self._rows.append(list(buttons))
        return self

    def adjust(self, *sizes: int) -> InlineKeyboardBuilder:
        """Arrange flat buttons into rows.

        Args:
            *sizes: Buttons per row. Repeats cyclically.

        Examples::

            builder.adjust(2)           # all rows have 2 buttons
            builder.adjust(1, 2, 1)     # row1: 1 btn, row2: 2, row3: 1, repeat
            builder.adjust(3)           # rows of 3
        """
        if not sizes:
            sizes = (1,)

        buttons = list(self._buttons)
        self._buttons.clear()

        idx = 0
        size_idx = 0
        while idx < len(buttons):
            size = sizes[size_idx % len(sizes)]
            self._rows.append(buttons[idx : idx + size])
            idx += size
            size_idx += 1

        return self

    def as_markup(self) -> list[list[dict[str, str]]]:
        """Convert to VK Teams JSON format. Pass to ``inline_keyboard_markup``."""
        if self._buttons:
            self.adjust(1)
        return [[btn.to_dict() for btn in row] for row in self._rows]

    def as_json(self) -> str:
        """Convert to JSON string (for raw API calls)."""
        return json.dumps(self.as_markup(), ensure_ascii=False)

    def copy(self) -> InlineKeyboardBuilder:
        """Create a shallow copy of this builder."""
        new = InlineKeyboardBuilder()
        new._buttons = list(self._buttons)
        new._rows = [list(row) for row in self._rows]
        return new
