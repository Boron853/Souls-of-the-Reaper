// Runs the shared launcher page in jsdom: as Launcher.ps1 loads it (no host
// capabilities) and as the Tauri build (dist/index.html, from prepare-ui.mjs).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { JSDOM, VirtualConsole } from 'jsdom';

const legacyHtml = readFileSync(new URL('../v6_borderless_final.html', import.meta.url), 'utf8');
const tauriHtml = readFileSync(new URL('./dist/index.html', import.meta.url), 'utf8');
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

const BUILDS = [
  { id: 'base', label: 'Base', update: false, extras: false, executable: '/r/linux-amd64-relwithdebinfo/diablo3' },
  { id: 'update-extras', label: 'Update + Extras', update: true, extras: true, executable: '/r/linux-amd64-update-extras-relwithdebinfo/diablo3' },
];

function page(html, globals, options = {}) {
  const dom = new JSDOM(html, { runScripts: 'dangerously', beforeParse: window => Object.assign(window, globals), ...options });
  const doc = dom.window.document;
  const rows = () => [...doc.querySelectorAll('#menu .opt-row')].map(r => ({
    row: r, label: r.querySelector('.opt-label').textContent, value: r.querySelector('.opt-val')?.textContent,
  }));
  const row = label => rows().find(r => r.label === label);
  const click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
  const next = label => click(row(label).row.querySelector('[data-a="r"]'));
  return { dom, doc, rows, row, click, next };
}

function tauriPage({ platform = 'linux', builds = BUILDS, settings = {}, saved = { res: -1, display: -1 }, failLaunch = false,
  canBuild = true, responses = {}, caps = {}, events = true, jsdom = {} } = {}) {
  const calls = [];
  const listeners = {};
  const invoke = async (command, args) => {
    calls.push({ command, args });
    if (command === 'launch_game' && failLaunch) throw 'Default.xex does not match';
    if (command in responses) return responses[command](args);
  };
  const listen = async (event, handler) => { listeners[event] = handler; return () => {}; };
  const p = page(tauriHtml, {
    __TAURI__: { core: { invoke }, event: events ? { listen } : {} },
    LAUNCHER_CAPS: { platform, updateInstalled: !!settings.updateInstalled, backends: platform === 'windows' ? ['d3d12', 'vulkan'] : ['vulkan'], builds, canBuild, defaults: { gameDir: '/r/game', gameDirUpdate: '/r/game', userDataRoot: '/d/sotr', userDataRootUpdate: '/d/sotr-update' }, ...caps },
    LAUNCHER_SETTINGS: { gameDir: '', gameDirUpdate: '', userDataRoot: '', userDataRootUpdate: '', vulkanDevice: -1, ...settings },
    SAVED_STATE: { ...saved, username: settings.username ?? '' },
  }, jsdom);
  const emit = (event, payload) => listeners[event]({ payload });
  return { ...p, calls, emit };
}

test('Launcher.ps1 keeps its original rows and WebView2 message channel', () => {
  const posted = [];
  const { rows, row, click, doc } = page(legacyHtml, {
    chrome: { webview: { postMessage: m => posted.push(JSON.parse(m)) } },
    SAVED_STATE: { lang: 0, path: 1, fps: 1, scale: 0, res: 2, display: 1, mouse: 0 },
  });
  assert.deepEqual(rows().map(r => r.label),
    ['Render Path', 'Frame Rate', 'Image Scaling', 'Internal Resolution', 'Display', 'Mouse', 'Remap Controls ›']);
  assert.equal(row('Internal Resolution').value, '3×');
  click(doc.getElementById('playBtn'));
  const { config } = posted[0];
  assert.equal(posted[0].type, 'play');
  assert.equal(config.rtp, 'rtv');
  assert.equal(config.fps, 120);
  assert.equal(config.resScale, 3);
  assert.equal(config.fullscreen, false);
});

test('Linux shows Vulkan rows and hides D3D12-only options', () => {
  const { rows } = tauriPage();
  assert.deepEqual(rows().map(r => r.label),
    ['Game Version', 'Render Path', 'VSync', 'Image Scaling', 'Internal Resolution', 'Display', 'Mouse', 'Player Name', 'Remap Controls ›']);
  assert.equal(rows()[1].value, 'FSI');
  assert.equal(rows()[3].value, 'Off');
});

