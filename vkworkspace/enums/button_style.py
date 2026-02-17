from enum import StrEnum


class ButtonStyle(StrEnum):
    """Inline keyboard button visual style.

    - ``BASE`` — neutral grey button (system default).
    - ``PRIMARY`` — blue button.
    - ``ATTENTION`` — red button (for destructive actions).
    """

    BASE = "base"
    PRIMARY = "primary"
    ATTENTION = "attention"
