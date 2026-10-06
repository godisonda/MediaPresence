let socket = null;
let reconnectTimer = null;
let mainLoopTimer = null;
let lastStateKey = "";

function isContextValid() {
  return typeof chrome !== "undefined" && Boolean(chrome.runtime && chrome.runtime.id);
}

function cleanupInvalidContext() {
  if (mainLoopTimer) clearInterval(mainLoopTimer);
  if (reconnectTimer) clearTimeout(reconnectTimer);
  if (socket) {
    try { socket.close(); } catch (e) {}
    socket = null;
  }
}

function parseTime(str) {
  if (!str) return 0;
  const p = str.trim().split(":").map(Number);
  if (p.length === 2) return p[0] * 60 + p[1];
  if (p.length === 3) return p[0] * 3600 + p[1] * 60 + p[2];
  return 0;
}

function clickElement(el) {
  if (!el) return false;
  const target = el.closest("button") || el;
  const rect = target.getBoundingClientRect();
  const clientX = rect.left + rect.width / 2;
  const clientY = rect.top + rect.height / 2;

  const eventOpts = {
    bubbles: true,
    cancelable: true,
    view: window,
    clientX: clientX,
    clientY: clientY
  };

  ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach((type) => {
    target.dispatchEvent(new MouseEvent(type, eventOpts));
  });

  if (typeof target.click === "function") {
    target.click();
  }
  return true;
}

function getMediaInfo() {
  const isYT = location.hostname.includes("youtube.com");
  const isYM = location.hostname.includes("music.yandex");

  if (!isYT && !isYM) return null;

  if (isYT) {
    if (!location.pathname.startsWith("/watch")) return null;
    const video = document.querySelector("video");
    if (!video) return null;

    let title = "";
    const tEl = document.querySelector("h1.ytd-watch-metadata yt-formatted-string") ||
                document.querySelector("#title h1 yt-formatted-string");
    title = tEl ? tEl.innerText.trim() : document.title.replace(" - YouTube", "").trim();

    let channel = "YouTube";
    const cEl = document.querySelector("#upload-info #channel-name a") ||
                document.querySelector("ytd-channel-name a");
    if (cEl) channel = cEl.innerText.trim();

    const vId = new URLSearchParams(window.location.search).get("v");
    const coverUrl = vId ? `https://img.youtube.com/vi/${vId}/hqdefault.jpg` : "";

    return {
      platform: "YouTube",
      title: title,
      channel: channel,
      url: window.location.href,
      coverUrl: coverUrl,
      currentTime: Math.floor(video.currentTime || 0),
      duration: Math.floor(video.duration || 0),
      isPaused: Boolean(video.paused)
    };
  }

  if (isYM) {
    let title = "";
    let artist = "";
    let coverUrl = "";
    let currentTime = 0;
    let duration = 0;
    let isPaused = true;

    if (navigator.mediaSession && navigator.mediaSession.metadata) {
      const meta = navigator.mediaSession.metadata;
      title = meta.title || "";
      artist = meta.artist || "";
      if (meta.artwork && meta.artwork.length > 0) {
        coverUrl = meta.artwork[meta.artwork.length - 1].src || "";
      }
    }

    if (!title) {
      const tEl = document.querySelector("[data-test-id='player-track-name'], .d-track__title, [class*='trackName'], [class*='TrackName']");
      if (tEl) title = tEl.innerText.trim();
    }
    if (!artist) {
      const aEl = document.querySelector("[data-test-id='player-author-name'], .d-track__artists, [class*='authorName'], [class*='AuthorName']");
      if (aEl) artist = aEl.innerText.trim();
    }
    if (!coverUrl) {
      const cImg = document.querySelector("[data-test-id='player-cover-image'] img, [class*='Cover'] img, [class*='cover'] img, .track-cover img");
      if (cImg && cImg.src) {
        coverUrl = cImg.src.startsWith("//") ? "https:" + cImg.src : cImg.src;
      }
    }
    if (coverUrl) {
      coverUrl = coverUrl.replace(/%%\d+x\d+/, "400x400").replace(/\d+x\d+$/, "400x400");
    }

    const audios = Array.from(document.querySelectorAll("audio"));
    const activeAudio = audios.find(a => !isNaN(a.duration) && a.duration > 0);

    if (activeAudio) {
      currentTime = Math.floor(activeAudio.currentTime || 0);
      duration = Math.floor(activeAudio.duration || 0);
      isPaused = Boolean(activeAudio.paused);
    }

    if (duration === 0) {
      const allText = Array.from(document.querySelectorAll("span, div, p"))
        .map(el => (el.innerText ? el.innerText.trim() : ""));

      const slashTime = allText.find(t => /^\d{1,2}:\d{2}\s*\/\s*\d{1,2}:\d{2}$/.test(t));
      if (slashTime) {
        const parts = slashTime.split("/").map(s => s.trim());
        currentTime = parseTime(parts[0]);
        duration = parseTime(parts[1]);
      }
    }

    if (!activeAudio) {
      const playBtn = document.querySelector("button[aria-label*='Воспроизведение'], [class*='VibePlayerControls_playButton']");
      const pauseBtn = document.querySelector("button[aria-label*='Пауза']");
      isPaused = Boolean(playBtn && !pauseBtn);
    }

    if (!title) return null;

    return {
      platform: "Яндекс Музыка",
      title: title,
      channel: artist || "Яндекс Музыка",
      url: window.location.href,
      coverUrl: coverUrl,
      currentTime: currentTime,
      duration: duration,
      isPaused: isPaused
    };
  }

  return null;
}

