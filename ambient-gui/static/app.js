const state = { presets: [], parameters: [], selected: 0, values: {}, group: "layers", busy: false, ready: false, selection: 0, authRequired: false, note4: null, syncEnabled: false, note4Busy: false, note4Reading: false, note4Timer: null, fields: [], currentField: -1, fieldBusy: false };
const accents = ["#c9d7b0", "#a7b8cb", "#c3accb", "#dfc671", "#90b4c1", "#9abca4", "#d8dbd3", "#a7b2d5"];
const engineNames = ["Garden", "Departures", "Voices", "Afternoon", "Night Bus", "Shoreline", "Glass", "Tides"];
const groupNames = { layers: "声部", motion: "动态", space: "空间", tone: "音色" };
const parameterNames = {
  pad: "声床", bells: "钟声", bass: "低音", pulse: "脉冲",
  density: "音符密度", evolve: "演化", drift: "和声漂移", hits: "节奏密度",
  echo: "回声", reverb: "混响", size: "空间大小", bright: "明亮度",
  swell: "音量起伏", bell_tone: "钟声质感", motion: "呼吸幅度", tempo: "速度",
  bell_oct: "钟声八度", pad_tone: "声床音色",
};
const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

function showLogin() {
  $("loginError").textContent = "";
  if (!$("loginDialog").open) $("loginDialog").showModal();
}

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (response.status === 401) {
    $("loginButton").hidden = false;
    if (path !== "/api/login") showLogin();
  }
  if (!response.ok) {
    const error = new Error(body.error || `请求失败（${response.status}）`);
    error.status = response.status;
    throw error;
  }
  return body;
}

function setStatus(message, kind = "") {
  $("status").textContent = message;
  $("status").className = `status ${kind}`;
}

function renderNote4() {
  const device = state.note4 || { managerOnline: false, connected: false, phase: "manager_offline", syncState: "off" };
  const phases = {
    manager_offline: "管理端未运行", offline: "未连接", starting: "正在建立会话",
    startup_display: "正在推送启动图", generating: "正在生成音频", loading_display: "正在推送加载页",
    cover_display: "正在推送封面", ready: "画面已就绪", playing: "音频推送 / 播放中",
    closing: "正在释放连接", unknown: "结果未知 · 不重试", error: "会话异常结束",
  };
  const preset = state.presets[device.preset] || state.fields[device.preset - 8];
  $("note4State").textContent = `NOTE4 · ${phases[device.phase] || device.phase}`;
  $("note4Led").className = `note4-led ${device.connected ? "connected" : ""} ${["unknown", "error"].includes(device.phase) ? "error" : ""}`;
  if (!device.managerOnline) {
    $("note4Detail").textContent = "管理端离线；不会发起新连接或排队补推";
  } else if (!device.connected) {
    $("note4Detail").textContent = device.syncState === "rejected_offline" ? "设备未连接，本次音频没有推送" : "管理端在线，等待你在 NOTE4 上主动连接";
  } else {
    const details = [preset ? preset.title : "当前声景", device.preset >= 8 ? "完整实地录音" : `种子 ${device.seed ?? "--"}`, `${device.seconds ?? "--"} 秒`];
    if (device.battery !== null && device.battery !== undefined) details.push(`电量 ${device.battery}%`);
    if (device.volume !== null && device.volume !== undefined) details.push(`音量 ${Math.round(device.volume / 25) + 1} 档`);
    if (device.syncState === "queued") details.push("下一段已排队");
    if (device.syncState === "received") details.push("同步请求已接收");
    $("note4Detail").textContent = details.join(" · ");
  }
  $("syncPush").checked = state.syncEnabled;
  $("syncPush").disabled = state.note4Busy;
  $("syncNote").textContent = state.syncEnabled
    ? device.connected ? "后续提前生成的段会排队，不提前切歌" : "已开启；离线生成不会补推"
    : "仅网页播放，不占用 NOTE4";
}

function applyNote4(data) {
  state.syncEnabled = Boolean(data.syncEnabled);
  state.note4 = data.device;
  renderNote4();
}

async function refreshNote4() {
  if (state.note4Reading) return;
  state.note4Reading = true;
  try {
    applyNote4(await request("/api/note4"));
  } catch (_) {
    state.note4 = { managerOnline: false, connected: false, phase: "manager_offline", syncState: "off" };
    renderNote4();
  } finally {
    state.note4Reading = false;
  }
}