test('Linux Display Server is a launch setting, saved from the settings panel and sent on Play', async () => {
  const { doc, click, calls } = tauriPage({ settings: { videoDriver: 'x11' } });
  assert.equal(doc.getElementById('videoLabel').hidden, false);
  click(doc.getElementById('setupBtn'));
  assert.equal(doc.getElementById('videoDriver').value, 'x11');
  assert.equal(doc.querySelector('[data-video].on').dataset.video, 'x11');
  click(doc.querySelector('[data-video="wayland"]'));
  assert.equal(doc.querySelector('[data-video].on').dataset.video, 'wayland');
  click(doc.getElementById('saveSetup'));
  await tick();
  assert.equal(calls.find(c => c.command === 'save_settings').args.settings.videoDriver, 'wayland');
  assert.equal(tauriPage({ platform: 'windows' }).doc.getElementById('videoLabel').hidden, true);
});

test('Windows keeps the D3D12 rows and adds the build selector', () => {
  const { rows } = tauriPage({ platform: 'windows' });
  assert.deepEqual(rows().map(r => r.label).slice(0, 5),
    ['Game Version', 'Renderer', 'Render Path', 'Frame Rate', 'Image Scaling']);
  assert.equal(rows()[1].value, 'D3D12');
});

test('Windows can switch to Vulkan, which swaps in the Vulkan rows and is sent on Play', async () => {
  const { rows, row, next, doc, click, calls } = tauriPage({ platform: 'windows' });
  next('Renderer');
  assert.equal(row('Renderer').value, 'Vulkan');
  assert.deepEqual(rows().map(r => r.label).slice(0, 4), ['Game Version', 'Renderer', 'Render Path', 'VSync']);
  assert.equal(row('Render Path').value, 'FSI');
  click(doc.getElementById('playBtn'));
  await tick();
  const options = calls.find(c => c.command === 'launch_game').args.options;
  assert.equal(options.backend, 'vulkan');
  assert.equal(options.vkPath, 'fsi');
  assert.equal(options.vsync, true);
  assert.equal(calls.find(c => c.command === 'launch_game').args.settings.uiState.backend, 1);
});

test('Extras builds offer In-game resolution and display; normal builds do not', () => {
  const { row, next } = tauriPage();
  assert.equal(row('Internal Resolution').value, '1×', 'normal build falls back to an explicit scale');
  assert.equal(row('Display').value, 'Fullscreen');
  next('Game Version');
  assert.equal(row('Game Version').value, 'Update + Extras');
  assert.equal(row('Internal Resolution').value, 'In-game');
  assert.equal(row('Display').value, 'In-game');
  next('Internal Resolution');
  assert.equal(row('Internal Resolution').value, '1×');
});

test('Play sends the selected build, in-game choices and saved menu state', async () => {
  const { doc, click, next, calls } = tauriPage({ settings: { gameDirUpdate: '/games/update' } });
  next('Game Version');
  click(doc.getElementById('playBtn'));
  await tick();
  const launch = calls.find(c => c.command === 'launch_game');
  assert.equal(launch.args.options.build, 'update-extras');
  assert.equal(launch.args.options.resScale, 0);
  assert.equal(launch.args.options.fullscreen, null);
  assert.equal(launch.args.options.vkPath, 'fsi');
  assert.equal(launch.args.options.vsync, true);
  assert.equal(launch.args.settings.gameDirUpdate, '/games/update');
  assert.equal(launch.args.settings.uiState.build, 'update-extras');
  assert.equal(launch.args.settings.uiState.view, undefined);
});

