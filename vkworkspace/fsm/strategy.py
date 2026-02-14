from enum import StrEnum


class FSMStrategy(StrEnum):
    USER_IN_CHAT = "user_in_chat"
    CHAT = "chat"
    GLOBAL_USER = "global_user"
