from enum import StrEnum


class ButtonStyle(StrEnum):
    """Inline keyboard button visual style.

    - ``PRIMARY`` — blue button (default).
    - ``ATTENTION`` — red button (for destructive actions).
    """

    PRIMARY = "primary"
    ATTENTION = "attention"
