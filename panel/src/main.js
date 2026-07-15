let statusLed;
let historyList;
let themeBtn;
let pinBtn;
let clearBtn;
let sendFileBtn;

let statusText;
let pcIpLabel;
let downloadsPathLabel;
let targetIpLabel;
let authTokenLabel;
let textShareBox;
let sendTextBtn;
let dropZone;

let progressStatusLabel;
let progressSpeedLabel;
let progressBar;

let pairingModal;
let pairingIpLabel;
let pairingApproveBtn;
let pairingRejectBtn;

let socket = null;
let currentSpeed = 0.0;
let currentTransferState = "IDLE";
let currentProgress = 0.0;
let _reconnectDelay = 500;

function connect() {
  socket = new WebSocket("ws://127.0.0.1:59153");

  socket.onopen = () => {
    console.log("WebSocket IPC linked successfully.");
    _reconnectDelay = 500; // reset backoff on successful connect
    statusLed.classList.add("connected");
    statusText.textContent = "ONLINE";
    if (rssiIndicator) rssiIndicator.textContent = "[ |||| ]";
  };

  socket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      handleEvent(payload.event, payload.data);
    } catch (e) {
      console.error("Failed to parse IPC message:", e);
    }
  };

  socket.onclose = () => {
    statusLed.classList.remove("connected");
    statusLed.classList.remove("active");
    statusText.textContent = "OFFLINE";
    progressStatusLabel.textContent = "OFFLINE";
    progressSpeedLabel.textContent = "";
    progressBar.style.width = "0%";
    progressBar.classList.remove("alive");
    currentSpeed = 0.0;
    currentTransferState = "IDLE";
    
    // Exponential backoff: 500ms → 1s → 2s → 4s → max 30s
    const delay = _reconnectDelay;
    _reconnectDelay = Math.min(_reconnectDelay * 2, 30000);
    console.log(`WebSocket IPC closed. Reconnecting in ${delay}ms...`);
    setTimeout(connect, delay);
  };

  socket.onerror = () => {
    socket.close();
  };
}

function handleEvent(event, data) {
  switch (event) {
    case "clipboard_history":
      updateHistoryList(data);
      flashLed();
      break;
      
    case "clipboard_update":
      flashLed();
      break;
      
    case "pairing_status":
      if (data.connected) {
        statusLed.classList.add("connected");
        if (data.ip) {
          targetIpLabel.textContent = data.ip;
          targetIpLabel.style.color = "var(--accent-green)";
        }
      } else {
        statusLed.classList.remove("connected");
        targetIpLabel.textContent = "UNPAIRED";
        targetIpLabel.style.color = "var(--text-secondary)";
      }
      break;

    case "system_info":
      if (data.pc_ip) {
        pcIpLabel.textContent = data.pc_ip;
      }
      if (data.downloads_path) {
        downloadsPathLabel.textContent = data.downloads_path.toUpperCase();
      }
      if (data.auth_token && authTokenLabel) {
        authTokenLabel.textContent = data.auth_token;
      }
      break;
      
    case "transfer_stats":
      currentSpeed = data.speed_mb || 0.0;
      currentTransferState = data.state || "IDLE";
      currentProgress = data.progress_percent || 0;

      if (currentTransferState === "TRANSFERRING") {
        progressStatusLabel.textContent = `SENDING: ${(data.file_name || "FILE").toUpperCase()}`;
        progressStatusLabel.style.color = "var(--text-primary)";
        progressSpeedLabel.textContent = currentSpeed > 0 ? `${currentSpeed.toFixed(1)} MB/S` : "MEASURING...";
        progressBar.style.width = `${currentProgress}%`;
        progressBar.classList.add("alive");
      } else if (currentTransferState === "RECEIVING") {
        progressStatusLabel.textContent = `RECEIVING: ${(data.file_name || "FILE").toUpperCase()}`;
        progressStatusLabel.style.color = "var(--accent-lime)";
        progressSpeedLabel.textContent = currentSpeed > 0 ? `${currentSpeed.toFixed(1)} MB/S` : "MEASURING...";
        progressBar.style.width = `${currentProgress}%`;
        progressBar.classList.add("alive");
      } else if (currentTransferState === "CONNECTING") {
        progressStatusLabel.textContent = "CONNECTING DROP...";
        progressStatusLabel.style.color = "var(--accent-lime)";
        progressSpeedLabel.textContent = "";
        progressBar.style.width = "0%";
        progressBar.classList.add("alive");
      } else if (currentTransferState === "SENT") {
        progressStatusLabel.textContent = `SENT: ${(data.file_name || "FILE").toUpperCase()}`;
        progressStatusLabel.style.color = "var(--accent-green)";
        progressSpeedLabel.textContent = "";
        progressBar.style.width = "100%";
      } else if (currentTransferState === "COMPLETED") {
        progressStatusLabel.textContent = `RECEIVED: ${(data.file_name || "FILE").toUpperCase()}`;
        progressStatusLabel.style.color = "var(--accent-lime)";
        progressSpeedLabel.textContent = "";
        progressBar.style.width = "100%";
        progressBar.classList.remove("alive");
        
        setTimeout(() => {
          if (currentTransferState === "COMPLETED") {
            progressStatusLabel.textContent = "READY";
            progressStatusLabel.style.color = "var(--text-primary)";
            progressBar.style.width = "0%";
          }
        }, 3000);
      } else if (currentTransferState === "ERROR") {
        progressStatusLabel.textContent = (data.error || "TRANSFER ERROR").toUpperCase();
        progressStatusLabel.style.color = "red";
        progressSpeedLabel.textContent = "";
        progressBar.style.width = "0%";
        progressBar.classList.remove("alive");
        
        setTimeout(() => {
          if (currentTransferState === "ERROR") {
            progressStatusLabel.textContent = "READY";
            progressStatusLabel.style.color = "var(--text-primary)";
          }
        }, 3000);
      } else {
        progressStatusLabel.textContent = "READY";
        progressStatusLabel.style.color = "var(--text-primary)";
        progressSpeedLabel.textContent = "";
        progressBar.style.width = "0%";
        progressBar.classList.remove("alive");
      }
      break;
      
    case "pairing_request":
      if (data && data.ip && pairingModal && pairingIpLabel) {
        pairingIpLabel.textContent = data.ip;
        pairingModal.style.display = "flex";
      }
      break;
  }
}