test('Player Name is a main-screen row, filled from settings and saved on Play', async () => {
  const { doc, click, row, calls } = tauriPage({ settings: { username: 'Nephalem' } });
  assert.equal(doc.getElementById('setup').querySelector('#username'), null, 'no longer in the launch settings panel');
  const input = doc.querySelector('.opt-row[data-key="username"] input.opt-name');
  assert.equal(input.value, 'Nephalem');
  assert.equal(input.maxLength, 15);
  input.value = '  Reaper ';
  input.dispatchEvent(new doc.defaultView.Event('input'));
  click(doc.getElementById('playBtn'));
  await tick();
  assert.equal(calls.find(c => c.command === 'launch_game').args.settings.username, 'Reaper');
  assert.equal(calls.find(c => c.command === 'save_settings').args.settings.username, 'Reaper');
});

test('The font credit under Play opens in the default browser', async () => {
  const { doc, click, calls } = tauriPage();
  const link = doc.querySelector('.foot a.fontlink');
  assert.match(link.href, /^https:\/\/fernandoforeroart\.com\//);
  click(link);
  await tick();
  assert.deepEqual(calls.filter(c => c.command === 'open_external').map(c => c.args.url), [link.href]);
});

test('The borderless window can still be closed when the host setup fails', async () => {
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => errors.push(error));
  // Without the event API the Build panel setup throws halfway through.
  const { doc, click, calls } = tauriPage({ events: false, jsdom: { virtualConsole } });
  assert.match(String(errors[0]?.cause ?? errors[0]), /listen/);
  click(doc.getElementById('winClose'));
  await tick();
  assert.deepEqual(calls.filter(c => c.command === 'window_action').map(c => c.args.action), ['close']);
});

test('Launch failures stay visible and restore the Play button', async () => {
  const { doc, click } = tauriPage({ failLaunch: true });
  click(doc.getElementById('playBtn'));
  await tick();
  assert.equal(doc.getElementById('launchStatus').textContent, 'Default.xex does not match');
  assert.equal(doc.getElementById('playBtn').disabled, false);
});

test('Launch settings show defaults and save a blank Vulkan device as automatic', async () => {
  const { doc, click, calls } = tauriPage();
  click(doc.getElementById('setupBtn'));
  assert.equal(doc.getElementById('setup').hidden, false);
  assert.equal(doc.getElementById('gameDirUpdate'), null);
  assert.equal(doc.getElementById('vulkanDevice').value, '');
  assert.match(doc.getElementById('buildList').textContent, /Update \+ Extras: .*update-extras/);
  doc.getElementById('userDataRoot').value = ' /saves ';
  click(doc.getElementById('saveSetup'));
  await tick();
  const saved = calls.find(c => c.command === 'save_settings').args.settings;
  assert.equal(saved.userDataRoot, '/saves');
  assert.equal(saved.vulkanDevice, -1);
  assert.equal(doc.getElementById('setup').hidden, true);
});

test('Missing builds hide the selector and explain where to look', () => {
  const { rows, doc } = tauriPage({ builds: [], canBuild: false });
  assert.equal(rows()[0].label, 'Render Path');
  assert.match(doc.getElementById('launchStatus').textContent, /No game build found/);
  assert.equal(doc.getElementById('buildPanel').hidden, true);
  assert.equal(doc.getElementById('openBuild').hidden, true, 'release installs cannot build');
});

test('A source checkout without builds opens the Build panel', () => {
  const { doc } = tauriPage({ builds: [], settings: { buildIso: '/isos/d3.iso' } });
  assert.equal(doc.getElementById('buildPanel').hidden, false);
  assert.equal(doc.getElementById('buildIso').value, '/isos/d3.iso');
  assert.match(doc.getElementById('launchStatus').textContent, /Build it from your disc image/);
});

