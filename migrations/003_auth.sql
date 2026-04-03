-- Ultra Job Agent — Authentication & user management (run after 002_features.sql)

CREATE TABLE IF NOT EXISTS users (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email           TEXT UNIQUE NOT NULL,
  password_hash   TEXT NOT NULL,
  full_name       TEXT NOT NULL DEFAULT '',
  role            TEXT NOT NULL DEFAULT 'user',   -- 'user' | 'admin'
  is_active       BOOLEAN DEFAULT TRUE,
  last_login_at   TIMESTAMPTZ,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Each user can store their own preferences / config overrides
CREATE TABLE IF NOT EXISTS user_preferences (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
  key             TEXT NOT NULL,
  value           TEXT NOT NULL,
  updated_at      TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, key)
);

-- Resume uploads linked to a user
CREATE TABLE IF NOT EXISTS resume_uploads (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
  filename        TEXT NOT NULL,
  file_path       TEXT NOT NULL,
  file_size       INTEGER DEFAULT 0,
  content_text    TEXT,                           -- extracted plain text for LLM
  is_primary      BOOLEAN DEFAULT FALSE,
  uploaded_at     TIMESTAMPTZ DEFAULT NOW()
);

-- Track salary estimates more precisely
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS salary_currency TEXT DEFAULT 'INR';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS remote_type TEXT DEFAULT 'unknown';  -- 'remote' | 'hybrid' | 'onsite' | 'unknown'
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS experience_min INTEGER;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS experience_max INTEGER;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS is_duplicate BOOLEAN DEFAULT FALSE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS duplicate_of UUID REFERENCES jobs(id);

-- Application tracking improvements
ALTER TABLE applications ADD COLUMN IF NOT EXISTS follow_up_count INTEGER DEFAULT 0;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS last_follow_up_at TIMESTAMPTZ;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS interview_date TIMESTAMPTZ;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS interview_type TEXT;  -- 'phone' | 'video' | 'onsite' | 'take_home'
ALTER TABLE applications ADD COLUMN IF NOT EXISTS rejection_reason TEXT;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS salary_offered BIGINT;

-- Auto-update triggers
DROP TRIGGER IF EXISTS trg_users_updated ON users;
CREATE TRIGGER trg_users_updated
  BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Indexes
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_resume_uploads_user ON resume_uploads(user_id);
CREATE INDEX IF NOT EXISTS idx_user_prefs_user ON user_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_remote_type ON jobs(remote_type);
CREATE INDEX IF NOT EXISTS idx_jobs_duplicate ON jobs(is_duplicate);
CREATE INDEX IF NOT EXISTS idx_apps_interview_date ON applications(interview_date);
