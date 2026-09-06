"""FastAPI application with typed routes and Pydantic schemas."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Modernized Account API", version="1.0.0")

class AccountDTO(BaseModel):
    account_id: str
    customer_id: str
    balance: float = Field(ge=0.0)
    status: str = "ACTIVE"

@app.get("/api/v1/accounts/{account_id}", response_model=AccountDTO)
async def get_account(account_id: str) -> AccountDTO:
    if not account_id:
        raise HTTPException(status_code=400, detail="Invalid account id")
    return AccountDTO(account_id=account_id, customer_id="CUST-001", balance=1250.75, status="ACTIVE")
