ALTER TABLE logs ADD COLUMN request_text TEXT;
ALTER TABLE logs ADD COLUMN response_text TEXT;

PRAGMA user_version = 9;
