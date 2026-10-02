"use strict";
// Sample-only interactions. No server requests or real server actions.
const byId = (id) => document.getElementById(id);
let running = true;
byId("theme").addEventListener("change", (event) => {
  if (event.target.value === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = event.target.value;
});
function log(message, status = "") {
  const line = document.createElement("div");
  line.className = "cc-log-line";
  const time = document.createElement("time");
  time.className = "cc-log-timestamp";
  time.textContent = `[${new Date().toLocaleTimeString("en-GB", { hour12:false })}] `;
  const text = document.createElement("span");
  text.className = status;
  text.textContent = message;
  line.append(time, text);
  const consoleBox = byId("console");
  consoleBox.append(line);
  while (consoleBox.childElementCount > 200) consoleBox.firstElementChild.remove();
  consoleBox.scrollTop = consoleBox.scrollHeight;
}
function setRunning(value) {
  running = value;
  byId("server-state").textContent = value ? "Online" : "Stopped";
  byId("server-state").className = value ? "cc-chip cc-chip-nominal" : "cc-chip";
  byId("start").disabled = value;
  byId("restart").disabled = !value;
  byId("stop").disabled = !value;
  byId("command").disabled = !value;
  byId("command-form").querySelector("button").disabled = !value;
  byId("cpu").textContent = value ? "24%" : "—";
  byId("ram").textContent = value ? "3.2 GB" : "—";
  byId("players").textContent = value ? "3 / 20" : "0 / 20";
  byId("connected-players").hidden = !value;
  byId("player-note").textContent = value ? "3 players online" : "Nobody online right now.";
}
byId("start").addEventListener("click", () => { setRunning(true); log("Preview: server started.", "cc-log-success"); });
byId("stop").addEventListener("click", () => { setRunning(false); log("Preview: server stopped.", "cc-log-warning"); });
byId("restart").addEventListener("click", () => { log("Preview: restarting server…", "cc-log-warning"); log("Preview: server ready.", "cc-log-success"); });
byId("clear").addEventListener("click", () => byId("console").replaceChildren());
byId("command-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const command = byId("command").value.trim();
  if (!running || !command) return;
  log(`> ${command}`);
  if (command === "help") log("Preview commands: help, list, say <message>");
  else if (command === "list") log("3 of 20 players online: Alex, Sam, Robin");
  else if (command.startsWith("say ")) log(`[Server] ${command.slice(4)}`);
  else log("Preview only: command was not sent to a server.", "cc-log-warning");
  byId("command").value = "";
});
