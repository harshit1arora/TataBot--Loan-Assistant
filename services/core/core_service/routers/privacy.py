"""Customer privacy requests. A durable tombstone revokes already issued tokens."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Literal
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Customer, PrivacyRequest
from ..security import Principal, get_principal

router = APIRouter(prefix="/v1/privacy", tags=["privacy"])


def customer(principal: Principal = Depends(get_principal)) -> str:
    if principal.scope != "customer":
        raise HTTPException(403, "Customer token required")
    return principal.customer_id


def present(row: PrivacyRequest | None) -> dict:
    return {"status": row.status if row else "active",
            "last_error": row.last_error if row else None,
            "external_erasure": "not_verified" if row and row.status == "local_erased" else None}


@router.get("")
def status(customer_id: str = Depends(customer), db: Session = Depends(get_db)):
    return present(db.get(PrivacyRequest, customer_id))


@router.post("/withdraw")
def withdraw(customer_id: str = Depends(customer), db: Session = Depends(get_db)):
    row = db.get(PrivacyRequest, customer_id)
    if not row:
        if not db.get(Customer, customer_id):
            raise HTTPException(404, "Customer not found")
        row = PrivacyRequest(customer_id=customer_id, status="withdrawn")
        db.add(row)
        db.flush()
    return present(row)


class ErasureConfirmation(BaseModel):
    confirm: Literal["ERASE"]


@router.post("/erase", status_code=202)
def erase(body: ErasureConfirmation, customer_id: str = Depends(customer), db: Session = Depends(get_db)):
    row = db.get(PrivacyRequest, customer_id)
    if not row:
        if not db.get(Customer, customer_id):
            raise HTTPException(404, "Customer not found")
        row = PrivacyRequest(customer_id=customer_id, status="erasure_pending")
        db.add(row)
    elif row.status != "local_erased":
        row.status = "erasure_pending"
        row.last_error = None
    db.flush()
    return present(row)