function updateHistoryList(items) {
  if (!items || items.length === 0) {
    historyList.innerHTML = `
      <div class="history-item">
        <span class="icon">•</span>
        <span class="text">CLIPBOARD WAITING...</span>
        <span class="time">--:--</span>
      </div>
    `;
    return;
  }

  historyList.innerHTML = items.map(item => {
    let timeStr = "--:--";
    if (item.timestamp) {
      const parts = item.timestamp.split(" ");
      if (parts.length === 2) {
        const timeParts = parts[1].split(":");
        if (timeParts.length >= 2) {
          timeStr = `${timeParts[0]}:${timeParts[1]}`;
        }
      }
    }
    
    let icon = "•";
    let iconColor = "var(--accent-lime)";
    let displayText = item.content;

    if (item.is_file) {
      if (item.content.startsWith("RCVD: ")) {
        icon = "↓";
        iconColor = "var(--accent-green)";
      } else if (item.content.startsWith("SENT: ")) {
        icon = "↑";
        iconColor = "var(--accent-green)";
      } else {
        icon = "■";
        iconColor = "var(--accent-green)";
      }
    }

    const text = displayText.length > 45 ? displayText.slice(0, 45) + "..." : displayText;
    
    return `
      <div class="history-item">
        <span class="icon" style="color: ${iconColor}; font-weight: bold;">${icon}</span>
        <span class="text">${escapeHtml(text)}</span>
        <span class="time">${timeStr}</span>
      </div>
    `;
  }).join("");
}

function flashLed() {
  statusLed.classList.add("active");
  setTimeout(() => {
    statusLed.classList.remove("active");
  }, 400);
}

