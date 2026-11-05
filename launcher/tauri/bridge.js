// Tauri host adapter, appended after the shared launcher script. The Rust
// host injects LAUNCHER_CAPS (platform, builds, folder defaults, canBuild),
// LAUNCHER_SETTINGS and SAVED_STATE before the page runs; this file wires the
// page's host messages, the launch-settings panel and the Build panel to
// Tauri commands.
(() => {
  const invoke = window.__TAURI__.core.invoke;
  const caps = window.LAUNCHER_CAPS;
  const settings = window.LAUNCHER_SETTINGS;
  const status = document.getElementById('launchStatus');
  const panel = document.getElementById('setup');
  const fields = ['gameDir', 'userDataRoot', 'userDataRootUpdate', 'vulkanDevice', 'videoDriver'];

  // Menu state worth restoring next time (not the remap view or bindings).
  const uiState = () => {
    const { lang, path, fps, scale, vkscale, res, display, mouse, vkpath, vsync, backend } = state;
    return { lang, path, fps, scale, vkscale, res, display, mouse, vkpath, vsync, backend, build: curBuild() ? curBuild().id : null };
  };
  function showStatus(text) { status.textContent = text; }

  // Installed before the rest of the setup: the window has no decorations, so
  // if anything below throws, the page's close and drag buttons must still work.
  window.LAUNCHER_HOST = {
    async post(message) {
      try {
        if (message.type !== 'play') { await invoke('window_action', { action: message.type }); return; }
        // Only Save applies the panel fields; Play keeps the saved folders.
        settings.uiState = uiState();
        // The player name is a main-screen row; keep it with the other saved settings.
        const name = String(message.config.username ?? '').trim();
        if (name !== settings.username) {
          settings.username = name;
          invoke('save_settings', { settings }).catch(error => showStatus(String(error)));
        }
        const button = document.getElementById('playBtn');
        button.disabled = true; showStatus('Starting game…');
        try { await invoke('launch_game', { settings, options: message.config }); }
        finally { button.disabled = false; }
      } catch (error) { showStatus(String(error)); }
    },
  };

  // Display server: three buttons around a hidden field that readSettings/fillSettings use.
  const videoField = document.getElementById('videoDriver');
  const videoButtons = [...document.querySelectorAll('[data-video]')];
  function showVideo() {
    videoButtons.forEach(b => {
      const on = b.dataset.video === videoField.value;
      b.classList.toggle('on', on); b.setAttribute('aria-checked', String(on));
    });
  }
  videoButtons.forEach(b => b.addEventListener('click', () => { videoField.value = b.dataset.video; showVideo(); }));
  function fillSettings() {
    fields.forEach(key => {
      const field = document.getElementById(key);
      const value = settings[key] ?? '';
      field.value = key === 'vulkanDevice' && value < 0 ? '' : value;
      if (caps.defaults[key] !== undefined) field.placeholder = caps.defaults[key];
    });
    showVideo();
  }
  function readSettings() {
    fields.forEach(key => {
      const value = document.getElementById(key).value.trim();
      settings[key] = key === 'vulkanDevice' ? (value === '' ? -1 : Number(value)) : value;
    });
  }

  // External links (the font credit under Play) open in the default browser;
  // a Tauri webview ignores target="_blank" on its own.
  document.addEventListener('click', e => {
    const link = e.target.closest && e.target.closest('a[href]');
    if (!link || !/^https:\/\//i.test(link.getAttribute('href'))) return;
    e.preventDefault();
    invoke('open_external', { url: link.href }).catch(error => showStatus(String(error)));
  });

  document.getElementById('deviceLabel').hidden = !(caps.backends || []).includes('vulkan');
  // The display server (X11/Wayland) only exists on Linux.
  document.getElementById('videoLabel').hidden = caps.platform !== 'linux';
  function listBuilds() {
    document.getElementById('buildList').textContent = caps.builds.length
      ? caps.builds.map(b => `${b.label}: ${b.executable}`).join('\n')
      : 'No game build found next to the launcher or under port/out/build.';
  }
  listBuilds();
  if (caps.version) document.getElementById('launcherVersion').textContent = `Launcher build ${caps.version.label}`;
  if (!caps.builds.length) {
    showStatus(caps.canBuild ? 'No game build found. Build it from your disc image.'
      : 'No game build found. Open launch settings (⚙) for details.');
  }
  document.getElementById('setupBtn').addEventListener('click', e => {
    e.stopPropagation(); fillSettings(); panel.hidden = !panel.hidden;
  });
  document.getElementById('saveSetup').addEventListener('click', async () => {
    try { readSettings(); settings.uiState = uiState(); await invoke('save_settings', { settings }); panel.hidden = true; showStatus('Launch settings saved.'); }
    catch (error) { showStatus(String(error)); }
  });
  document.getElementById('cancelSetup').addEventListener('click', () => { panel.hidden = true; });

  // Build panel: runs scripts/build_client.py (start_build) into the game
  // folders above and refreshes Game Version when it finishes.
  const buildPanel = document.getElementById('buildPanel');
  const buildInputs = { buildIso: 'buildIso', buildTitleUpdate: 'buildTitleUpdate', buildCmake: 'buildCmake' };
  const optUpdate = document.getElementById('optUpdate');
  const optExtras = document.getElementById('optExtras');
  const buildStep = document.getElementById('buildStep');
  const buildLog = document.getElementById('buildLog');
  const startButton = document.getElementById('startBuild');
  const logLines = [];
  // What the panel runs, from the click that starts it until it ends: 'build'
  // (its tool check and download prompt included) or 'install'. Set before the
  // first await so a second click is ignored; the host turns one away too.
  let job = null;
  if (caps.platform === 'windows') {
    // build_windows.py finds CMake, Ninja and Clang (Visual Studio, LLVM) by itself.
    document.getElementById('cmakeLabel').hidden = true;
    document.getElementById('buildIntro').textContent = 'Builds the game from your disc image and, optionally, the USA Title Update package. Needs Visual Studio 2022 (C++ and CMake workload), LLVM Clang, Git and Python.';
  }
  document.getElementById('openBuild').hidden = !caps.canBuild;
  // The title update is an overlay on the base game files (always extracted, never
  // modified), so the panel asks for what to compile, not for four peer builds. It
  // compiles the update, or the base game without it, and the optional PC features
  // apply to either. The result is one build_client.py variant id.
  function selectedVariants() {
    return [`${optUpdate.checked ? 'update' : 'base'}${optExtras.checked ? '' : '-plain'}`];
  }
  function updateSummary() {
    const [variant] = selectedVariants();
    document.getElementById('buildSummary').textContent =
      `Will compile: ${variant.startsWith('update') ? 'Update' : 'Base'}${variant.endsWith('-plain') ? ' (no extras)' : ''}.` +
      (optUpdate.checked ? ' The update runs on top of the base game files, which are always extracted.' : '');
  }
  [optUpdate, optExtras].forEach(box => box.addEventListener('change', updateSummary));
  function titleUpdateAdded() { optUpdate.checked = true; updateSummary(); }
  document.getElementById('buildTitleUpdate').addEventListener('change', event => {
    if (event.target.value.trim()) titleUpdateAdded();
  });
  updateSummary();
  // Build tools: the host looks for Python, Git, a compiler, CMake and Ninja before
  // anything runs and the panel links to the download of each one that is missing.
  const toolList = document.getElementById('toolList');
  const sdkPrompt = document.getElementById('sdkPrompt');
  function renderTools(report) {
    toolList.textContent = '';
    if (!report) { toolList.textContent = 'Could not check the build tools.'; showWinget(null); return; }
    const add = (ok, text, note, url) => {
      const item = document.createElement('li');
      item.className = ok ? 'ok' : 'miss';
      item.append(`${ok ? '✓' : '✗'} ${text}`);
      if (!ok && url) {
        const link = document.createElement('a');
        link.href = url; link.textContent = ' Get it';
        item.append(link);
      }
      if (!ok && note) { const small = document.createElement('small'); small.textContent = note; item.append(small); }
      toolList.append(item);
    };
    report.tools.forEach(t => add(t.found, t.label, t.note, t.url));
    // Warnings do not block Build; they explain failures that may come later.
    (report.warnings ?? []).forEach(text => {
      const item = document.createElement('li');
      item.className = 'warn'; item.textContent = `! ${text}`;
      toolList.append(item);
    });
    const sdk = report.sdk;
    if (report.sources) add(false, `Game sources (${report.sources.commit.slice(0, 8)})`,
      'Not downloaded yet. Starting the build asks before they are fetched.');
    add(sdk.installed, `ReXGlue SDK${sdk.commit ? ` (pinned ${sdk.commit.slice(0, 8)})` : ''}`,
      sdk.stale ? 'Built from another version or patch set; it is rebuilt before the game. Starting the build asks first.'
        : 'Not built yet. Starting the build asks before it is downloaded.');
    showWinget(report);
  }
  // Windows with winget: one button installs every missing tool. Its note says
  // what pressing it agrees to, since winget accepts the license agreements.
  const wingetRow = document.getElementById('wingetRow');
  function showWinget(report) {
    const missing = report && report.winget ? report.tools.filter(t => !t.found && t.winget) : [];
    // A check that finishes while winget runs must not offer a second install.
    wingetRow.hidden = job === 'install' || !missing.length;
    if (wingetRow.hidden) return;
    const vs = missing.some(t => t.id === 'msvc');
    document.getElementById('wingetNote').textContent =
      `Installs ${missing.map(t => t.label).join(', ')} with winget and accepts their license agreements. ` +
      'Windows asks for administrator approval for most of them.' +
      (vs ? ' Visual Studio Build Tools is several GB and shows its own progress window.' : '');
  }
  document.getElementById('installTools').addEventListener('click', async () => {
    if (job) return;
    job = 'install';
    logLines.length = 0; buildLog.textContent = '';
    buildStep.textContent = 'Installing build tools…';
    setBuilding(true);
    // winget and the installers it starts are not stopped halfway.
    document.getElementById('cancelBuild').hidden = true;
    wingetRow.hidden = true;
    let report = null;
    try { report = await invoke('install_tools', { cmake: document.getElementById('buildCmake').value.trim() }) || null; }
    catch (error) { buildStep.textContent = String(error); }
    finally { job = null; setBuilding(false); }
    if (!report) { checkTools(); return; }
    renderTools(report);
    buildStep.textContent = report.ready ? 'The build tools are installed. Press Build to continue.'
      : 'Some tools are still missing (see above). If one was just installed, restart the launcher and press Check tools.';
  });
  async function checkTools() {
    let report = null;
    try { report = await invoke('check_build_tools', { cmake: document.getElementById('buildCmake').value.trim() }) || null; }
    catch (error) { buildStep.textContent = String(error); }
    renderTools(report);
    return report;
  }
  // Answers the open download prompt, if any. Closing the panel answers no, so
  // the request it was asked for is dropped and a later Build starts afresh.
  let answerPrompt = null;
  // Resolves true when the user agrees to download what is missing: the game
  // sources (a launcher outside a checkout) and/or the ReXGlue SDK.
  function askDownloads(report) {
    const { sdk, sources } = report;
    const parts = [];
    if (sources) parts.push(`the game sources (${sources.repository}, commit ${sources.commit.slice(0, 8)}), a small download`);
    if (sdk.stale) parts.push(`a rebuild of the ReXGlue SDK (commit ${sdk.commit.slice(0, 8)}), which was built from a different version or patch set and can take 12+ minutes`);
    else if (!sdk.installed) parts.push(`the ReXGlue SDK (${sdk.repository || 'pinned version'}${sdk.commit ? `, commit ${sdk.commit.slice(0, 8)}` : ''}), about 3 GB, and the first build takes 12+ minutes`);
    document.getElementById('sdkPromptText').textContent =
      `Compiling the game needs ${parts.join(' and ')}. Download ${parts.length > 1 ? 'them' : 'it'} and continue?`;
    sdkPrompt.hidden = false;
    return new Promise(resolve => {
      answerPrompt = answer => { answerPrompt = null; sdkPrompt.hidden = true; resolve(answer); };
      document.getElementById('sdkYes').onclick = () => answerPrompt?.(true);
      document.getElementById('sdkNo').onclick = () => answerPrompt?.(false);
    });
  }
  document.getElementById('recheckTools').addEventListener('click', checkTools);
  document.getElementById('buildCmake').addEventListener('change', checkTools);
  function openBuild() {
    Object.keys(buildInputs).forEach(key => { document.getElementById(key).value = settings[key] ?? ''; });
    panel.hidden = true; buildPanel.hidden = false;
    checkTools();
  }
  function setBuilding(on) {
    startButton.hidden = on;
    document.getElementById('recheckTools').disabled = on;
    // The running build's log sits right after the tool list and takes its place.
    document.getElementById('toolsLabel').hidden = on;
    document.getElementById('cancelBuild').hidden = !on;
    document.getElementById('closeBuild').disabled = on;
    document.getElementById('setupBtn').disabled = on;
    document.getElementById('playBtn').disabled = on;
    buildPanel.querySelectorAll('input, [data-pick]').forEach(el => { el.disabled = on; });
  }
  function log(line) {
    logLines.push(line);
    if (logLines.length > 400) logLines.shift();
    buildLog.textContent = logLines.join('\n');
    buildLog.scrollTop = buildLog.scrollHeight;
  }
  window.__TAURI__.event.listen('build-output', ({ payload }) => {
    const step = /^::step::(\d+)\/(\d+)::(.*)$/.exec(payload);
    if (step) buildStep.textContent = `Step ${step[1]} of ${step[2]}: ${step[3]}…`;
    else if (payload !== '::done::') log(payload);
  });
  document.getElementById('openBuild').addEventListener('click', openBuild);
  document.getElementById('closeBuild').addEventListener('click', () => {
    buildPanel.hidden = true;
    answerPrompt?.(false);
  });
  buildPanel.querySelectorAll('[data-pick]').forEach(button => button.addEventListener('click', async () => {
    const kind = button.dataset.pick;
    try {
      const path = await invoke('pick_file', { kind });
      if (!path) return;
      button.previousElementSibling.value = path;
      // A title update means an update build is wanted, in place of the base one.
      if (kind === 'titleUpdate') titleUpdateAdded();
    } catch (error) { buildStep.textContent = String(error); }
  }));
  document.getElementById('cancelBuild').addEventListener('click', () => {
    buildStep.textContent = 'Cancelling…';
    invoke('cancel_build').catch(error => { buildStep.textContent = String(error); });
  });
  startButton.addEventListener('click', async () => {
    if (job) return;
    job = 'build'; startButton.disabled = true;
    try { await runBuild(); }
    finally { job = null; startButton.disabled = false; }
  });
  async function runBuild() {
    Object.keys(buildInputs).forEach(key => { settings[key] = document.getElementById(key).value.trim(); });
    settings.uiState = uiState();
    const request = {
      iso: settings.buildIso, titleUpdate: settings.buildTitleUpdate, cmake: settings.buildCmake,
      variants: selectedVariants(), downloadSdk: false, downloadSources: false,
    };
    logLines.length = 0; buildLog.textContent = '';
    buildStep.textContent = 'Checking build tools…';
    // An unavailable check (null) is left to the host, which checks again before it runs anything.
    const report = await checkTools();
    if (report && !report.ready) {
      buildStep.textContent = 'Install the missing tools listed above, then press Build again.';
      return;
    }
    if (report && (report.sources || !report.sdk.installed)) {
      const agreed = await askDownloads(report);
      if (!agreed) { buildStep.textContent = 'Nothing was downloaded. The build needs the game sources and the ReXGlue SDK.'; return; }
      request.downloadSdk = !report.sdk.installed;
      request.downloadSources = Boolean(report.sources);
    }
    buildStep.textContent = 'Checking inputs…';
    setBuilding(true);
    try {
      const builds = await invoke('start_build', { settings, request });
      // The page reads CAPS.builds (its copy of LAUNCHER_CAPS) on each render.
      caps.builds = CAPS.builds = builds;
      listBuilds(); render();
      // Back to the main screen; failures and cancellations stay in the panel.
      buildPanel.hidden = true;
      showStatus('Build complete. Choose it under Game Version.');
    } catch (error) {
      buildStep.textContent = String(error);
    } finally { setBuilding(false); }
  }
  // Same signal as the launcher's update autoselect (caps.updateInstalled): once the
  // update is there, the Build panel opens on update instead of Base so a rebuild
  // does not make both. A saved package path counts too. Applied once, so a
  // deliberate Base tick later is left alone.
  if (caps.updateInstalled || (settings.buildTitleUpdate ?? '').trim()) titleUpdateAdded();
  if (!caps.builds.length && caps.canBuild) openBuild();
})();
