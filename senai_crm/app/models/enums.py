import enum


class ContactStatus(str, enum.Enum):
    VIP = "VIP"
    BLOCKED = "Blocked"
    ACTIVE = "Active"
    CHURNED = "Churned"


class ThreadStatus(str, enum.Enum):
    OPEN = "Open"
    RESOLVED = "Resolved"
    ESCALATED = "Escalated"
    IGNORED = "Ignored"


class EmailStatus(str, enum.Enum):
    RECEIVED = "Received"
    PROCESSING = "Processing"
    REPLIED = "Replied"
    ESCALATED = "Escalated"
    IGNORED = "Ignored"


class ActionType(str, enum.Enum):
    AUTO_REPLY = "Auto-Reply"
    ESCALATE = "Escalate"
    LEGAL_FLAG = "Legal-Flag"
    TICKET_CREATED = "Ticket-Created"
    IGNORED = "Ignored"
