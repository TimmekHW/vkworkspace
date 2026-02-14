"""
Magic Filter setup.

The ``F`` object allows expressive filtering::

    F.text                        # message.text is truthy
    F.text == "hello"             # exact match
    F.text.startswith("hi")       # method delegation
    F.from_user.user_id == "x"    # nested attribute access
    F.chat.type == "private"      # chat type check
    F.callback_data == "abc"      # callback data check
"""

from magic_filter import MagicFilter

F = MagicFilter()