function note4SyncResult(result) {
  if (!result.note4) return;
  state.syncEnabled = result.note4.enabled;
  if (result.note4.requested && state.note4) {
    state.note4.syncId = result.note4.id;
    state.note4.syncState = "received";
  } else if (result.note4.reason === "offline" && state.note4) {
    state.note4.syncState = "rejected_offline";
  }
  renderNote4();
}

function renderPresets() {
  $("presetGrid").innerHTML = state.presets.map((preset) => `
    <button class="preset-card ${preset.id === state.selected ? "selected" : ""}" data-preset="${preset.id}" aria-pressed="${preset.id === state.selected}" style="--scene:${accents[preset.id]}" ${state.busy ? "disabled" : ""}>
      <img src="/covers/${preset.name}.png" alt="${escapeHtml(preset.title)}封面" width="400" height="300" loading="lazy">
      <span class="patch-number">${String(preset.id + 1).padStart(2, "0")}</span>
      <div class="preset-info">
        <h3>${escapeHtml(preset.title)}</h3>
        <p>${escapeHtml(preset.description)}</p>
        <div class="preset-meta"><span>${escapeHtml(engineNames[preset.id])}</span><span>${preset.format}</span></div>
      </div>
    </button>`).join("");
  document.querySelectorAll("[data-preset]").forEach((button) => {
    button.addEventListener("click", () => selectPreset(Number(button.dataset.preset)));
  });
}

function formatDuration(seconds) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function renderFields() {
  const audio = $("fieldAudio");
  $("fieldGrid").innerHTML = state.fields.map((field, index) => {
    const playing = state.currentField === index && !audio.paused;
    return `<article class="field-card ${playing ? "playing" : ""}">
      <img src="/covers/${field.name}.png" alt="${escapeHtml(field.title)}实地录音封面" width="400" height="300" loading="lazy">
      <div class="field-info">
        <h3>${escapeHtml(field.title)}</h3>
        <p>${escapeHtml(field.description)}</p>
        <div class="field-meta"><span>${formatDuration(field.seconds)} / FULL</span><span>${escapeHtml(field.license)}</span></div>
        <div class="field-actions">
          <button class="field-play" type="button" data-field="${index}" ${state.fieldBusy ? "disabled" : ""}>${playing ? "PAUSE / 暂停" : "PLAY / 播放"}</button>
          <span class="field-credit">${escapeHtml(field.author)} · <a href="${escapeHtml(field.source)}" target="_blank" rel="noopener noreferrer">来源</a></span>
        </div>
      </div>
    </article>`;
  }).join("");
  document.querySelectorAll("[data-field]").forEach((button) => button.addEventListener("click", () => playField(Number(button.dataset.field))));
}

async function playField(index) {
  const field = state.fields[index];
  const audio = $("fieldAudio");
  if (!field || state.fieldBusy) return;
  if (state.currentField === index) {
    if (audio.paused) await audio.play().catch((error) => setStatus(error.message, "error"));
    else audio.pause();
    renderFields();
    return;
  }
  state.fieldBusy = true;
  if (player.active) player.stop();
  state.currentField = index;
  $("fieldPlayer").hidden = false;
  $("fieldSource").href = field.source;
  $("fieldCaption").textContent = `${field.title} · ${formatDuration(field.seconds)} · 完整音轨`;
  audio.src = `/field-audio/${field.audio}`;
  audio.loop = true;
  renderFields();
  try {
    await audio.play();
    if (state.syncEnabled) {
      const result = await request("/api/field/play", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: field.id }),
      });
      note4SyncResult(result);
    }
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    state.fieldBusy = false;
    renderFields();
  }
}

function renderTabs() {
  const groups = [...new Set(state.parameters.map((parameter) => parameter.group))];
  $("parameterTabs").innerHTML = groups.map((group) => `
    <button type="button" class="parameter-tab ${group === state.group ? "active" : ""}" data-group="${group}" role="tab" aria-selected="${group === state.group}" aria-controls="parameterGroups" ${state.busy ? "disabled" : ""}>${groupNames[group] || group}</button>`).join("");
  document.querySelectorAll("[data-group]").forEach((button) => {
    button.addEventListener("click", () => {
      state.group = button.dataset.group;
      renderTabs();
      renderParameters();
    });
  });
}

function displayValue(parameter, value) {
  if (parameter.name === "pad_tone") return value ? "Voices" : "Rhodes";
  if (parameter.name === "tempo") return `${value} BPM`;
  return value;
}