test('Building streams progress, saves inputs and adds the new build to Game Version', async () => {
  let finish;
  const { doc, click, row, rows, calls, emit } = tauriPage({
    builds: [],
    responses: {
      pick_file: ({ kind }) => (kind === 'titleUpdate' ? '/isos/title-update' : null),
      start_build: () => new Promise(resolve => { finish = resolve; }),
    },
  });
  doc.getElementById('buildIso').value = ' /isos/d3.iso ';
  click(doc.querySelector('[data-pick="titleUpdate"]'));
  await tick();
  assert.equal(doc.getElementById('buildTitleUpdate').value, '/isos/title-update');
  assert.equal(doc.getElementById('optUpdate').checked, true, 'choosing a title update selects it');
  assert.match(doc.getElementById('buildSummary').textContent, /^Will compile: Update\./);
  click(doc.getElementById('startBuild'));
  await tick();
  const { request, settings } = calls.find(c => c.command === 'start_build').args;
  assert.deepEqual(JSON.parse(JSON.stringify(request)), { iso: '/isos/d3.iso', titleUpdate: '/isos/title-update', cmake: '', variants: ['update'], downloadSdk: false, downloadSources: false });
  assert.equal(settings.buildIso, '/isos/d3.iso');
  assert.equal(doc.getElementById('playBtn').disabled, true);
  assert.equal(doc.getElementById('cancelBuild').hidden, false);
  assert.equal(doc.getElementById('toolsLabel').hidden, true, 'the log replaces the tool list while building');
  emit('build-output', '::step::2/5::Extract title update');
  emit('build-output', 'CPKs/Patch.cpk: 3,774,503 bytes');
  assert.equal(doc.getElementById('buildStep').textContent, 'Step 2 of 5: Extract title update…');
  assert.equal(doc.getElementById('buildLog').textContent, 'CPKs/Patch.cpk: 3,774,503 bytes');
  finish(BUILDS);
  await tick(); await tick();
  assert.equal(doc.getElementById('playBtn').disabled, false);
  assert.equal(doc.getElementById('cancelBuild').hidden, true);
  assert.equal(doc.getElementById('toolsLabel').hidden, false);
  assert.equal(rows()[0].label, 'Game Version');
  assert.equal(row('Game Version').value, 'Base');
  assert.match(doc.getElementById('buildList').textContent, /Update \+ Extras/);
  assert.equal(doc.getElementById('buildPanel').hidden, true, 'a finished build returns to the main screen');
  assert.equal(doc.getElementById('launchStatus').textContent, 'Build complete. Choose it under Game Version.');
});

test('A double click on Build starts one build and the panel stays busy until it ends', async () => {
  let finish;
  const { doc, click, calls } = tauriPage({
    builds: [],
    responses: {
      // The host turns a second build away; that error must not reset the panel.
      start_build: () => (finish ? Promise.reject('A build is already running.') : new Promise(resolve => { finish = resolve; })),
    },
  });
  click(doc.getElementById('startBuild'));
  click(doc.getElementById('startBuild'));
  await tick(); await tick();
  assert.equal(calls.filter(c => c.command === 'start_build').length, 1);
  assert.equal(doc.getElementById('cancelBuild').hidden, false);
  assert.equal(doc.getElementById('playBtn').disabled, true);
  assert.equal(doc.getElementById('closeBuild').disabled, true);
  finish(BUILDS);
  await tick(); await tick();
  assert.equal(doc.getElementById('playBtn').disabled, false);
  assert.equal(doc.getElementById('cancelBuild').hidden, true);
  assert.equal(doc.getElementById('startBuild').disabled, false);
  click(doc.getElementById('startBuild'));
  await tick(); await tick();
  assert.equal(calls.filter(c => c.command === 'start_build').length, 2, 'Build works again afterwards');
});

const tick1 = (doc, el, on) => { el.checked = on; el.dispatchEvent(new doc.defaultView.Event('change')); };

test('The Build panel asks what to build and summarises it', () => {
  const { doc } = tauriPage({ builds: [] });
  const summary = () => doc.getElementById('buildSummary').textContent;
  assert.equal(doc.getElementById('optUpdate').checked, false);
  assert.equal(doc.getElementById('optBase'), null, 'Base is not a separate choice');
  assert.match(summary(), /^Will compile: Base\.$/);
  tick1(doc, doc.getElementById('optUpdate'), true);
  assert.match(summary(), /^Will compile: Update\. The update runs on top of the base game/);
  tick1(doc, doc.getElementById('optExtras'), false);
  assert.match(summary(), /^Will compile: Update \(no extras\)\./);
});

test('Choosing a title update package selects the update build', () => {
  const { doc } = tauriPage({ builds: [] });
  const title = doc.getElementById('buildTitleUpdate');
  title.value = '/isos/title-update';
  title.dispatchEvent(new doc.defaultView.Event('change'));
  assert.equal(doc.getElementById('optUpdate').checked, true);
});

