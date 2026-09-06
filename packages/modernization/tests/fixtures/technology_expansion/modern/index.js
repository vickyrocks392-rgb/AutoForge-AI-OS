// Node.js application entrypoint
const fs = require('fs');
const path = require('path');

function getApplicationConfig() {
    return {
        service: 'modernized-account-node',
        version: '1.0.0',
        environment: process.env.NODE_ENV || 'development'
    };
}

module.exports = { getApplicationConfig };
