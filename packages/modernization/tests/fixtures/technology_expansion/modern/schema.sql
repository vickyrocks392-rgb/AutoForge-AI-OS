-- Relational SQL DDL and schema definition
CREATE TABLE IF NOT EXISTS modern_accounts (
    account_id VARCHAR(36) PRIMARY KEY,
    account_number VARCHAR(20) NOT NULL UNIQUE,
    customer_id VARCHAR(36) NOT NULL,
    balance DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    status VARCHAR(10) NOT NULL CHECK(status IN ('ACTIVE', 'SUSPENDED', 'CLOSED')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_acc_customer ON modern_accounts (customer_id);

INSERT INTO modern_accounts (account_id, account_number, customer_id, balance, status)
VALUES ('001-acc', '1234567890', 'cust-01', 2500.50, 'ACTIVE');
