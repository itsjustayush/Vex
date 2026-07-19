(() => {
  "use strict";
  const HEALTH_POLL_MS = 15_000;
  const demoUserId = "status-page-" + Math.random().toString(36).slice(2, 10);

  const dot = document.getElementById("status-dot"), badge = document.getElementById("status-badge");
  const uptimeValue = document.getElementById("uptime-value"), statStatus = document.getElementById("stat-status");
  const statModel = document.getElementById("stat-model"), statConversations = document.getElementById("stat-conversations");
  const transcript = document.getElementById("transcript"), chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input"), sendBtn = document.getElementById("send-btn");
  let baseUptimeSeconds = 0, baseUptimeAt = Date.now();

  function humanizeSeconds(s) {
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
    const parts = [];
    if (d) parts.push(`${d}d`); if (h) parts.push(`${h}h`); if (m) parts.push(`${m}m`); parts.push(`${sec}s`);
    return parts.join(" ");
  }

  function appendLine(who, text, cls) {
    const empty = transcript.querySelector(".empty");
    if (empty) empty.remove();
    const line = document.createElement("div"); line.className = `line ${cls}`;
    const whoSpan = document.createElement("span"); whoSpan.className = "who"; whoSpan.textContent = who + " ";
    const textSpan = document.createElement("span"); textSpan.className = "text"; textSpan.textContent = text;
    line.appendChild(whoSpan); line.appendChild(textSpan);
    transcript.appendChild(line); transcript.scrollTop = transcript.scrollHeight;
  }

  async function pollHealth() {
    try {
      const res = await fetch("/api/health", { cache: "no-store" });
      const data = await res.json();
      const status = data.status || "offline";
      badge.textContent = status.toUpperCase();
      statStatus.textContent = status;
      statModel.textContent = data.model || "n/a";
      statConversations.textContent = String(data.active_conversations ?? "0");
      baseUptimeSeconds = data.uptime_seconds || 0;
      baseUptimeAt = Date.now();
    } catch (err) {
      badge.textContent = "UNREACHABLE";
      statStatus.textContent = "unreachable";
    }
  }

  setInterval(() => {
    uptimeValue.textContent = humanizeSeconds(baseUptimeSeconds + (Date.now() - baseUptimeAt) / 1000);
  }, 1000);

  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const message = chatInput.value.trim();
    if (!message) return;
    appendLine("you", message, "user");
    chatInput.value = "";
    try {
      const res = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, user_id: demoUserId }) });
      const data = await res.json();
      if (!res.ok) appendLine("error", data.detail || "Failed.", "err");
      else appendLine("bot", data.response, "bot");
    } catch (err) { appendLine("error", "Network error.", "err"); }
  });

  pollHealth();
  setInterval(pollHealth, HEALTH_POLL_MS);
})();