test('Build requests carry the single matching variant', async () => {
  const { doc, click, calls } = tauriPage({ builds: [], responses: { start_build: async () => [] } });
  tick1(doc, doc.getElementById('optUpdate'), true);
  tick1(doc, doc.getElementById('optExtras'), false);
  click(doc.getElementById('startBuild'));
  await tick(); await tick();
  assert.deepEqual(JSON.parse(JSON.stringify(calls.find(c => c.command === 'start_build').args.request.variants)), ['update-plain']);
});

test('update already installed opens the Build panel on the update', () => {
  const { doc } = tauriPage({ builds: [], settings: { updateInstalled: true } });
  assert.equal(doc.getElementById('optUpdate').checked, true);
});

test('A saved title update package opens the Build panel on the update', () => {
  const { doc } = tauriPage({ builds: [], settings: { buildIso: '/i.iso', buildTitleUpdate: '/isos/title-update' } });
  assert.equal(doc.getElementById('optUpdate').checked, true);
});

test('Build failures and cancellation are reported in the panel', async () => {
  const { doc, click, calls } = tauriPage({ responses: { start_build: async () => { throw 'Build failed: wrong disc'; } } });
  click(doc.getElementById('setupBtn'));
  click(doc.getElementById('openBuild'));
  assert.equal(doc.getElementById('setup').hidden, true);
  click(doc.getElementById('startBuild'));
  await tick(); await tick();
  assert.equal(doc.getElementById('buildStep').textContent, 'Build failed: wrong disc');
  assert.equal(doc.getElementById('startBuild').hidden, false);
  click(doc.getElementById('cancelBuild'));
  assert.ok(calls.some(c => c.command === 'cancel_build'));
});

test('Windows offers build choices and finds CMake by itself', () => {
  const { doc } = tauriPage({ platform: 'windows', builds: [] });
  assert.equal(doc.getElementById('buildVariants').hidden, false);
  assert.equal(doc.getElementById('cmakeLabel').hidden, true);
  assert.notEqual(doc.getElementById('startBuild').textContent, 'Prepare');
});

test('Cancelled settings edits are not used by Play', async () => {
  const { doc, click, calls } = tauriPage({ settings: { gameDir: '/games/base' } });
  click(doc.getElementById('setupBtn'));
  doc.getElementById('gameDir').value = '/typo';
  click(doc.getElementById('cancelSetup'));
  click(doc.getElementById('playBtn'));
  await tick();
  assert.equal(calls.find(c => c.command === 'launch_game').args.settings.gameDir, '/games/base');
});

test('Launch settings show the launcher build revision when the host reports it', () => {
  const { doc } = tauriPage({ caps: { version: { commit: 'c94f5ebdcb3c9d1a460ca48e04f9758448f8d518', dirty: true, label: 'c94f5ebd (modified)' } } });
  assert.equal(doc.getElementById('launcherVersion').textContent, 'Launcher build c94f5ebd (modified)');
  assert.equal(tauriPage().doc.getElementById('launcherVersion').textContent, '');
});

const TOOL = (id, found) => ({ id, label: id.toUpperCase(), found, path: '', url: found ? '' : `https://example.test/${id}`, note: '' });
const SDK = installed => ({ installed, repository: 'https://example.test/sdk.git', commit: 'c94f5ebdcb3c9d1a460ca48e04f9758448f8d518' });

test('Missing build tools are listed with download links and block the build', async () => {
  const report = { ready: false, tools: [TOOL('python', false), TOOL('git', true)], sdk: SDK(true) };
  const { doc, click, calls } = tauriPage({ builds: [], responses: { check_build_tools: () => report } });
  await tick();
  const items = [...doc.querySelectorAll('#toolList li')];
  assert.equal(items.length, 3);
  assert.equal(items[0].className, 'miss');
  assert.equal(items[0].querySelector('a').href, 'https://example.test/python');
  assert.equal(items[1].className, 'ok');
  click(doc.getElementById('startBuild'));
  await tick(); await tick();
  assert.equal(calls.some(c => c.command === 'start_build'), false);
  assert.match(doc.getElementById('buildStep').textContent, /missing tools/);
});

