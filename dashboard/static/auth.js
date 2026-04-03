/**
 * auth.js — Supabase Auth login/signup + onboarding chatbot
 *
 * Loads the Supabase JS client from CDN (no build step needed).
 * On DOMContentLoaded: checks session → shows auth overlay or onboarding or dashboard.
 */

// ---------------------------------------------------------------------------
// Supabase client init (loaded from CDN in index.html head)
// We load it dynamically to avoid bundling
// ---------------------------------------------------------------------------
let _supabase = null;

async function getSupabase() {
  if (_supabase) return _supabase;
  // Load Supabase JS v2 from CDN if not already present
  if (!window.supabase) {
    await new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js';
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  const SUPABASE_URL = 'https://ftaffgnzvihgquhlybzl.supabase.co';
  // Use the publishable/anon key for client-side auth only
  const SUPABASE_ANON_KEY = window.__SUPABASE_ANON_KEY__ || '';
  _supabase = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  return _supabase;
}

// Store current session token for API calls
let _authToken = localStorage.getItem('uja_token') || '';
let _currentUser = null;

function setToken(token) {
  _authToken = token;
  if (token) {
    localStorage.setItem('uja_token', token);
  } else {
    localStorage.removeItem('uja_token');
  }
}

// Patch all fetch calls to include auth token
const _origFetch = window.fetch;
window.fetch = function(url, opts = {}) {
  if (_authToken && typeof url === 'string' && url.startsWith('/api/')) {
    opts.headers = opts.headers || {};
    opts.headers['Authorization'] = `Bearer ${_authToken}`;
  }
  return _origFetch(url, opts);
};

// ---------------------------------------------------------------------------
// Startup — check auth state
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
  try {
    const sb = await getSupabase();
    const { data: { session } } = await sb.auth.getSession();

    if (!session) {
      showAuthOverlay();
      return;
    }

    _currentUser = session.user;
    setToken(session.access_token);
    await checkOnboardingAndProceed();

    // Keep token fresh
    sb.auth.onAuthStateChange((_event, session) => {
      if (session) {
        setToken(session.access_token);
      } else {
        setToken('');
        showAuthOverlay();
      }
    });
  } catch (err) {
    console.warn('Auth init failed — running in no-auth mode:', err);
    // Fallback: show dashboard without auth (dev mode)
  }
});

async function checkOnboardingAndProceed() {
  try {
    const res = await fetch('/api/onboarding/state');
    if (!res.ok) return;
    const state = await res.json();
    if (state.step !== 'done') {
      showOnboardingModal(state);
    } else {
      hideBothOverlays();
    }
  } catch {
    hideBothOverlays();
  }
}

// ---------------------------------------------------------------------------
// Auth overlay
// ---------------------------------------------------------------------------
function showAuthOverlay() {
  document.getElementById('auth-overlay').style.display = 'flex';
  document.getElementById('onboarding-modal').style.display = 'none';
}

function hideBothOverlays() {
  document.getElementById('auth-overlay').style.display = 'none';
  document.getElementById('onboarding-modal').style.display = 'none';
}

function showAuthTab(tab) {
  document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('login-form').style.display = tab === 'login' ? '' : 'none';
  document.getElementById('signup-form').style.display = tab === 'signup' ? '' : 'none';
}

async function handleLogin(e) {
  e.preventDefault();
  const btn = document.getElementById('login-btn');
  const errEl = document.getElementById('login-error');
  errEl.textContent = '';
  btn.textContent = 'Signing in…';
  btn.disabled = true;

  try {
    const sb = await getSupabase();
    const email = document.getElementById('login-email').value.trim();
    const password = document.getElementById('login-password').value;
    const { data, error } = await sb.auth.signInWithPassword({ email, password });

    if (error) throw error;
    _currentUser = data.user;
    setToken(data.session.access_token);
    await checkOnboardingAndProceed();
  } catch (err) {
    errEl.textContent = err.message || 'Login failed. Check your credentials.';
  } finally {
    btn.textContent = 'Sign In';
    btn.disabled = false;
  }
}

