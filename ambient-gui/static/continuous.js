class AmbientContinuousPlayer {
  constructor({ request, getConfig, onState, onBusy, onStatus, onQueue, onRetry, onSegment }) {
    this.request = request;
    this.getConfig = getConfig;
    this.onState = onState;
    this.onBusy = onBusy;
    this.onStatus = onStatus;
    this.onQueue = onQueue;
    this.onRetry = onRetry;
    this.onSegment = onSegment;
    this.slots = [document.getElementById("playerA"), document.getElementById("playerB")];
    this.context = null;
    this.nodes = [];
    this.active = false;
    this.playing = false;
    this.generating = false;
    this.transitioning = false;
    this.id = 0;
    this.current = 0;
    this.currentSegment = 0;
    this.nextSegment = 1;
    this.next = null;
    this.timer = null;
    this.fadeTimer = null;
    this.retryTimer = null;
    this.retryCount = 0;
    this.slots.forEach((audio, index) => {
      audio.hidden = true;
      audio.controls = false;
      audio.preload = "auto";
      audio.addEventListener("play", () => this.nativePlay(index));
      audio.addEventListener("pause", () => this.nativePause(index));
      audio.addEventListener("ended", () => this.nativeEnded(index));
      audio.addEventListener("error", () => this.nativeError(index));
    });
  }

  ensureAudio() {
    if (!this.context) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) throw new Error("当前浏览器不支持连续播放所需的 Web Audio");
      this.context = new AudioContext();
      this.nodes = this.slots.map((audio) => {
        const source = this.context.createMediaElementSource(audio);
        const gain = this.context.createGain();
        source.connect(gain);
        gain.connect(this.context.destination);
        return gain;
      });
    }
    this.context.resume().catch(() => {});
  }

  clearTimer(name) {
    if (this[name] !== null) {
      if (name === "timer") clearInterval(this[name]);
      else clearTimeout(this[name]);
      this[name] = null;
    }
  }

  gainAt(index, value) {
    if (!this.nodes[index]) return;
    const now = this.context.currentTime;
    this.nodes[index].gain.cancelScheduledValues(now);
    this.nodes[index].gain.setValueAtTime(value, now);
  }

  clearSlot(index) {
    const audio = this.slots[index];
    audio.pause();
    audio.controls = false;
    audio.hidden = true;
    audio.removeAttribute("src");
    audio.load();
    this.gainAt(index, 0);
  }

  mediaState() {
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = this.active ? (this.playing ? "playing" : "paused") : "none";
  }

  playingStatus() {
    this.onStatus(`第 ${this.currentSegment + 1} 段播放中 · 自动接续已开启`, "success");
    this.mediaState();
  }

  nativePlay(index) {
    if (!this.active || index !== this.current) return;
    this.context.resume().catch(() => {});
    this.playing = true;
    this.playingStatus();
    this.schedule();
  }

  nativePause(index) {
    if (!this.active || index !== this.current || this.transitioning || this.slots[index].ended) return;
    this.playing = false;
    this.clearTimer("timer");
    this.onStatus(`已暂停 · 第 ${this.currentSegment + 1} 段`);
    this.mediaState();
  }

  nativeEnded(index) {
    if (!this.active || index !== this.current) return;
    if (this.next && !this.transitioning) {
      this.crossfade();
    } else if (!this.transitioning) {
      this.playing = false;
      this.clearTimer("timer");
      this.onStatus("本段已结束，正在等待下一段。", "error");
      this.onQueue("下一段尚未就绪，请检查生成状态或手动重试。");
      this.mediaState();
      this.prepareNext();
    }
  }

  nativeError(index) {
    if (!this.active || index !== this.current || !this.slots[index].src) return;
    this.playing = false;
    this.clearTimer("timer");
    this.onStatus("当前音频加载失败，可停止后重新开始。", "error");
    this.mediaState();
  }

  schedule() {
    if (this.timer !== null || !this.active || !this.playing) return;
    this.timer = setInterval(() => this.tick(), 250);
    this.tick();
  }

  tick() {
    if (!this.active || !this.playing || this.transitioning) return;
    const audio = this.slots[this.current];
    if (!Number.isFinite(audio.duration)) return;
    const remaining = Math.max(0, audio.duration - audio.currentTime);
    const prepareAt = Math.min(90, audio.duration * 0.25);
    if (!this.next && !this.generating && this.retryTimer === null && remaining <= prepareAt) this.prepareNext();
    if (this.next && remaining <= Math.min(8, audio.duration / 5)) this.crossfade();
  }

  renderSegment(index) {
    const config = this.getConfig(index);
    if (!config) return null;
    return this.request("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    }).then((result) => {
      note4SyncResult(result);
      return { ...result, config };
    });
  }

  async start(seconds, initialSeed) {
    if (this.active) return;
    this.ensureAudio();
    this.id += 1;
    const id = this.id;
    this.active = true;
    this.playing = false;
    this.current = 0;
    this.currentSegment = 0;
    this.nextSegment = 1;
    this.segmentSeconds = seconds;
    this.initialSeed = initialSeed;
    this.next = null;
    this.generating = false;
    this.transitioning = false;
    this.retryCount = 0;
    this.clearTimer("timer");
    this.clearTimer("fadeTimer");
    this.clearTimer("retryTimer");
    this.clearSlot(0);
    this.clearSlot(1);
    this.slots[0].hidden = false;
    this.gainAt(0, 1);
    this.onRetry(false);
    this.onQueue("");
    this.onState(true);
    this.onBusy(true);
    this.onStatus("正在 NAS 上生成第一段…");
    try {
      const result = await this.renderSegment(0);
      if (id !== this.id) return;
      const audio = this.slots[0];
      audio.src = result.audio;
      audio.load();
      audio.controls = true;
      this.onSegment(result, 1);
      this.onStatus("第一段已生成，正在缓冲…");
      await audio.play();
      if (id !== this.id) return;
      this.playing = true;
      this.playingStatus();
      this.schedule();
    } catch (error) {
      if (id !== this.id) return;
      if (error.name === "NotAllowedError" && this.slots[0].src) {
        this.slots[0].controls = true;
        this.onStatus("第一段已就绪，请按播放键开始连续播放。", "success");
        this.mediaState();
      } else {
        this.stop();
        this.onStatus(error.message, "error");
      }
    } finally {
      if (id === this.id) this.onBusy(false);
    }
  }

  waitForBuffer(audio, id) {
    return new Promise((resolve, reject) => {
      let timeout;
      const cleanup = () => {
        clearTimeout(timeout);
        audio.removeEventListener("canplaythrough", ready);
        audio.removeEventListener("progress", ready);
        audio.removeEventListener("error", failed);
      };
      const ready = () => {
        if (id !== this.id) {
          cleanup();
          reject(new Error("连续播放已停止"));
          return;
        }
        const buffered = audio.buffered.length && Number.isFinite(audio.duration) && audio.buffered.end(audio.buffered.length - 1) >= audio.duration - 0.25;
        if (audio.readyState >= 4 || buffered) {
          cleanup();
          resolve();
        }
      };
      const failed = () => {
        cleanup();
        reject(new Error("下一段音频缓冲失败"));
      };
      timeout = setTimeout(() => {
        cleanup();
        reject(new Error("下一段缓冲超时"));
      }, 45000);
      audio.addEventListener("canplaythrough", ready);
      audio.addEventListener("progress", ready);
      audio.addEventListener("error", failed);
      ready();
    });
  }

  async prepareNext() {
    if (!this.active || this.next || this.generating || this.transitioning || this.retryTimer !== null) return;
    const config = this.getConfig(this.nextSegment);
    if (!config) return;
    const id = this.id;
    const index = this.nextSegment;
    const slot = 1 - this.current;
    this.generating = true;
    this.clearTimer("retryTimer");
    this.onRetry(false);
    this.onQueue(`正在生成第 ${index + 1} 段…`);
    try {
      const result = await this.renderSegment(index);
      if (id !== this.id) return;
      const audio = this.slots[slot];
      audio.src = result.audio;
      audio.load();
      await this.waitForBuffer(audio, id);
      if (id !== this.id) return;
      this.next = { ...result, index, slot };
      this.retryCount = 0;
      this.onQueue(`第 ${index + 1} 段已缓冲，将在本段结尾接入`);
      if (this.slots[this.current].ended) this.crossfade();
    } catch (error) {
      if (id !== this.id) return;
      if (error.status === 429 && this.retryCount < 3) {
        this.retryCount += 1;
        this.onQueue("NAS 正在完成另一项渲染，将在 5 秒后重试下一段");
        this.retryTimer = setTimeout(() => {
          this.clearTimer("retryTimer");
          this.prepareNext();
        }, 5000);
      } else {
        this.onQueue(`下一段暂未就绪：${error.message}`);
        this.onRetry(true);
        this.onStatus("当前段继续播放；下一段需要重试。", "error");
      }
    } finally {
      if (id === this.id) this.generating = false;
    }
  }

  async crossfade() {
    if (!this.active || !this.next || this.transitioning) return;
    const id = this.id;
    const oldIndex = this.current;
    const oldAudio = this.slots[oldIndex];
    const next = this.next;
    const newAudio = this.slots[next.slot];
    this.transitioning = true;
    oldAudio.controls = false;
    newAudio.controls = false;
    oldAudio.hidden = true;
    newAudio.hidden = false;
    this.onRetry(false);
    try {
      newAudio.currentTime = 0;
      await this.context.resume();
      await newAudio.play();
      if (id !== this.id) return;
      const duration = Number.isFinite(oldAudio.duration) ? oldAudio.duration : this.segmentSeconds;
      const fade = Math.max(0.1, Math.min(8, duration / 5, duration - oldAudio.currentTime));
      const now = this.context.currentTime;
      this.nodes[oldIndex].gain.cancelScheduledValues(now);
      this.nodes[next.slot].gain.cancelScheduledValues(now);
      this.nodes[oldIndex].gain.setValueAtTime(this.nodes[oldIndex].gain.value, now);
      this.nodes[next.slot].gain.setValueAtTime(0, now);
      this.nodes[oldIndex].gain.linearRampToValueAtTime(0, now + fade);
      this.nodes[next.slot].gain.linearRampToValueAtTime(1, now + fade);
      this.current = next.slot;
      this.currentSegment = next.index;
      this.nextSegment = Math.max(this.nextSegment, next.index + 1);
      this.next = null;
      this.onSegment(next, next.index + 1);
      this.playing = true;
      this.playingStatus();
      this.onQueue(`第 ${this.nextSegment + 1} 段将在本段播放中自动准备`);
      this.schedule();
      this.fadeTimer = setTimeout(() => {
        if (id !== this.id) return;
        this.clearSlot(oldIndex);
        newAudio.controls = true;
        this.transitioning = false;
        this.tick();
      }, fade * 1000 + 100);
    } catch (error) {
      if (id !== this.id) return;
      this.clearSlot(next.slot);
      this.gainAt(oldIndex, 1);
      oldAudio.hidden = false;
      oldAudio.controls = true;
      this.next = null;
      this.transitioning = false;
      this.onQueue("接续未能开始，请重试下一段。");
      this.onRetry(true);
      this.onStatus(error.message, "error");
    }
  }

  announceRecipeChange() {
    if (!this.active) return;
    if (this.next) this.onQueue(`第 ${this.next.index + 1} 段已缓存，新调整将在随后一段生效`);
    else if (!this.generating) this.onQueue("新配方将用于下一段");
  }

  pause() {
    if (!this.active) return;
    if (this.transitioning) {
      this.clearTimer("fadeTimer");
      this.transitioning = false;
      const old = 1 - this.current;
      this.clearSlot(old);
      this.gainAt(this.current, 1);
      this.slots[this.current].controls = true;
    }
    this.slots[this.current].pause();
  }

  resume() {
    if (!this.active) return;
    this.ensureAudio();
    this.slots[this.current].play().catch((error) => this.onStatus(error.message, "error"));
  }

  stop() {
    if (!this.active && !this.slots.some((audio) => audio.src)) return;
    this.id += 1;
    this.active = false;
    this.playing = false;
    this.generating = false;
    this.transitioning = false;
    this.next = null;
    this.clearTimer("timer");
    this.clearTimer("fadeTimer");
    this.clearTimer("retryTimer");
    this.clearSlot(0);
    this.clearSlot(1);
    if (this.context) this.context.suspend().catch(() => {});
    this.onBusy(false);
    this.onRetry(false);
    this.onQueue("");
    this.onState(false);
    this.onStatus("已停止连续播放；已生成的音频仍在保留期内。", "success");
    this.mediaState();
  }
}