function escapeHtml(unsafe) {
  return unsafe
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Initialize
window.addEventListener("DOMContentLoaded", () => {
  statusLed = document.querySelector("#status-led");
  historyList = document.querySelector("#history-list");
  themeBtn = document.querySelector("#theme-btn");
  pinBtn = document.querySelector("#pin-btn");
  clearBtn = document.querySelector("#clear-btn");
  sendFileBtn = document.querySelector("#send-file-btn");

  statusText = document.querySelector("#status-text");
  pcIpLabel = document.querySelector("#pc-ip-label");
  downloadsPathLabel = document.querySelector("#downloads-path-label");
  targetIpLabel = document.querySelector("#target-ip-label");
  authTokenLabel = document.querySelector("#auth-token-label");
  textShareBox = document.querySelector("#text-share-box");
  sendTextBtn = document.querySelector("#send-text-btn");
  dropZone = document.querySelector("#drop-zone");
  
  progressStatusLabel = document.querySelector("#progress-status-label");
  progressSpeedLabel = document.querySelector("#progress-speed-label");
  progressBar = document.querySelector("#progress-bar");

  pairingModal = document.querySelector("#pairing-modal");
  pairingIpLabel = document.querySelector("#pairing-ip-label");
  pairingApproveBtn = document.querySelector("#pairing-approve-btn");
  pairingRejectBtn = document.querySelector("#pairing-reject-btn");

  if (pairingApproveBtn) {
    pairingApproveBtn.addEventListener("click", () => {
      const ip = pairingIpLabel.textContent;
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ action: "approve_pairing", ip: ip }));
      }
      pairingModal.style.display = "none";
    });
  }

  if (pairingRejectBtn) {
    pairingRejectBtn.addEventListener("click", () => {
      const ip = pairingIpLabel.textContent;
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ action: "reject_pairing", ip: ip }));
      }
      pairingModal.style.display = "none";
    });
  }

  // 1. Sidebar Tab Switches
  const navItems = document.querySelectorAll(".nav-item");
  const views = document.querySelectorAll(".view");

  navItems.forEach(item => {
    item.addEventListener("click", () => {
      const targetTab = item.getAttribute("data-tab");
      navItems.forEach(ni => ni.classList.remove("active"));
      item.classList.add("active");

      views.forEach(v => {
        v.classList.remove("active-view");
        if (v.id === `view-${targetTab}`) {
          v.classList.add("active-view");
        }
      });
    });
  });

  // 2. Theme Switch handler — defaults to system preference, user override saved
  if (themeBtn) {
    const body = document.body;
    const savedTheme = localStorage.getItem("arc-theme");
    const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const startDark = savedTheme ? savedTheme === "dark" : systemDark;

    if (startDark) {
      body.classList.add("dark-theme");
      body.classList.remove("light-theme");
      themeBtn.textContent = "[ LIGHT ]";
    } else {
      body.classList.add("light-theme");
      body.classList.remove("dark-theme");
      themeBtn.textContent = "[ DARK ]";
    }

    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
      if (!localStorage.getItem("arc-theme")) {
        if (e.matches) {
          body.classList.add("dark-theme");
          body.classList.remove("light-theme");
          themeBtn.textContent = "[ LIGHT ]";
        } else {
          body.classList.add("light-theme");
          body.classList.remove("dark-theme");
          themeBtn.textContent = "[ DARK ]";
        }
      }
    });

    themeBtn.addEventListener("click", () => {
      if (body.classList.contains("dark-theme")) {
        body.classList.remove("dark-theme");
        body.classList.add("light-theme");
        themeBtn.textContent = "[ DARK ]";
        localStorage.setItem("arc-theme", "light");
      } else {
        body.classList.remove("light-theme");
        body.classList.add("dark-theme");
        themeBtn.textContent = "[ LIGHT ]";
        localStorage.setItem("arc-theme", "dark");
      }
    });
  }

  // 3. Always-on-top toggle handler via Tauri RPC
  if (pinBtn) {
    pinBtn.addEventListener("click", async () => {
      if (window.__TAURI__ && window.__TAURI__.core) {
        try {
          const isPinned = await window.__TAURI__.core.invoke("toggle_pin");
          if (isPinned) {
            pinBtn.textContent = "[ PINNED ]";
            pinBtn.style.color = "var(--accent-green)";
          } else {
            pinBtn.textContent = "[ PIN ]";
            pinBtn.style.color = "var(--text-secondary)";
          }
        } catch (err) {
          console.error("Tauri command error:", err);
        }
      } else {
        const isPinned = pinBtn.textContent === "[ PIN ]";
        pinBtn.textContent = isPinned ? "[ PINNED ]" : "[ PIN ]";
        pinBtn.style.color = isPinned ? "var(--accent-green)" : "var(--text-secondary)";
      }
    });
  }

  // 4. Clear database history handler
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        console.log("Sending clear history command...");
        socket.send(JSON.stringify({ action: "clear_history" }));
      }
    });
  }

  // 5. Send File to phone handler (Native Tauri dialog)
  if (sendFileBtn) {
    sendFileBtn.addEventListener("click", async () => {
      try {
        const selected = await window.__TAURI__.core.invoke("plugin:dialog|open", {
          multiple: false,
          title: "Select File to Send to Phone",
          defaultPath: window.__TAURI__ ? undefined : undefined
        });
        if (selected && socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ action: "send_file_path", payload: { file_path: selected } }));
        }
      } catch (e) {
        // Fallback to daemon tkinter dialog
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ action: "open_file_dialog" }));
        }
      }
    });
  }

  // 6. Send Quick Text handler
  if (sendTextBtn) {
    sendTextBtn.addEventListener("click", () => {
      const textVal = textShareBox.value;
      if (textVal && socket && socket.readyState === WebSocket.OPEN) {
        console.log("Syncing quick text to daemon...");
        socket.send(JSON.stringify({ action: "sync_text", text: textVal }));
        textShareBox.value = "";
      }
    });
  }

  // 7. Drag-and-drop native filesystem interceptor
  if (dropZone) {
    dropZone.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropZone.classList.add("dragover");
    });

    dropZone.addEventListener("dragleave", () => {
      dropZone.classList.remove("dragover");
    });

    dropZone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropZone.classList.remove("dragover");
    });

    // In Tauri, we listen for native OS drags to bypass browser security sandbox
    if (window.__TAURI__ && window.__TAURI__.event) {
      window.__TAURI__.event.listen("tauri://drag-drop", (event) => {
        const paths = event.payload.paths;
        if (paths && paths.length > 0 && socket && socket.readyState === WebSocket.OPEN) {
          const filePath = paths[0];
          console.log(`Native file drag-drop received: ${filePath}`);
          // Unified payload structure matching file-picker (fixes silent mismatch bug)
          socket.send(JSON.stringify({
            action: "send_file_path",
            payload: { file_path: filePath }
          }));
        }
      });
    }
  }

  connect();
});
