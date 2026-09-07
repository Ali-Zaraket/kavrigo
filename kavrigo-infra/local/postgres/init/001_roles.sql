-- Kavrigo local PostgreSQL bootstrap: roles only.
--
-- The schema is owned by Alembic (kavrigo-platform/services/api/migrations). This file creates
-- the separation that makes row-level security meaningful:
--
--   kavrigo      — the container superuser. Runs migrations. Owns the tables.
--   kavrigo_app  — what the application connects as. NOT a superuser, NOT the table owner,
--                  and without BYPASSRLS, so every policy actually applies to it.
--
-- Superusers and BYPASSRLS roles ignore row-level security entirely. An application connecting
-- as the superuser would pass every isolation test while providing no isolation at all — which
-- is precisely the failure this split prevents.
--
-- The password here is a local development value. Real environments provision this role through
-- infrastructure-as-code with credentials from Secrets Manager (MASTER_BUILD_SPEC.md §24.3).

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kavrigo_app') THEN
    CREATE ROLE kavrigo_app
      LOGIN
      PASSWORD 'kavrigo_local_dev'
      NOSUPERUSER
      NOCREATEDB
      NOCREATEROLE
      NOBYPASSRLS
      NOINHERIT;
  END IF;
END
$$;

GRANT CONNECT ON DATABASE kavrigo TO kavrigo_app;

-- Table-level grants are issued by the migration that creates each table, so a new table is
-- unreachable by the application until its migration deliberately grants access.