function knobAngle(input, value) {
  return -135 + ((value - Number(input.min)) / (Number(input.max) - Number(input.min))) * 270;
}

function renderParameters() {
  const parameters = state.parameters.filter((parameter) => parameter.group === state.group);
  $("parameterGroups").innerHTML = parameters.map((parameter) => {
    const value = state.values[parameter.name] ?? parameter.min;
    const shown = displayValue(parameter, value);
    return `<div class="knob-control">
      <label class="parameter-label" for="param-${parameter.name}"><span>${escapeHtml(parameterNames[parameter.name])}</span><small>${escapeHtml(parameter.label)}</small></label>
      <div class="knob-shell" style="--angle:${-135 + ((value - parameter.min) / (parameter.max - parameter.min)) * 270}deg">
        <input class="knob-input" id="param-${parameter.name}" data-name="${parameter.name}" type="range" min="${parameter.min}" max="${parameter.max}" step="1" value="${value}" aria-label="${escapeHtml(parameterNames[parameter.name])} ${escapeHtml(parameter.label)}" aria-valuetext="${escapeHtml(shown)}" title="拖动或使用方向键调整" ${state.busy ? "disabled" : ""}>
        <span class="knob-body" aria-hidden="true"></span>
      </div>
      <output id="value-${parameter.name}" class="parameter-value" for="param-${parameter.name}">${shown}</output>
    </div>`;
  }).join("");
  document.querySelectorAll("input[type=range]").forEach((input) => {
    input.addEventListener("input", () => {
      const value = Number(input.value);
      state.values[input.dataset.name] = value;
      const parameter = state.parameters.find((item) => item.name === input.dataset.name);
      const shown = displayValue(parameter, value);
      input.parentElement.style.setProperty("--angle", `${knobAngle(input, value)}deg`);
      input.setAttribute("aria-valuetext", shown);
      $(`value-${input.dataset.name}`).textContent = shown;
      player.announceRecipeChange();
    });
  });
}

function syncTransport() {
  $("renderButton").disabled = state.busy || !state.ready || player.active;
  $("renderButtonLabel").textContent = player.active ? "ACTIVE / 连续播放" : "START / 连续生成";
  $("stopPlayback").hidden = !player.active;
  $("seconds").disabled = state.busy || player.active;
  $("seed").disabled = state.busy || player.active;
}

function setBusy(busy) {
  state.busy = busy;
  renderPresets();
  renderTabs();
  renderParameters();
  syncTransport();
  $("resetParameters").disabled = busy;
}

async function selectPreset(index) {
  if (state.busy || !state.presets[index]) return;
  const selection = ++state.selection;
  state.selected = index;
  state.ready = false;
  syncTransport();
  const preset = state.presets[index];
  document.documentElement.style.setProperty("--accent", "#e85a24");
  document.documentElement.style.setProperty("--scene", accents[index]);
  $("selectedCover").src = `/covers/${preset.name}.png`;
  $("selectedCover").alt = `${preset.title}情景封面`;
  $("formatBadge").textContent = preset.format;
  $("presetKicker").textContent = engineNames[index].toUpperCase();
  $("presetTitle").textContent = preset.title;
  $("presetDescription").textContent = preset.description;
  renderPresets();
  if (!player.active) setStatus("");
  try {
    const recipe = await request(`/api/recipe?preset=${index}`);
    if (selection !== state.selection) return;
    state.values = recipe.values;
    state.ready = true;
    renderParameters();
    player.announceRecipeChange();
  } catch (error) {
    if (selection === state.selection) setStatus(error.message, "error");
  } finally {
    if (selection === state.selection) syncTransport();
  }
}

function updateSegment(result, index) {
  const preset = state.presets[result.preset];
  $("playerCaption").textContent = `第 ${index} 段 · ${preset.title} · 种子 ${result.seed}`;
  $("downloadLink").href = result.audio;
  $("downloadLink").download = `amb-${preset.name}-${String(result.seed).padStart(5, "0")}-part-${String(index).padStart(3, "0")}.wav`;
  if ("mediaSession" in navigator && window.MediaMetadata) {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: `${preset.title} · 第 ${index} 段`,
      artist: "AMB Atelier · NAS",
      album: "Continuous AMB-1",
      artwork: [{ src: `/covers/${preset.name}.png`, sizes: "400x300", type: "image/png" }],
    });
  }
}

