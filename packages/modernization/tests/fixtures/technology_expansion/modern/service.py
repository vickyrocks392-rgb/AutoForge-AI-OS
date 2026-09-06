"""Python modern domain service."""
from dataclasses import dataclass

@dataclass
class Account:
    account_id: str
    balance: float
    status: str = "ACTIVE"

    def apply_credit(self, amount: float) -> float:
        if amount <= 0:
            raise ValueError("Credit amount must be positive")
        self.balance += amount
        return self.balance
