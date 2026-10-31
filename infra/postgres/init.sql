SELECT 'CREATE DATABASE app' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='app')\gexec
SELECT 'CREATE DATABASE tracemind' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='tracemind')\gexec