async function handleSignup(e) {
  e.preventDefault();
  const btn = document.getElementById('signup-btn');
  const errEl = document.getElementById('signup-error');
  errEl.textContent = '';
  btn.textContent = 'Creating account…';
  btn.disabled = true;

  try {
    const sb = await getSupabase();
    const name = document.getElementById('signup-name').value.trim();
    const email = document.getElementById('signup-email').value.trim();
    const password = document.getElementById('signup-password').value;

    const { data, error } = await sb.auth.signUp({
      email,
      password,
      options: { data: { full_name: name } },
    });

    if (error) throw error;

    if (data.session) {
      // Auto-confirmed (email confirm disabled in Supabase)
      _currentUser = data.user;
      setToken(data.session.access_token);
      await checkOnboardingAndProceed();
    } else {
      errEl.style.color = '#22c55e';
      errEl.textContent = '✅ Check your email to confirm your account, then sign in.';
    }
  } catch (err) {
    errEl.textContent = err.message || 'Signup failed. Try again.';
  } finally {
    btn.textContent = 'Create Account';
    btn.disabled = false;
  }
}

// Expose logout globally
window.logout = async function() {
  const sb = await getSupabase();
  await sb.auth.signOut();
  setToken('');
  _currentUser = null;
  showAuthOverlay();
};

// ---------------------------------------------------------------------------
// Onboarding chatbot
// ---------------------------------------------------------------------------
const OB_STEPS = [
  'name','phone','location','linkedin','github',
  'resume','skills','salary','keywords','locations','work_type','done'
];

let _obState = { step: 'name', messages: [], collected: {} };

function showOnboardingModal(state) {
  document.getElementById('auth-overlay').style.display = 'none';
  document.getElementById('onboarding-modal').style.display = 'flex';
  _obState = state;
  renderChat(state.messages);
  updateObProgress(state.step);
  updateObInputVisibility(state.step);
}

function skipOnboarding() {
  hideBothOverlays();
}

function renderChat(messages) {
  const chat = document.getElementById('ob-chat');
  chat.innerHTML = '';
  (messages || []).forEach(m => appendChatMsg(m.role, m.text, false));
  chat.scrollTop = chat.scrollHeight;
}

function appendChatMsg(role, text, scroll = true) {
  const chat = document.getElementById('ob-chat');
  const div = document.createElement('div');
  div.className = `ob-msg ob-msg-${role}`;
  // Simple markdown: **bold**
  div.innerHTML = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
  chat.appendChild(div);
  if (scroll) chat.scrollTop = chat.scrollHeight;
}

function updateObProgress(step) {
  const idx = OB_STEPS.indexOf(step);
  const pct = Math.round((idx / (OB_STEPS.length - 1)) * 100);
  document.getElementById('ob-progress-fill').style.width = `${pct}%`;
}

function updateObInputVisibility(step) {
  const inputRow = document.getElementById('ob-input-row');
  const resumeArea = document.getElementById('ob-resume-upload');
  if (step === 'resume') {
    inputRow.style.display = 'none';
    resumeArea.style.display = '';
  } else if (step === 'done') {
    inputRow.style.display = 'none';
    resumeArea.style.display = 'none';
  } else {
    inputRow.style.display = '';
    resumeArea.style.display = 'none';
  }
}

async function sendOnboardingMessage() {
  const input = document.getElementById('ob-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';

  appendChatMsg('user', text);

  try {
    const res = await fetch('/api/onboarding/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();
    appendChatMsg('bot', data.bot_reply);
    _obState.step = data.step;
    _obState.collected = data.collected;
    updateObProgress(data.step);
    updateObInputVisibility(data.step);

    if (data.done) {
      setTimeout(() => {
        hideBothOverlays();
        if (window.showToast) window.showToast('🚀 Setup complete! You\'re ready to start.', 'success');
      }, 2000);
    }
  } catch (err) {
    appendChatMsg('bot', '⚠️ Error: ' + err.message);
  }
}

async function handleOnboardingResume(input) {
  const file = input.files[0];
  if (!file) return;

  const statusEl = document.getElementById('ob-upload-status');
  statusEl.textContent = '⏳ Uploading and parsing…';

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/api/onboarding/upload-resume', {
      method: 'POST',
      body: formData,
    });
    const data = await res.json();

    if (!res.ok) {
      statusEl.textContent = '❌ ' + (data.detail || 'Upload failed');
      return;
    }

    statusEl.textContent = `✅ Parsed ${data.skills?.length || 0} skills, ${data.experience_years || '?'} yrs exp`;

    // Re-fetch state to get updated messages from backend
    const stateRes = await fetch('/api/onboarding/state');
    const state = await stateRes.json();
    renderChat(state.messages);
    _obState = state;
    updateObProgress(state.step);
    updateObInputVisibility(state.step);
  } catch (err) {
    statusEl.textContent = '❌ ' + err.message;
  }
}