const player = new AmbientContinuousPlayer({
  request,
  getConfig(index) {
    if (!state.ready) return null;
    return {
      preset: state.selected,
      seconds: player.segmentSeconds,
      seed: (player.initialSeed + index) & 65535,
      overrides: { ...state.values },
      ephemeral: true,
      interrupt: index === 0,
    };
  },
  onState(active) {
    $("playerWrap").hidden = !active;
    syncTransport();
  },
  onBusy: setBusy,
  onStatus: setStatus,
  onQueue(message) { $("nextStatus").textContent = message; },
  onRetry(visible) { $("retryNext").hidden = !visible; },
  onSegment: updateSegment,
});

function startAudio() {
  if (state.busy || player.active || !state.ready || !$("seconds").reportValidity() || !$("seed").reportValidity()) return;
  $("fieldAudio").pause();
  $("fieldPlayer").hidden = true;
  renderFields();
  $("playerCaption").textContent = "正在准备第一段…";
  player.start(Number($("seconds").value), Number($("seed").value));
}

async function initialize() {
  try {
    const health = await request("/api/health");
    state.authRequired = health.authRequired;
    $("loginButton").hidden = !health.authRequired;
    if (!health.rendererReady) throw new Error("NAS 渲染器尚未就绪");
    const retention = health.ephemeralRetention;
    $("retentionNote").textContent = retention ? `连续段在 NAS 保留 ${retention / 3600} 小时，下载可长期保存。` : "连续段限时保留，下载可长期保存。";
    const data = await request("/api/presets");
    state.presets = data.presets;
    state.parameters = data.parameters;
    state.fields = data.fields;
    $("loginButton").hidden = true;
    renderPresets();
    renderFields();
    renderTabs();
    await selectPreset(0);
    await refreshNote4();
    if (state.note4Timer === null) state.note4Timer = setInterval(refreshNote4, 2000);
  } catch (error) {
    setStatus(error.message, "error");
  }
}

$("syncPush").addEventListener("change", async (event) => {
  const enabled = event.currentTarget.checked;
  const previous = state.syncEnabled;
  state.note4Busy = true;
  $("syncPush").disabled = true;
  try {
    const data = await request("/api/note4", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    applyNote4(data);
    setStatus(enabled ? "已开启 NOTE4 同步；仅推送之后新生成的音频。" : "已关闭同步；排队段取消，当前播放不中断。", "success");
  } catch (error) {
    state.syncEnabled = previous;
    setStatus(error.message, "error");
  } finally {
    state.note4Busy = false;
    renderNote4();
  }
});
$("renderButton").addEventListener("click", startAudio);
$("stopPlayback").addEventListener("click", () => player.stop());
$("retryNext").addEventListener("click", () => {
  player.retryCount = 0;
  player.prepareNext();
});
$("resetParameters").addEventListener("click", () => selectPreset(state.selected));
$("loginButton").addEventListener("click", showLogin);
$("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = $("loginSubmit");
  submit.disabled = true;
  $("loginError").textContent = "";
  try {
    await request("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: $("tokenInput").value }),
    });
    $("tokenInput").value = "";
    $("loginDialog").close();
    $("loginButton").hidden = true;
    setStatus("已解锁本地渲染。", "success");
    await initialize();
  } catch (error) {
    $("loginError").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});
$("loginCancel").addEventListener("click", () => $("loginDialog").close());
$("tokenInput").addEventListener("input", () => { $("loginError").textContent = ""; });
if ("mediaSession" in navigator) {
  navigator.mediaSession.setActionHandler("play", () => player.resume());
  navigator.mediaSession.setActionHandler("pause", () => player.pause());
  navigator.mediaSession.setActionHandler("stop", () => player.stop());
}
$("fieldAudio").addEventListener("play", () => {
  const field = state.fields[state.currentField];
  if (field) $("fieldCaption").textContent = `${field.title} · ${formatDuration(field.seconds)} · 完整音轨循环`;
  renderFields();
});
$("fieldAudio").addEventListener("pause", () => {
  const field = state.fields[state.currentField];
  if (field && !$("fieldPlayer").hidden) $("fieldCaption").textContent = `${field.title} · 网页已暂停；NOTE4 可独立续播`;
  renderFields();
});
$("fieldAudio").addEventListener("error", () => {
  if ($("fieldAudio").src) setStatus("实地录音加载失败，请检查 NAS 音频库。", "error");
});
window.addEventListener("pagehide", () => {
  player.stop();
  $("fieldAudio").pause();
});
initialize();
