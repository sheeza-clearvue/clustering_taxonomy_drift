'use strict';

const { Pool } = require('pg');
const path = require('path');

require('dotenv').config({ path: path.resolve(__dirname, '../.env') });

const pool = new Pool({
  host:     process.env.LOCAL_PG_HOST     || '127.0.0.1',
  port:     parseInt(process.env.LOCAL_PG_PORT || '5432', 10),
  database: process.env.LOCAL_PG_DB,
  user:     process.env.LOCAL_PG_USER,
  password: process.env.LOCAL_PG_PASSWORD,
  max: 10,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 5000,
});

pool.on('error', (err) => {
  console.error('Unexpected idle-client error:', err.message);
});

module.exports = pool;
