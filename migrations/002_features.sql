-- NaukriMitra-AI / Ultra Job Agent — extended features (run after 001_initial.sql)

ALTER TABLE applications ADD COLUMN IF NOT EXISTS ats_score INTEGER DEFAULT 0;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS recruiter_email TEXT;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS outreach_sent BOOLEAN DEFAULT FALSE;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS outreach_sent_at TIMESTAMPTZ;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS outreach_subject TEXT;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS interview_prep JSONB DEFAULT '{}';
ALTER TABLE applications ADD COLUMN IF NOT EXISTS resume_variant TEXT DEFAULT 'base';

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS salary_estimate TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS red_flags JSONB DEFAULT '[]';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ats_keywords JSONB DEFAULT '[]';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS match_explanation TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS why_apply TEXT;

CREATE TABLE IF NOT EXISTS resume_variants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  variant_name TEXT NOT NULL,
  content TEXT NOT NULL,
  applications_count INTEGER DEFAULT 0,
  response_count INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recruiter_outreach (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  application_id UUID REFERENCES applications(id) ON DELETE CASCADE,
  to_email TEXT,
  subject TEXT,
  body TEXT,
  sent_at TIMESTAMPTZ,
  opened BOOLEAN DEFAULT FALSE,
  replied BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_apps_ats ON applications(ats_score DESC);
CREATE INDEX IF NOT EXISTS idx_apps_resume_variant ON applications(resume_variant);
CREATE INDEX IF NOT EXISTS idx_outreach_app ON recruiter_outreach(application_id);
