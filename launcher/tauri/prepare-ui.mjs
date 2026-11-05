// Builds dist/index.html from the shared launcher page (also used by the
// Windows Launcher.ps1) plus the Tauri-only settings panel and host bridge.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const source = fileURLToPath(new URL('../v6_borderless_final.html', import.meta.url));
let html = readFileSync(source, 'utf8');
const bridge = readFileSync(new URL('./bridge.js', import.meta.url), 'utf8');

function inject(marker, replacement) {
  if (!html.includes(marker)) throw new Error(`Launcher HTML no longer contains: ${marker}`);
  html = html.replace(marker, replacement);
}

const panelStyle = `<style>
  .winctl{display:flex;gap:2px}
  .wico-gear{width:auto;height:auto;font:12px/1 var(--data)}
  #launchStatus{position:absolute;left:8%;right:8%;bottom:1.6%;z-index:6;min-height:12px;
    font:10px/1.3 var(--data);color:var(--bone);text-align:center;text-shadow:0 1px 3px #000;pointer-events:none}
  .panel{position:absolute;inset:44px 18px 18px;z-index:8;overflow-y:auto;padding:14px 16px;
    background:rgba(8,6,5,.97);border:1px solid rgba(122,106,76,.35);box-shadow:0 6px 18px rgba(0,0,0,.55);
    font:11px/1.4 var(--data);color:var(--bone)}
  .panel[hidden]{display:none}
  .panel h2{margin:0 0 8px;font:400 13px var(--disp);letter-spacing:.08em;text-transform:uppercase;color:#e2d7bd}
  .panel label{display:block;margin:9px 0;color:var(--bone-dim)}
  .panel label[hidden]{display:none}
  .panel input{display:block;width:100%;margin-top:4px;padding:6px 7px;background:rgba(39,33,28,.8);
    border:1px solid rgba(122,106,76,.45);color:#e2d7bd;font:11px var(--data)}
  .panel input[type=hidden]{display:none}
  .panel .field{display:block;margin:9px 0;color:var(--bone-dim)}
  .panel .field[hidden]{display:none}
  .panel .seg{display:flex;margin-top:4px}
  .panel .seg button{flex:1;padding:6px 0;background:rgba(39,33,28,.8);border:1px solid rgba(122,106,76,.45);color:var(--bone-dim)}
  .panel .seg button+button{border-left:0}
  .panel .seg button.on{background:rgba(110,30,20,.85);border-color:rgba(158,43,28,.7);color:#e9dcbf}
  .panel input::placeholder{color:var(--muted)}
  .panel pre{margin:4px 0 0;white-space:pre-wrap;word-break:break-all;color:var(--muted);font:10px/1.4 var(--data)}
  .panel .acts{display:flex;gap:8px;justify-content:flex-end;margin-top:12px}
  .panel button{padding:6px 14px;background:rgba(46,30,24,.9);color:#e9dcbf;border:1px solid rgba(158,43,28,.55);
    cursor:pointer;font:11px var(--data)}
  .panel button:hover{border-color:var(--crimson-hi)}
  .panel .pick{display:flex;gap:6px;margin-top:4px}
  .panel .pick input{margin-top:0}
  .panel .pick button{padding:0 9px}
  .panel fieldset{margin:9px 0;padding:6px 8px;border:1px solid rgba(122,106,76,.35);color:var(--bone-dim)}
  .panel fieldset[hidden]{display:none}
  .panel fieldset label{display:inline-flex;align-items:center;gap:5px;margin:3px 12px 3px 0;color:var(--bone)}
  .panel fieldset input{display:inline;width:auto;margin:0}
  .panel button:disabled{opacity:.45;cursor:default}
  #buildStep{min-height:14px;margin:8px 0 4px;color:#e2d7bd}
  #buildLog{max-height:150px;overflow-y:auto;padding:6px;background:rgba(0,0,0,.35)}
  #buildLog:empty{display:none}
  #toolList{margin:4px 0 0;padding:0;list-style:none}
  #toolList li{margin:3px 0}
  #toolList .miss{color:#e08a7a}
  #toolList .ok{color:#9bc48a}
  #toolList .warn{color:#e2c07a}
  #toolList small{display:block;margin-left:16px;color:var(--muted)}
  #toolList a{color:#e2d7bd}
  #sdkPrompt{margin:8px 0;padding:8px 10px;border:1px solid rgba(158,43,28,.55);background:rgba(46,30,24,.55)}
  #sdkPrompt[hidden]{display:none}
  #wingetRow{margin:6px 0 0}
  #wingetRow[hidden]{display:none}
  #wingetRow small{display:block;margin-top:4px;color:var(--muted)}
</style>`;

