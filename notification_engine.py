import re


class WalletRepository:
    """Abstract interface defining database contracts."""

    def get_status(self, msg_id: str) -> str:
        raise NotImplementedError

    def save_status(self, msg_id: str, phone: str, status: str):
        raise NotImplementedError


class SMSGatewayClient:
    """Abstract interface representing external telecom provider."""

    def send_sms(self, phone: str, message: str) -> bool:
        raise NotImplementedError


class NotificationEngine:
    """Core Business Logic to be verified."""

    def __init__(self, repo: WalletRepository, primary_gateway: SMSGatewayClient,
                 backup_gateway: SMSGatewayClient = None):
        self.repo = repo
        self.primary_gateway = primary_gateway
        self.backup_gateway = backup_gateway

    def dispatch(self, msg_id: str, phone: str, message: str) -> str:
        if not re.match(r"^\+[1-9]\d{1,14}$", phone):
            raise ValueError("Invalid E.164 phone number format")

        existing_status = self.repo.get_status(msg_id)
        if existing_status == "SENT":
            return "ALREADY_SENT"

        for attempt in range(2):
            try:
                if self.primary_gateway.send_sms(phone, message):
                    self.repo.save_status(msg_id, phone, "SENT")
                    return "SENT_PRIMARY"
            except Exception:
                pass

        if self.backup_gateway:
            try:
                if self.backup_gateway.send_sms(phone, message):
                    self.repo.save_status(msg_id, phone, "SENT_BACKUP")
                    return "SENT_BACKUP"
            except Exception:
                pass

        self.repo.save_status(msg_id, phone, "FAILED")
        raise RuntimeError("All gateways failed to deliver message")