test('Windows offers to install missing tools with winget and says it accepts their licenses', async () => {
  const missing = { ...TOOL('msvc', false), label: 'Visual Studio 2022 C++ tools', winget: 'Microsoft.VisualStudio.2022.BuildTools' };
  const report = { ready: false, winget: true, tools: [missing, { ...TOOL('git', true), winget: 'Git.Git' }], sdk: SDK(true) };
  const after = { ...report, ready: true, tools: [{ ...missing, found: true }, report.tools[1]] };
  const { doc, click, calls } = tauriPage({ platform: 'windows', builds: [],
    responses: { check_build_tools: () => report, install_tools: async () => after } });
  await tick();
  assert.equal(doc.getElementById('wingetRow').hidden, false);
  const note = doc.getElementById('wingetNote').textContent;
  assert.match(note, /Visual Studio 2022 C\+\+ tools/);
  assert.match(note, /accepts their license agreements/);
  assert.doesNotMatch(note, /\bGIT\b/);
  click(doc.getElementById('installTools'));
  await tick(); await tick();
  assert.equal(calls.filter(c => c.command === 'install_tools').length, 1);
  assert.equal(doc.getElementById('wingetRow').hidden, true);
  assert.match(doc.getElementById('buildStep').textContent, /installed/);
  assert.equal(doc.querySelector('#toolList li').className, 'ok');
});

test('Checking tools while winget runs does not offer a second install', async () => {
  const missing = { ...TOOL('git', false), winget: 'Git.Git' };
  const report = { ready: false, winget: true, tools: [missing], sdk: SDK(true) };
  let finish;
  const { doc, click, calls } = tauriPage({ platform: 'windows', builds: [],
    responses: { check_build_tools: () => report, install_tools: () => new Promise(resolve => { finish = resolve; }) } });
  await tick();
  assert.equal(doc.getElementById('wingetRow').hidden, false);
  click(doc.getElementById('installTools'));
  await tick();
  assert.equal(doc.getElementById('recheckTools').disabled, true);
  click(doc.getElementById('recheckTools'));
  // A check started before the install, or by the CMake field, can still finish meanwhile.
  doc.getElementById('buildCmake').dispatchEvent(new doc.defaultView.Event('change'));
  await tick(); await tick();
  assert.equal(doc.getElementById('wingetRow').hidden, true);
  click(doc.getElementById('installTools'));
  await tick();
  assert.equal(calls.filter(c => c.command === 'install_tools').length, 1);
  finish({ ...report, ready: true, tools: [{ ...missing, found: true }] });
  await tick(); await tick();
  assert.equal(doc.getElementById('recheckTools').disabled, false);
  assert.match(doc.getElementById('buildStep').textContent, /installed/);
});

test('The winget button stays hidden without winget or missing tools', async () => {
  for (const report of [
    { ready: false, winget: false, tools: [{ ...TOOL('git', false), winget: 'Git.Git' }], sdk: SDK(true) },
    { ready: true, winget: true, tools: [{ ...TOOL('git', true), winget: 'Git.Git' }], sdk: SDK(true) },
  ]) {
    const { doc } = tauriPage({ platform: 'windows', builds: [], responses: { check_build_tools: () => report } });
    await tick();
    assert.equal(doc.getElementById('wingetRow').hidden, true);
  }
});

test('A missing SDK is only downloaded after the user agrees', async () => {
  const report = { ready: true, tools: [TOOL('git', true)], sdk: SDK(false) };
  const { doc, click, calls } = tauriPage({ builds: [], responses: { check_build_tools: () => report, start_build: async () => [] } });
  await tick();
  click(doc.getElementById('startBuild'));
  await tick(); await tick();
  assert.equal(doc.getElementById('sdkPrompt').hidden, false);
  assert.match(doc.getElementById('sdkPromptText').textContent, /c94f5ebd/);
  click(doc.getElementById('sdkNo'));
  await tick(); await tick();
  assert.equal(calls.some(c => c.command === 'start_build'), false);
  assert.match(doc.getElementById('buildStep').textContent, /Nothing was downloaded/);
  click(doc.getElementById('startBuild'));
  await tick(); await tick();
  click(doc.getElementById('sdkYes'));
  await tick(); await tick();
  assert.equal(calls.find(c => c.command === 'start_build').args.request.downloadSdk, true);
});

