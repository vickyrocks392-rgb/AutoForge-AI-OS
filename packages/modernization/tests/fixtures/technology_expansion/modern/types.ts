// TypeScript interfaces and domain types
export interface AccountRecord {
    accountId: string;
    accountNumber: string;
    balance: number;
    status: 'ACTIVE' | 'SUSPENDED' | 'CLOSED';
    openedDate: string;
}

export type AccountMap = Map<string, AccountRecord>;

export function calculateTotalBalance(accounts: AccountRecord[]): number {
    return accounts.reduce((acc, curr) => acc + curr.balance, 0.0);
}
