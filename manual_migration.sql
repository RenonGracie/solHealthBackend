-- Manual Migration Script for Progressive Logger Fields
-- This is a BACKUP - your system uses AUTO_MIGRATE so this should not be needed!
-- Only run this manually if AUTO_MIGRATE fails for some reason.

-- Add new columns to client_responses table
ALTER TABLE client_responses ADD COLUMN IF NOT EXISTS therapist_gender_preference VARCHAR;
ALTER TABLE client_responses ADD COLUMN IF NOT EXISTS browser_timezone VARCHAR;
ALTER TABLE client_responses ADD COLUMN IF NOT EXISTS insurance_provider_corrected BOOLEAN DEFAULT FALSE;
ALTER TABLE client_responses ADD COLUMN IF NOT EXISTS algorithm_suggested_therapist_id VARCHAR;
ALTER TABLE client_responses ADD COLUMN IF NOT EXISTS algorithm_suggested_therapist_name VARCHAR;
ALTER TABLE client_responses ADD COLUMN IF NOT EXISTS algorithm_suggested_therapist_score FLOAT;
ALTER TABLE client_responses ADD COLUMN IF NOT EXISTS alternative_therapists_offered JSONB;
ALTER TABLE client_responses ADD COLUMN IF NOT EXISTS user_chose_alternative BOOLEAN DEFAULT FALSE;
ALTER TABLE client_responses ADD COLUMN IF NOT EXISTS therapist_selection_timestamp TIMESTAMPTZ;

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS ix_client_responses_algorithm_suggested ON client_responses(algorithm_suggested_therapist_id);
CREATE INDEX IF NOT EXISTS ix_client_responses_user_chose_alternative ON client_responses(user_chose_alternative);
CREATE INDEX IF NOT EXISTS ix_client_responses_selection_timestamp ON client_responses(therapist_selection_timestamp);

-- Verify the columns were added
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'client_responses'
AND column_name IN (
    'therapist_gender_preference',
    'browser_timezone',
    'insurance_provider_corrected',
    'algorithm_suggested_therapist_id',
    'algorithm_suggested_therapist_name',
    'algorithm_suggested_therapist_score',
    'alternative_therapists_offered',
    'user_chose_alternative',
    'therapist_selection_timestamp'
)
ORDER BY column_name;
