from __future__ import annotations

import json

from vkworkspace.enums.button_style import ButtonStyle


class InlineKeyboardButton:
    """Single inline keyboard button."""

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
    """
    Fluent API for building inline keyboards.

    Usage::

        builder = InlineKeyboardBuilder()
        builder.button(text="Option A", callback_data="a")
        builder.button(text="Option B", callback_data="b")
        builder.adjust(2)  # 2 buttons per row

        await message.answer("Choose:", inline_keyboard_markup=builder.as_markup())
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
        self._rows.append(list(buttons))
        return self

    def adjust(self, *sizes: int) -> InlineKeyboardBuilder:
        """
        Arrange flat buttons into rows.

        ``adjust(2)`` -> rows of 2 buttons.
        ``adjust(1, 2, 1)`` -> first row 1 btn, second row 2, third row 1, repeat.
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
        if self._buttons:
            self.adjust(1)
        return [[btn.to_dict() for btn in row] for row in self._rows]

    def as_json(self) -> str:
        return json.dumps(self.as_markup(), ensure_ascii=False)

    def copy(self) -> InlineKeyboardBuilder:
        new = InlineKeyboardBuilder()
        new._buttons = list(self._buttons)
        new._rows = [list(row) for row in self._rows]
        return new
