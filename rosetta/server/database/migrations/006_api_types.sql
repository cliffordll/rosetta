-- Rosetta schema v6 · remove API type dictionary tables
-- API endpoints are fixed in code by ServerApi. base_url stores the upstream API prefix.

DROP TABLE IF EXISTS api_formats;
DROP TABLE IF EXISTS api_types;

PRAGMA user_version = 6;