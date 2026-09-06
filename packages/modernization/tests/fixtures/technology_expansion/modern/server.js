// Express.js server and API routing fixture
const express = require('express');
const app = express();

app.use(express.json());

const accounts = [
    { accountId: 'ACC-01', accountNumber: '111122223333', balance: 4500.50, status: 'ACTIVE' },
    { accountId: 'ACC-02', accountNumber: '444455556666', balance: 120.00, status: 'SUSPENDED' }
];

app.get('/api/v1/accounts', (req, res) => {
    res.json({ data: accounts, total: accounts.length });
});

app.get('/api/v1/accounts/:id', (req, res) => {
    const acc = accounts.find(a => a.accountId === req.params.id);
    if (!acc) return res.status(404).json({ error: 'Account not found' });
    res.json(acc);
});

module.exports = app;
