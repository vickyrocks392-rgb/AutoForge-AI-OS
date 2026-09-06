import React, { useState } from 'react';

export function AccountCard({ account, onRefresh }) {
    const [loading, setLoading] = useState(false);

    const handleRefresh = async () => {
        setLoading(true);
        if (onRefresh) await onRefresh(account.accountId);
        setLoading(false);
    };

    return (
        <div className="account-card" data-testid="account-card">
            <h3 className="account-title">Account #{account.accountNumber}</h3>
            <p className="account-balance">Balance: ${account.balance.toFixed(2)}</p>
            <span className={`badge ${account.status.toLowerCase()}`}>{account.status}</span>
            <button onClick={handleRefresh} disabled={loading} className="btn-refresh">
                {loading ? 'Refreshing...' : 'Refresh'}
            </button>
        </div>
    );
}
