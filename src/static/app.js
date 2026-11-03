'use strict';
const $ = id => document.getElementById(id);
const state = { profile: null, csrf: '', email: '', authMode: 'login', verification: '', secret: '', secretNext: 'login', booted: false };
const protectedPages = new Set(['dashboard', 'keys', 'tokens', 'connection', 'security']);
const authPages = new Set(['login', 'register', 'recover', 'resend']);
let toastTimer;
class ApiError extends Error { constructor(message, status, code) { super(message); this.status = status; this.code = code; } }
function message(id, text, type = 'error') { const el = $(id); el.textContent = text; el.className = 'message ' + type; el.hidden = !text; }
function toast(text) { clearTimeout(toastTimer); $('toast').textContent = text; $('toast').hidden = false; toastTimer = setTimeout(() => { $('toast').hidden = true; }, 5500); }
function friendly(data, status) {
  const code = data.error || '';
  if (status === 401) return 'Sesi Anda berakhir. Silakan masuk kembali.';
  if (code === 'csrf_rejected') return 'Sesi halaman berubah. Muat ulang halaman dan coba kembali.';
  if (code === 'origin_rejected') return 'Alamat halaman ini belum diizinkan. Gunakan domain resmi situs.';
  if (status === 429) return data.message || (typeof code === 'string' && code.includes('percobaan') ? code : 'Terlalu banyak percobaan. Tunggu beberapa saat sebelum mencoba lagi.');
  if (status >= 500) return 'Layanan belum dapat memproses permintaan. Coba lagi sebentar; input Anda belum dikonfirmasi tersimpan.';
  return data.message || (typeof code === 'string' ? code : '') || 'Permintaan belum berhasil. Periksa isian Anda.';
}
async function refreshAccount() {
  const response = await fetch('/api/account/me', { credentials: 'same-origin', cache: 'no-store' });
  if (response.status === 401) { state.profile = null; state.csrf = ''; updateAccount(); return null; }
  let data; try { data = await response.json(); } catch { throw new ApiError('Respons layanan akun tidak valid.', response.status); }
  if (!response.ok) throw new ApiError(friendly(data, response.status), response.status, data.error);
  state.profile = data; state.csrf = data.csrf; state.email = data.user.email; updateAccount(); return data;
}
async function request(path, body, retry = true) {
  let response;
  try { response = await fetch(path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf }, body: JSON.stringify(body), signal: AbortSignal.timeout(45000) }); }
  catch { throw new ApiError('Koneksi terputus atau permintaan terlalu lama. Periksa status akun sebelum mencoba kembali.', 0); }
  let data; try { data = await response.json(); } catch { throw new ApiError('Server mengirim respons yang tidak dapat dibaca. Coba muat ulang halaman.', response.status); }
  if (response.status === 403 && data.error === 'csrf_rejected' && retry) {
    // This response guarantees no mutation ran. Refresh this tab's session once.
    const profile = await refreshAccount();
    if (profile) return request(path, body, false);
  }
  if (!response.ok) {
    if (response.status === 401) { state.profile = null; state.csrf = ''; $('savedKey').value = ''; updateAccount(); location.hash = 'login'; }
    throw new ApiError(friendly(data, response.status), response.status, data.error);
  }
  return data;
}
const account = (action, body) => request('/api/account/' + action, body);
async function busy(id, text, fn) { const button = $(id), previous = button.textContent; button.disabled = true; button.textContent = text; try { return await fn(); } finally { button.disabled = false; button.textContent = previous; } }
const date = seconds => new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Jakarta' }).format(new Date(seconds * 1000)) + ' WIB';
function hasKey(service = 'bps') { return state.profile?.credentials?.find(item => item.service === service); }
function updateAccount() {
  const data = state.profile;
  $('navAccount').textContent = data ? 'Akun saya' : 'Masuk / daftar'; $('navAccount').href = data ? '#dashboard' : '#login';
  $('explorerLoginNotice').hidden = Boolean(data);
  if (!data) return;
  $('sidebarEmail').textContent = data.user.email; $('profileEmail').textContent = data.user.email;
  const completed = 1 + Number(Boolean(hasKey())) + Number(data.tokens.length > 0);
  $('setupCount').textContent = completed + ' dari 3 selesai'; $('setupProgress').style.width = (completed / 3 * 100) + '%';
  $('setupKeyText').textContent = hasKey() ? 'API key BPS sudah tersimpan terenkripsi.' : 'Diperlukan agar server dapat mengambil data BPS untuk Anda.';
  $('setupTokenText').textContent = data.tokens.length ? data.tokens.length + ' token aktif. Kelola akses masing-masing klien.' : 'Token inilah yang Anda pasang pada klien AI.';
  updateKey(); renderTokens();
}
function updateKey() {
  const service = $('keyService').value, saved = hasKey(service);
  $('keyServiceTitle').textContent = service === 'bps' ? 'Web API BPS' : 'SDGs Access';
  $('keyBadge').textContent = saved ? 'Tersimpan terenkripsi' : 'Belum disimpan'; $('keyBadge').className = 'badge' + (saved ? '' : ' muted');
  $('keyState').textContent = saved ? 'Terakhir diperbarui ' + date(saved.updated) + '. Nilai key tidak ditampilkan kembali.' : 'Belum ada key untuk layanan ini.';
  $('keyInputLabel').textContent = saved ? 'API key pengganti' : 'API key baru';
  $('saveKey').textContent = saved ? 'Simpan pengganti' : 'Simpan API key';
  $('testKey').disabled = !saved; $('deleteKey').disabled = !saved;
}
function renderTokens() {
  const tokens = state.profile?.tokens || []; $('tokenCount').textContent = tokens.length + ' token';
  const rows = tokens.map(token => {
    const row = document.createElement('div'); row.className = 'token-row';
    const body = document.createElement('div'); body.className = 'body';
    const title = document.createElement('strong'); title.textContent = token.label;
    const info = document.createElement('p'); info.textContent = 'Berakhir ' + date(token.expires);
    const button = document.createElement('button'); button.type = 'button'; button.className = 'danger'; button.textContent = 'Cabut'; button.setAttribute('aria-label', 'Cabut token ' + token.label);
    button.addEventListener('click', async () => {
      if (button.dataset.confirm !== 'yes') { button.dataset.confirm = 'yes'; button.textContent = 'Konfirmasi cabut'; setTimeout(() => { if (button.isConnected) { button.dataset.confirm = ''; button.textContent = 'Cabut'; } }, 6000); return; }
      button.disabled = true;
      try { await account('tokens', { revoke: token.id }); await refreshAccount(); toast('Token dicabut. Klien tersebut tidak dapat mengakses MCP lagi.'); }
      catch (error) { message('dashboardError', error.message); button.disabled = false; }
    });
    body.append(title, info); row.append(body, button); return row;
  });
  if (!rows.length) { const empty = document.createElement('div'); empty.className = 'empty'; empty.textContent = 'Belum ada token aktif. Buat token pertama untuk menghubungkan klien AI Anda.'; rows.push(empty); }
  $('tokenList').replaceChildren(...rows);
}
function setAuthMode(mode) {
  state.authMode = mode;
  const copy = {
    login: ['Selamat datang kembali.', 'Masuk untuk mengelola koneksi data Anda.', 'Masuk ke akun'],
    register: ['Mulai dari akun Anda.', 'Daftar, verifikasi email, lalu siapkan koneksi BPS.', 'Daftar dan kirim verifikasi'],
    recover: ['Pulihkan akses akun.', 'Masukkan kode pemulihan dan pilih password baru. Semua sesi dan token lama akan dicabut.', 'Reset password'],
    resend: ['Belum menerima email?', 'Gunakan email dan password akun Anda untuk meminta tautan verifikasi baru.', 'Kirim ulang email verifikasi']
  }[mode];
  $('authTitle').textContent = copy[0]; $('authIntro').textContent = copy[1]; $('authSubmit').textContent = copy[2];
  $('confirmGroup').hidden = !['register', 'recover'].includes(mode); $('passwordConfirm').required = !$('confirmGroup').hidden;
  $('recoveryGroup').hidden = mode !== 'recover'; $('recoveryCode').required = mode === 'recover';
  $('passwordHint').hidden = !['register', 'recover'].includes(mode); $('passwordLabel').textContent = mode === 'recover' ? 'Password baru' : 'Password';
  $('password').autocomplete = ['register', 'recover'].includes(mode) ? 'new-password' : 'current-password';
  $('tab-login').setAttribute('aria-current', mode === 'login' ? 'page' : 'false'); $('tab-register').setAttribute('aria-current', mode === 'register' ? 'page' : 'false');
  if (!$('email').value && state.email) $('email').value = state.email;
  $('password').value = ''; $('passwordConfirm').value = ''; $('recoveryCode').value = ''; message('authError', '');
}
function captureVerification() {
  const raw = location.hash.slice(1);
  if (raw.startsWith('verify=')) { state.verification = new URLSearchParams(raw).get('verify') || ''; history.replaceState(null, '', location.pathname + location.search + '#verify'); }
}
function route() {
  captureVerification();
  let page = location.hash.slice(1) || (state.profile ? 'dashboard' : 'home');
  if (!['home', 'explore', 'guide', 'wait', 'verify', 'secret', ...authPages, ...protectedPages].includes(page)) page = 'home';
  if (protectedPages.has(page) && !state.profile) { history.replaceState(null, '', '#login'); page = 'login'; }
  if (authPages.has(page) && state.profile) { history.replaceState(null, '', '#dashboard'); page = 'dashboard'; }
  if (page === 'secret' && !state.secret) { page = state.profile ? 'tokens' : 'login'; history.replaceState(null, '', '#' + page); }
  const view = authPages.has(page) ? 'auth' : protectedPages.has(page) ? 'dashboard' : page;
  document.querySelectorAll('main > section').forEach(el => { el.hidden = el.id !== 'view-' + view; });
  $('initialLoading').hidden = true;
  if (authPages.has(page)) setAuthMode(page);
  if (protectedPages.has(page)) {
    document.querySelectorAll('[data-dashboard-panel]').forEach(el => { el.hidden = el.id !== 'panel-' + page; });
    document.querySelectorAll('[data-panel]').forEach(el => el.setAttribute('aria-current', el.dataset.panel === page ? 'page' : 'false'));
  }
  if (page === 'verify') {
    $('verifyEmail').disabled = !state.verification;
    if (!state.verification) message('verifyMessage', 'Tautan tidak tersedia atau sudah digunakan. Masuk atau minta tautan baru.');
  }
  if (page === 'explore') $('explorerLoginNotice').hidden = Boolean(state.profile);
  window.scrollTo({ top: 0, behavior: 'instant' });
  document.title = (authPages.has(page) ? { login: 'Masuk', register: 'Daftar', recover: 'Pemulihan', resend: 'Verifikasi email' }[page] : protectedPages.has(page) ? 'Dashboard' : 'Ruang data') + ' · MCP Satu Data Aceh';
}
function showSecret(value, type, next) {
  state.secret = value; state.secretNext = next;
  $('secretTitle').textContent = type === 'token' ? 'Token MCP Anda siap.' : 'Simpan kode pemulihan.';
  $('secretIntro').textContent = type === 'token' ? 'Salin token ke pengaturan klien MCP. Token ini hanya ditampilkan sekali.' : 'Kode ini diperlukan jika lupa password. Simpan di pengelola password sebelum melanjutkan.';
  $('oneTimeSecret').textContent = value; $('copySecret').textContent = type === 'token' ? 'Salin token MCP' : 'Salin kode pemulihan';
  $('secretSaved').checked = false; $('secretContinue').disabled = true; location.hash = 'secret';
}
async function copy(text, label) { try { await navigator.clipboard.writeText(text); toast(label + ' disalin.'); } catch { toast('Clipboard tidak tersedia. Pilih dan salin teks secara manual.'); } }
$('secretSaved').addEventListener('change', () => { $('secretContinue').disabled = !$('secretSaved').checked; });
$('copySecret').addEventListener('click', () => copy(state.secret, 'Credential'));
$('secretContinue').addEventListener('click', () => { if (!$('secretSaved').checked) return; state.secret = ''; $('oneTimeSecret').textContent = ''; location.hash = state.secretNext; });
$('authForm').addEventListener('submit', async event => {
  event.preventDefault(); message('authError', '');
  if (['register', 'recover'].includes(state.authMode) && $('password').value !== $('passwordConfirm').value) { message('authError', 'Kedua password belum sama. Periksa konfirmasi password.'); $('passwordConfirm').focus(); return; }
  const mode = state.authMode; state.email = $('email').value.trim();
  await busy('authSubmit', mode === 'login' ? 'Memeriksa akun…' : 'Memproses…', async () => {
    try {
      const data = await account(mode, { email: state.email, password: $('password').value, recovery_code: $('recoveryCode').value });
      $('password').value = ''; $('passwordConfirm').value = ''; $('recoveryCode').value = '';
      if (mode === 'login') { await refreshAccount(); location.hash = 'dashboard'; toast('Berhasil masuk. Selamat datang kembali.'); }
      else if (mode === 'register') {
        $('waitEmail').textContent = state.email; $('waitMessage').textContent = data.verification_sent ? 'Email telah diterima layanan pengirim. Periksa inbox dan spam.' : 'Akun berhasil dibuat, tetapi email belum dapat dikirim. Tunggu satu menit lalu gunakan Kirim ulang.';
        showSecret(data.recovery_code, 'recovery', 'wait');
      } else if (mode === 'recover') { state.profile = null; state.csrf = ''; updateAccount(); showSecret(data.recovery_code, 'recovery', 'login'); toast('Password diperbarui. Simpan kode pemulihan baru.'); }
      else { $('waitEmail').textContent = state.email; $('waitMessage').textContent = data.message; location.hash = 'wait'; }
    } catch (error) { message('authError', error.message); }
  });
});
$('verifyEmail').addEventListener('click', () => busy('verifyEmail', 'Mengonfirmasi…', async () => {
  try { await account('verify', { token: state.verification }); state.verification = ''; location.hash = state.profile ? 'dashboard' : 'login'; toast('Email terverifikasi. Anda sudah dapat masuk.'); }
  catch (error) { message('verifyMessage', error.message); }
}));
function keyInputError(value) {
  if (/^(https?:\/\/|bearer\s|authorization\s*:)/i.test(value)) return 'Tempel nilai API key saja, bukan URL atau header Authorization.';
  if (/\s/.test(value)) return 'Ada spasi atau baris baru di tengah key. Salin ulang nilai key dari akun BPS.';
  if (!/^[A-Za-z0-9._~+\/=-]{8,512}$/.test(value)) return 'Format key belum sesuai. Gunakan 8–512 karakter huruf, angka, atau simbol token yang didukung.';
  return '';
}
$('keyService').addEventListener('change', () => { $('savedKey').value = ''; $('keyFieldError').hidden = true; $('deleteKeyConfirm').hidden = true; message('keyFeedback', ''); updateKey(); });
$('keyForm').addEventListener('submit', async event => {
  event.preventDefault(); $('keyFieldError').hidden = true; $('savedKey').removeAttribute('aria-invalid');
  const value = $('savedKey').value.trim(), error = keyInputError(value);
  if (error) { $('keyFieldError').textContent = error; $('keyFieldError').hidden = false; $('savedKey').setAttribute('aria-invalid', 'true'); $('savedKey').focus(); return; }
  await busy('saveKey', 'Menyimpan terenkripsi…', async () => {
    try {
      const data = await account('credentials', { service: $('keyService').value, key: value });
      $('savedKey').value = '';
      if (state.profile && data.credentials) { state.profile.credentials = data.credentials; updateKey(); }
      message('keyFeedback', 'API key berhasil disimpan terenkripsi. Anda dapat menguji koneksi BPS sekarang.', '');
      toast('API key tersimpan.');
      try { await refreshAccount(); } catch { toast('Key sudah tersimpan; status halaman belum dapat diperbarui. Muat ulang untuk memeriksa.'); }
    } catch (error) { message('keyFeedback', error.message); }
  });
  updateKey();
});
$('testKey').addEventListener('click', () => busy('testKey', 'Menghubungi BPS…', async () => {
  try {
    const sdgs = $('keyService').value === 'sdgs';
    const data = await request('/api/bps', { operation: sdgs ? 'getSdgsHome' : 'listDomains', parameters: sdgs ? {} : { type: 'all' } });
    message('keyFeedback', data.ok ? 'Koneksi berhasil. Credential tersimpan diterima oleh BPS.' : 'Key tersimpan, tetapi BPS belum menerima permintaan. Periksa key, kuota, atau ketersediaan layanan BPS.', data.ok ? '' : 'error');
  } catch (error) { message('keyFeedback', error.message); }
}));
$('deleteKey').addEventListener('click', () => { $('deleteKeyConfirm').hidden = false; });
$('cancelDeleteKey').addEventListener('click', () => { $('deleteKeyConfirm').hidden = true; });
$('confirmDeleteKey').addEventListener('click', () => busy('confirmDeleteKey', 'Menghapus…', async () => {
  try { await account('credentials', { service: $('keyService').value, delete: true }); $('savedKey').value = ''; $('deleteKeyConfirm').hidden = true; await refreshAccount(); message('keyFeedback', 'Key layanan ini telah dihapus.', ''); }
  catch (error) { message('keyFeedback', error.message); }
}));
$('tokenForm').addEventListener('submit', async event => {
  event.preventDefault(); message('dashboardError', '');
  await busy('createToken', 'Membuat token…', async () => {
    try { const data = await account('tokens', { label: $('tokenLabel').value.trim(), days: Number($('tokenDays').value) }); try { await refreshAccount(); } catch { /* Preserve the one-time token even if refreshing metadata fails. */ } showSecret(data.token, 'token', 'tokens'); }
    catch (error) { message('dashboardError', error.message); }
  });
});
async function logout() {
  try { await account('logout', {}); state.profile = null; state.csrf = ''; state.secret = ''; $('oneTimeSecret').textContent = ''; $('savedKey').value = ''; updateAccount(); location.hash = 'login'; toast('Anda sudah keluar. Token klien tetap berlaku sampai dicabut atau kedaluwarsa.'); }
  catch (error) { message('dashboardError', error.message); }
}
$('logout').addEventListener('click', logout); $('logoutSecondary').addEventListener('click', logout);
$('passwordForm').addEventListener('submit', async event => {
  event.preventDefault();
  if ($('newPassword').value !== $('newPasswordConfirm').value) { message('dashboardError', 'Kedua password baru belum sama.'); return; }
  await busy('changePassword', 'Mengganti password…', async () => {
    try { await account('password', { old_password: $('oldPassword').value, password: $('newPassword').value }); state.profile = null; state.csrf = ''; $('oldPassword').value = ''; $('newPassword').value = ''; $('newPasswordConfirm').value = ''; updateAccount(); location.hash = 'login'; toast('Password diganti. Semua sesi dan token lama telah dicabut.'); }
    catch (error) { message('dashboardError', error.message); }
  });
});
document.querySelectorAll('[data-toggle]').forEach(button => button.addEventListener('click', () => { const input = $(button.dataset.toggle); const visible = input.type === 'password'; input.type = visible ? 'text' : 'password'; button.textContent = visible ? 'Sembunyikan' : 'Lihat'; button.setAttribute('aria-label', (visible ? 'Sembunyikan ' : 'Tampilkan ') + (button.dataset.toggle === 'savedKey' ? 'API key' : 'password')); }));
function endpoint() { $('endpoint').textContent = location.origin + '/' + $('transport').value; }
$('transport').addEventListener('change', endpoint); $('copyEndpoint').addEventListener('click', () => copy($('endpoint').textContent, 'Endpoint')); endpoint();
async function loadSchema() {
  try {
    const response = await fetch('/api/bps/endpoints?operation=' + encodeURIComponent($('operation').value)); if (!response.ok) throw Error();
    const spec = await response.json();
    $('schema').textContent = spec.parameters.map(p => p.name + ' · ' + p.schema.type + (p.required ? ' · wajib' : ' · opsional') + (p.schema.enum ? ' · ' + p.schema.enum.join(' / ') : '')).join('\n') || 'Tidak ada parameter.';
    const params = {}; for (const p of spec.parameters) if (p.required) params[p.name] = p.schema.enum?.[0] ?? (p.name === 'domain' ? '1100' : p.name === 'lang' ? 'ind' : p.schema.type === 'integer' ? 1 : '');
    $('parameters').value = JSON.stringify(params, null, 2);
  } catch { $('schema').textContent = 'Skema belum dapat dimuat. Periksa ketersediaan layanan.'; }
}
$('operation').addEventListener('change', loadSchema);
$('explorer').addEventListener('submit', async event => {
  event.preventDefault(); message('explorerError', '');
  if (!state.profile) { location.hash = 'login'; toast('Masuk terlebih dahulu untuk memakai explorer.'); return; }
  let parameters; try { parameters = JSON.parse($('parameters').value); if (!parameters || typeof parameters !== 'object' || Array.isArray(parameters)) throw Error(); }
  catch { message('explorerError', 'Parameter harus berupa objek JSON yang valid.'); return; }
  await busy('run', 'Mengambil data…', async () => {
    try { const data = await request('/api/bps', { operation: $('operation').value, parameters }); $('result').textContent = JSON.stringify(data, null, 2); $('resultStatus').textContent = data.ok ? 'Berhasil' : 'Periksa respons'; if (!data.ok) message('explorerError', 'BPS belum dapat memenuhi permintaan. Periksa key tersimpan dan parameter.'); }
    catch (error) { $('resultStatus').textContent = 'Belum berhasil'; message('explorerError', error.message); }
  });
});
window.addEventListener('hashchange', () => { if (state.booted) route(); });
window.addEventListener('pagehide', () => { for (const id of ['password', 'passwordConfirm', 'savedKey', 'oldPassword', 'newPassword', 'newPasswordConfirm', 'recoveryCode']) $(id).value = ''; state.csrf = ''; state.verification = ''; state.secret = ''; $('oneTimeSecret').textContent = ''; });
window.addEventListener('pageshow', async event => { if (event.persisted) { try { await refreshAccount(); } catch { state.profile = null; } route(); } });
(async () => {
  captureVerification();
  try { await refreshAccount(); } catch { toast('Status akun belum dapat diperiksa. Coba muat ulang jika login gagal.'); }
  state.booted = true; route();
  try { const response = await fetch('/api/bps/endpoints'); if (!response.ok) throw Error(); const data = await response.json(); $('operation').replaceChildren(...data.operations.map(op => { const option = document.createElement('option'); option.value = op.operation; option.textContent = op.group + ' / ' + op.summary; return option; })); await loadSchema(); } catch { $('schema').textContent = 'Katalog operasi belum tersedia.'; }
  try { const response = await fetch('/health', { signal: AbortSignal.timeout(8000) }); const data = await response.json(); if (!response.ok || data.status !== 'ok') throw Error(); $('health').textContent = '● Layanan aktif'; $('health').className = 'badge'; } catch { $('health').textContent = 'Status belum tersedia'; }
})();
