"""Customer records and the demo seed set."""
from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import NotFoundError
from ..models import Customer
from ..money import rupees_to_paise

DEMO_CUSTOMERS = [
    # id, name, age, city, phone, email, pre_approved_limit_rupees, salary_rupees, score
    ("CUST001", "Asha Verma", 32, "Pune", "9810000001", "asha@example.com", 300_000, 60_000, 745),
    ("CUST002", "Rahul Sharma", 29, "Delhi", "9810000002", "rahul@example.com", 200_000, 45_000, 712),
    ("CUST003", "Sneha Iyer", 35, "Bengaluru", "9810000003", "sneha@example.com", 400_000, 85_000, 780),
    ("CUST004", "Vikram Singh", 40, "Lucknow", "9810000004", "vikram@example.com", 150_000, 30_000, 690),
    ("CUST005", "Nisha Patel", 27, "Ahmedabad", "9810000005", "nisha@example.com", 250_000, 52_000, 710),
    ("CUST006", "Arjun Rao", 31, "Hyderabad", "9810000006", "arjun@example.com", 350_000, 70_000, 760),
    ("CUST007", "Meera Desai", 30, "Surat", "9810000007", "meera@example.com", 180_000, 40_000, 695),
    ("CUST008", "Karan Mehta", 33, "Mumbai", "9810000008", "karan@example.com", 320_000, 65_000, 735),
    ("CUST009", "Priya Nair", 28, "Kochi", "9810000009", "priya@example.com", 280_000, 48_000, 725),
    ("CUST010", "Sourav Ghosh", 36, "Kolkata", "9810000010", "sourav@example.com", 500_000, 90_000, 790),
]


def seed(db: Session) -> int:
    """Idempotent: inserts only the customers that are missing."""
    existing = {cid for (cid,) in db.execute(select(Customer.id))}
    added = 0
    for cid, name, age, city, phone, email, limit, salary, score in DEMO_CUSTOMERS:
        if cid in existing:
            continue
        db.add(
            Customer(
                id=cid,
                name=name,
                age=age,
                city=city,
                phone=phone,
                email=email,
                pre_approved_limit_paise=rupees_to_paise(limit),
                declared_salary_paise=rupees_to_paise(salary),
                credit_score=score,
            )
        )
        added += 1
    db.flush()
    return added


def get_or_404(db: Session, customer_id: str) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError("Customer not found.")
    return customer


Band = Literal["excellent", "good", "fair"]


def credit_score_band(score: int) -> Band:
    """Coarse bands are all the LLM ever sees — never the number itself."""
    if score >= 760:
        return "excellent"
    if score >= 720:
        return "good"
    return "fair"