function executePlayerCommand(action) {
  const isYT = location.hostname.includes("youtube.com");
  const isYM = location.hostname.includes("music.yandex");

  if (isYM) {
    if (action === "toggle") {
      const vibeContainer = document.querySelector("[class*='VibePlayerControls_root']");
      if (vibeContainer) {
        const buttons = Array.from(vibeContainer.querySelectorAll("button"));
        if (buttons.length >= 3) {
          clickElement(buttons[1]);
          return;
        }
      }

      const playPauseBtn = 
        document.querySelector("button[class*='VibePlayerControls_playButton']") ||
        document.querySelector("button[aria-label='Пауза']") ||
        document.querySelector("button[aria-label='Воспроизведение']") ||
        document.querySelector("[data-test-id='player-pause-button']") ||
        document.querySelector("[data-test-id='player-play-button']") ||
        document.querySelector(".player-controls__btn_play");

      if (playPauseBtn) {
        clickElement(playPauseBtn);
      }
    } else if (action === "next") {
      const nextBtn = 
        document.querySelector("button[aria-label*='Следующая песня']") ||
        document.querySelector("button[class*='VibePlayerControls_skipButton']") ||
        document.querySelector("[data-test-id='player-next-track']");
      clickElement(nextBtn);
    } else if (action === "prev") {
      const prevBtn = 
        document.querySelector("button[aria-label*='Предыдущая песня']") ||
        document.querySelector("[data-test-id='player-prev-track']");
      clickElement(prevBtn);
    }
  } else if (isYT) {
    const video = document.querySelector("video");
    if (action === "toggle") {
      if (video) video.paused ? video.play() : video.pause();
      else clickElement(document.querySelector(".ytp-play-button"));
    } else if (action === "next") {
      clickElement(document.querySelector(".ytp-next-button"));
    } else if (action === "prev") {
      if (video) video.currentTime = 0;
    }
  }
}

function sendMediaState(force = false) {
  if (!isContextValid()) {
    cleanupInvalidContext();
    return;
  }

  if (!socket || socket.readyState !== WebSocket.OPEN) return;

  const data = getMediaInfo();
  if (!data) return;

  const currentKey = `${data.title}|${data.channel}|${data.coverUrl}|${data.isPaused}|${data.currentTime}|${data.duration}`;
  if (!force && currentKey === lastStateKey) return;
  lastStateKey = currentKey;

  try {
    chrome.storage.local.get(["rpc_token"], (res) => {
      if (!isContextValid()) {
        cleanupInvalidContext();
        return;
      }
      const token = res ? res.rpc_token : null;
      if (!token) return;

      socket.send(JSON.stringify({
        type: "media_update",
        token: token,
        data: data
      }));
    });
  } catch (e) {
    cleanupInvalidContext();
  }
}

function connectWebSocket() {
  if (!isContextValid()) {
    cleanupInvalidContext();
    return;
  }

  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }

  try {
    socket = new WebSocket("ws://localhost:6412");
  } catch (e) {
    return;
  }

  socket.onopen = () => {
    sendMediaState(true);
  };

  socket.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg && msg.command) {
        executePlayerCommand(msg.command);
      }
    } catch (e) {}
  };

  socket.onclose = () => {
    socket = null;
    if (isContextValid()) {
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connectWebSocket, 2000);
    }
  };

  socket.onerror = () => {
    if (socket) socket.close();
  };
}

connectWebSocket();

mainLoopTimer = setInterval(() => {
  if (!isContextValid()) {
    cleanupInvalidContext();
    return;
  }
  connectWebSocket();
  sendMediaState(false);
}, 500);