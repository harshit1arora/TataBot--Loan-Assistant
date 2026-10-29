"""In-memory CRM store.

A mock CRM is a remote system; persistence is out of scope. Interactions are append-only
for the lifetime of the process, which is enough for the agent workflows that read them.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Same ten customers the lending core seeds, so ids line up across the demo.
CUSTOMERS: list[dict] = [
    {"id": "CUST001", "name": "Asha Verma", "age": 32, "city": "Pune", "phone": "9810000001",
     "email": "asha@example.com", "monthly_income_paise": 6_000_000, "employment": "salaried",
     "employer": "Infosys", "credit_score": 745},
    {"id": "CUST002", "name": "Rahul Sharma", "age": 29, "city": "Delhi", "phone": "9810000002",
     "email": "rahul@example.com", "monthly_income_paise": 4_500_000, "employment": "salaried",
     "employer": "TCS", "credit_score": 712},
    {"id": "CUST003", "name": "Sneha Iyer", "age": 35, "city": "Bengaluru", "phone": "9810000003",
     "email": "sneha@example.com", "monthly_income_paise": 8_500_000, "employment": "salaried",
     "employer": "Wipro", "credit_score": 780},
    {"id": "CUST004", "name": "Vikram Singh", "age": 40, "city": "Lucknow", "phone": "9810000004",
     "email": "vikram@example.com", "monthly_income_paise": 3_000_000, "employment": "self_employed",
     "employer": "Singh Traders", "credit_score": 690},
    {"id": "CUST005", "name": "Nisha Patel", "age": 27, "city": "Ahmedabad", "phone": "9810000005",
     "email": "nisha@example.com", "monthly_income_paise": 5_200_000, "employment": "salaried",
     "employer": "Zydus", "credit_score": 710},
    {"id": "CUST006", "name": "Arjun Rao", "age": 31, "city": "Hyderabad", "phone": "9810000006",
     "email": "arjun@example.com", "monthly_income_paise": 7_000_000, "employment": "salaried",
     "employer": "Deloitte", "credit_score": 760},
    {"id": "CUST007", "name": "Meera Desai", "age": 30, "city": "Surat", "phone": "9810000007",
     "email": "meera@example.com", "monthly_income_paise": 4_000_000, "employment": "self_employed",
     "employer": "Desai Textiles", "credit_score": 695},
    {"id": "CUST008", "name": "Karan Mehta", "age": 33, "city": "Mumbai", "phone": "9810000008",
     "email": "karan@example.com", "monthly_income_paise": 6_500_000, "employment": "salaried",
     "employer": "HDFC", "credit_score": 735},
    {"id": "CUST009", "name": "Priya Nair", "age": 28, "city": "Kochi", "phone": "9810000009",
     "email": "priya@example.com", "monthly_income_paise": 4_800_000, "employment": "salaried",
     "employer": "Cognizant", "credit_score": 725},
    {"id": "CUST010", "name": "Sourav Ghosh", "age": 36, "city": "Kolkata", "phone": "9810000010",
     "email": "sourav@example.com", "monthly_income_paise": 9_000_000, "employment": "salaried",
     "employer": "ITC", "credit_score": 790},
]


@dataclass
class Interaction:
    id: str
    customer_id: str
    channel: str
    summary: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class CrmStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.customers: dict[str, dict] = {
            row["id"]: {
                **row,
                "kyc": {"phone_verified": True, "address_verified": True, "pan_verified": False},
            }
            for row in CUSTOMERS
        }
        self.interactions: list[Interaction] = []

    def list_customers(self) -> list[dict]:
        return list(self.customers.values())

    def get(self, customer_id: str) -> dict | None:
        return self.customers.get(customer_id)

    def set_kyc(self, customer_id: str, field: str, value: bool) -> dict | None:
        with self._lock:
            customer = self.customers.get(customer_id)
            if customer is None:
                return None
            customer["kyc"][field] = value
            return customer

    def add_interaction(self, customer_id: str, channel: str, summary: str) -> Interaction | None:
        with self._lock:
            if customer_id not in self.customers:
                return None
            record = Interaction(
                id=uuid.uuid4().hex[:12],
                customer_id=customer_id,
                channel=channel,
                summary=summary[:500],
            )
            self.interactions.append(record)
            return record

    def list_interactions(self, customer_id: str) -> list[Interaction]:
        return [row for row in self.interactions if row.customer_id == customer_id]


store = CrmStore()
