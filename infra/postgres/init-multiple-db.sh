#!/bin/bash
# Create multiple PostgreSQL databases on first start
set -e
set -u

if [ -n "${POSTGRES_MULTIPLE_DATABASES:-}" ]; then
    echo "Creating multiple databases: ${POSTGRES_MULTIPLE_DATABASES}"
    for db in $(echo "${POSTGRES_MULTIPLE_DATABASES}" | tr ',' ' '); do
        echo "Creating database: ${db}"
        psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" <<-EOSQL
            CREATE DATABASE "${db}";
            GRANT ALL PRIVILEGES ON DATABASE "${db}" TO "${POSTGRES_USER}";
EOSQL
        # Create schema per service
        psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${db}" <<-EOSQL
            CREATE SCHEMA IF NOT EXISTS auth;
            CREATE SCHEMA IF NOT EXISTS catalog;
            CREATE SCHEMA IF NOT EXISTS order_svc;
            CREATE SCHEMA IF NOT EXISTS payment_svc;
            CREATE SCHEMA IF NOT EXISTS notification;
            CREATE SCHEMA IF NOT EXISTS audit;
EOSQL
    done
    echo "Multiple databases created"
fi