inject('<div class="stage">', `${panelStyle}
<div class="stage">
  <div id="launchStatus" role="status" aria-live="polite"></div>
  <section id="setup" class="panel" hidden aria-label="Launch settings">
    <h2>Launch settings</h2>
    <label>Game folder<input id="gameDir" type="text" spellcheck="false"></label>
    <label>Save folder<input id="userDataRoot" type="text" spellcheck="false"></label>
    <label>Update save folder<input id="userDataRootUpdate" type="text" spellcheck="false"></label>
    <label id="deviceLabel">Vulkan device (blank = automatic)<input id="vulkanDevice" type="number" min="0" max="32"></label>
    <div id="videoLabel" class="field">Display server<input id="videoDriver" type="hidden"><span class="seg" role="radiogroup" aria-label="Display server"><button type="button" role="radio" data-video="">Auto</button><button type="button" role="radio" data-video="wayland">Wayland</button><button type="button" role="radio" data-video="x11">X11</button></span></div>
    <label>Builds found<pre id="buildList"></pre></label>
    <p>Empty fields use the folder shown. The title update uses the same game folder as Base (its update/ folder holds the update) but keeps separate saves. Use the in-game F4 menu for key bindings.</p>
    <p id="launcherVersion"></p>
    <div class="acts"><button id="openBuild" type="button" hidden>Build from disc image…</button><button id="cancelSetup" type="button">Cancel</button><button id="saveSetup" type="button">Save</button></div>
  </section>
  <section id="buildPanel" class="panel" hidden aria-label="Build the game">
    <h2>Build the game</h2>
    <p id="buildIntro">Builds the game from your own copy: the USA Ultimate Evil Edition disc image, plus the USA Title Update package for update builds. The first build takes a while; later builds reuse finished steps.</p>
    <label>Disc image (ISO)<span class="pick"><input id="buildIso" type="text" spellcheck="false"><button type="button" data-pick="iso" aria-label="Browse for disc image">…</button></span></label>
    <label>Title Update package (optional)<span class="pick"><input id="buildTitleUpdate" type="text" spellcheck="false" placeholder="Path to the title update package"><button type="button" data-pick="titleUpdate" aria-label="Browse for title update">…</button></span></label>
    <fieldset id="buildVariants"><legend>What to build</legend>
      <label><input id="optUpdate" type="checkbox">Title Update</label>
      <label><input id="optExtras" type="checkbox" checked>Optional PC features</label>
      <p id="buildSummary"></p>
    </fieldset>
    <label id="cmakeLabel">CMake 3.25+ (blank = from PATH)<span class="pick"><input id="buildCmake" type="text" spellcheck="false"><button type="button" data-pick="cmake" aria-label="Browse for CMake">…</button></span></label>
    <label id="toolsLabel">Build tools<ul id="toolList"></ul></label>
    <div id="wingetRow" hidden><button id="installTools" type="button">Install missing tools with winget</button><small id="wingetNote"></small></div>
    <pre id="buildLog"></pre>
    <div id="sdkPrompt" role="alertdialog" aria-label="Download the ReXGlue SDK" hidden>
      <span id="sdkPromptText"></span>
      <div class="acts"><button id="sdkNo" type="button">Not now</button><button id="sdkYes" type="button">Download and build</button></div>
    </div>
    <div id="buildStep" role="status" aria-live="polite"></div>
    <div class="acts"><button id="recheckTools" type="button">Check tools</button><button id="closeBuild" type="button">Close</button><button id="cancelBuild" type="button" hidden>Cancel build</button><button id="startBuild" type="button">Build</button></div>
  </section>`);
inject('<button id="winClose"', '<button id="setupBtn" class="wbtn" type="button" aria-label="Launch settings" title="Launch settings"><span class="wico wico-gear">⚙</span></button>\n    <button id="winClose"');
inject('</script>', `</script>\n<script>\n${bridge}</script>`);

html = '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>' + html + '</body></html>';
mkdirSync(new URL('./dist', import.meta.url), { recursive: true });
writeFileSync(new URL('./dist/index.html', import.meta.url), html);