test('Closing the Build panel at the download prompt drops that request', async () => {
  const report = { ready: true, tools: [TOOL('git', true)], sdk: SDK(false) };
  const { doc, click, calls } = tauriPage({ builds: [], responses: { check_build_tools: () => report, start_build: async () => [] } });
  await tick();
  doc.getElementById('buildIso').value = '/isos/old.iso';
  click(doc.getElementById('startBuild'));
  await tick(); await tick();
  assert.equal(doc.getElementById('sdkPrompt').hidden, false);
  click(doc.getElementById('closeBuild'));
  await tick();
  assert.equal(doc.getElementById('buildPanel').hidden, true);
  assert.equal(doc.getElementById('sdkPrompt').hidden, true, 'the prompt closes with the panel');
  click(doc.getElementById('openBuild'));
  await tick();
  assert.equal(doc.getElementById('sdkPrompt').hidden, true);
  assert.equal(doc.getElementById('startBuild').disabled, false);
  doc.getElementById('buildIso').value = '/isos/new.iso';
  click(doc.getElementById('startBuild'));
  await tick(); await tick();
  click(doc.getElementById('sdkYes'));
  await tick(); await tick();
  const builds = calls.filter(c => c.command === 'start_build');
  assert.equal(builds.length, 1);
  assert.equal(builds[0].args.request.iso, '/isos/new.iso');
});

test('Missing game sources are listed and downloaded only after the user agrees', async () => {
  const sources = { repository: 'https://github.com/o/r', commit: 'a'.repeat(40) };
  const report = { ready: true, tools: [TOOL('git', true)], sdk: SDK(true), sources };
  const { doc, click, calls } = tauriPage({ builds: [], responses: { check_build_tools: () => report, start_build: async () => [] } });
  await tick();
  assert.match(doc.getElementById('toolList').textContent, /Game sources \(aaaaaaaa\)/);
  click(doc.getElementById('startBuild'));
  await tick(); await tick();
  assert.match(doc.getElementById('sdkPromptText').textContent, /game sources/);
  assert.doesNotMatch(doc.getElementById('sdkPromptText').textContent, /ReXGlue SDK/);
  click(doc.getElementById('sdkYes'));
  await tick(); await tick();
  const { request } = calls.find(c => c.command === 'start_build').args;
  assert.equal(request.downloadSources, true);
  assert.equal(request.downloadSdk, false);
});

test('A stale SDK is shown as needing a rebuild and asks before it is rebuilt', async () => {
  const report = { ready: true, tools: [TOOL('git', true)], sdk: { ...SDK(false), stale: true } };
  const { doc, click, calls } = tauriPage({ builds: [], responses: { check_build_tools: () => report, start_build: async () => [] } });
  await tick();
  assert.match(doc.getElementById('toolList').textContent, /another version or patch set/);
  click(doc.getElementById('startBuild'));
  await tick(); await tick();
  assert.match(doc.getElementById('sdkPromptText').textContent, /rebuild of the ReXGlue SDK/);
  click(doc.getElementById('sdkYes'));
  await tick(); await tick();
  assert.equal(calls.find(c => c.command === 'start_build').args.request.downloadSdk, true);
});

test('Warnings are listed but do not block the build', async () => {
  const report = { ready: true, tools: [TOOL('git', true)], sdk: SDK(true), warnings: ['No Vulkan driver was found.'] };
  const { doc, click, calls } = tauriPage({ builds: [], responses: { check_build_tools: () => report, start_build: async () => [] } });
  await tick();
  const warn = doc.querySelector('#toolList li.warn');
  assert.match(warn.textContent, /No Vulkan driver/);
  click(doc.getElementById('startBuild'));
  await tick(); await tick();
  assert.equal(calls.some(c => c.command === 'start_build'), true);
});
