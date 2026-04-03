-- =============================================================================
-- Migration 004: Multi-user SaaS — profiles, onboarding, RLS on all tables
-- Run in: Supabase Dashboard → SQL Editor → New query → paste → Run
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. PROFILES — one row per auth.users entry, holds all per-user settings
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS profiles (
  id                   UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email                TEXT,
  full_name            TEXT,
  phone                TEXT,
  location             TEXT,
  linkedin_url         TEXT,
  github_url           TEXT,
  years_experience     INTEGER DEFAULT 0,
  current_title        TEXT,
  summary              TEXT,
  skills               JSONB DEFAULT '[]',           -- ["Python", "FastAPI", ...]
  education            JSONB DEFAULT '[]',           -- [{degree, institution, year}]
  -- Job search prefs
  search_keywords      TEXT DEFAULT 'Python Developer,Backend Engineer',
  search_locations     TEXT DEFAULT 'Bangalore,Remote',
  work_type            TEXT DEFAULT 'any',           -- remote|hybrid|onsite|any
  salary_min_inr       BIGINT DEFAULT 1200000,
  match_threshold      INTEGER DEFAULT 75,
  max_apps_per_day     INTEGER DEFAULT 15,
  exclude_companies    TEXT DEFAULT '',
  exclude_keywords     TEXT DEFAULT '',
  prefer_companies     TEXT DEFAULT '',
  -- Agent control
  agent_active         BOOLEAN DEFAULT FALSE,
  onboarding_complete  BOOLEAN DEFAULT FALSE,
  created_at           TIMESTAMPTZ DEFAULT NOW(),
  updated_at           TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 2. ONBOARDING STATE — tracks chatbot conversation per user
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS onboarding_state (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID REFERENCES auth.users(id) ON DELETE CASCADE UNIQUE,
  step         TEXT NOT NULL DEFAULT 'name',  -- name|phone|location|linkedin|github|resume|skills|salary|keywords|locations|work_type|done
  messages     JSONB DEFAULT '[]',            -- [{role: user|bot, text, ts}]
  collected    JSONB DEFAULT '{}',            -- fields collected so far
  updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 3. ADD user_id TO EXISTING TABLES (idempotent)
-- ---------------------------------------------------------------------------
ALTER TABLE jobs            ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE applications    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE agent_runs      ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE state_log       ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE resume_uploads  ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

-- ---------------------------------------------------------------------------
-- 4. INDEXES on user_id for fast per-user queries
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_jobs_user_id         ON jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_apps_user_id         ON applications(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_user_id   ON agent_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_resume_user_id       ON resume_uploads(user_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_user_id   ON onboarding_state(user_id);

-- ---------------------------------------------------------------------------
-- 5. TRIGGER — auto-create profile row when a user signs up via Supabase Auth
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.profiles (id, email, full_name)
  VALUES (
    NEW.id,
    NEW.email,
    COALESCE(NEW.raw_user_meta_data->>'full_name', split_part(NEW.email, '@', 1))
  )
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO public.onboarding_state (user_id, step)
  VALUES (NEW.id, 'name')
  ON CONFLICT (user_id) DO NOTHING;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();

-- auto-update updated_at on profiles
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_profiles_updated ON profiles;
CREATE TRIGGER trg_profiles_updated
  BEFORE UPDATE ON profiles FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_onboarding_updated ON onboarding_state;
CREATE TRIGGER trg_onboarding_updated
  BEFORE UPDATE ON onboarding_state FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 6. ENABLE ROW LEVEL SECURITY
-- ---------------------------------------------------------------------------
ALTER TABLE profiles           ENABLE ROW LEVEL SECURITY;
ALTER TABLE onboarding_state   ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs               ENABLE ROW LEVEL SECURITY;
ALTER TABLE applications       ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_runs         ENABLE ROW LEVEL SECURITY;
ALTER TABLE state_log          ENABLE ROW LEVEL SECURITY;
ALTER TABLE resume_uploads     ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- 7. RLS POLICIES
-- ---------------------------------------------------------------------------

-- profiles: users see/edit only their own
DROP POLICY IF EXISTS "profiles_select_own" ON profiles;
CREATE POLICY "profiles_select_own" ON profiles
  FOR SELECT USING (auth.uid() = id);

DROP POLICY IF EXISTS "profiles_update_own" ON profiles;
CREATE POLICY "profiles_update_own" ON profiles
  FOR UPDATE USING (auth.uid() = id);

DROP POLICY IF EXISTS "profiles_insert_own" ON profiles;
CREATE POLICY "profiles_insert_own" ON profiles
  FOR INSERT WITH CHECK (auth.uid() = id);

-- onboarding_state
DROP POLICY IF EXISTS "onboarding_select_own" ON onboarding_state;
CREATE POLICY "onboarding_select_own" ON onboarding_state
  FOR ALL USING (auth.uid() = user_id);

-- jobs
DROP POLICY IF EXISTS "jobs_select_own" ON jobs;
CREATE POLICY "jobs_select_own" ON jobs
  FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "jobs_insert_own" ON jobs;
CREATE POLICY "jobs_insert_own" ON jobs
  FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "jobs_update_own" ON jobs;
CREATE POLICY "jobs_update_own" ON jobs
  FOR UPDATE USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "jobs_delete_own" ON jobs;
CREATE POLICY "jobs_delete_own" ON jobs
  FOR DELETE USING (auth.uid() = user_id);

-- applications
DROP POLICY IF EXISTS "apps_select_own" ON applications;
CREATE POLICY "apps_select_own" ON applications
  FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "apps_insert_own" ON applications;
CREATE POLICY "apps_insert_own" ON applications
  FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "apps_update_own" ON applications;
CREATE POLICY "apps_update_own" ON applications
  FOR UPDATE USING (auth.uid() = user_id);

-- agent_runs
DROP POLICY IF EXISTS "agent_runs_own" ON agent_runs;
CREATE POLICY "agent_runs_own" ON agent_runs
  FOR ALL USING (auth.uid() = user_id);

-- state_log
DROP POLICY IF EXISTS "state_log_own" ON state_log;
CREATE POLICY "state_log_own" ON state_log
  FOR ALL USING (auth.uid() = user_id);

-- resume_uploads
DROP POLICY IF EXISTS "resume_uploads_own" ON resume_uploads;
CREATE POLICY "resume_uploads_own" ON resume_uploads
  FOR ALL USING (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- Done. Verify with:
-- SELECT tablename, rowsecurity FROM pg_tables
-- WHERE schemaname = 'public' ORDER BY tablename;
-- ---------------------------------------------------------------------------
