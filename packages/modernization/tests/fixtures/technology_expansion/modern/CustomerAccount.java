package com.autoforge.account;

public record CustomerAccount(
    String accountId,
    String customerId,
    double balance,
    String status
) {
    public boolean isActive() {
        return "ACTIVE".equalsIgnoreCase(status);
    }
}
