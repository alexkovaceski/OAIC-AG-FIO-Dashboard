(function () {
  "use strict";
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  var log = document.getElementById("chat-log");
  var input = document.getElementById("chat-in");
  var send = document.getElementById("chat-send");

  function addMsg(role, text) {
    var d = document.createElement("div");
    d.className = "msg " + role;
    d.textContent = text;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  }

  function renderEscalation(d) {
    var e = document.createElement("div");
    e.className = "escalate";
    e.innerHTML = 'For a custom FOI report, email <a href="mailto:contact@bluebirdadvisory.com.au">contact@bluebirdadvisory.com.au</a>.';
    d.appendChild(e);
  }

  async function ask(q) {
    var resp = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, history: [] }),
    });
    if (resp.redirected) { window.location = "/login"; throw new Error("redirect"); }
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    return resp.json();
  }

  function renderAnswer(a) {
    var d = document.createElement("div");
    d.className = "msg assistant";
    d.textContent = a.answer || "";
    var cites = a.citations || [];
    if (cites.length) {
      var c = document.createElement("div");
      c.className = "cite";
      c.textContent = "Sources: " + cites.join(" · ");
      d.appendChild(c);
    }
    log.appendChild(d);
    if (a.escalate) renderEscalation(d);
    log.scrollTop = log.scrollHeight;
  }

  async function submit() {
    var q = input.value.trim();
    if (!q) return;
    input.value = "";
    addMsg("user", q);
    var typing = document.createElement("div");
    typing.className = "msg assistant typing";
    typing.textContent = "Searching the corpus…";
    log.appendChild(typing);
    log.scrollTop = log.scrollHeight;
    try {
      var a = await ask(q);
      typing.remove();
      renderAnswer(a);
    } catch (e) {
      typing.remove();
      addMsg("assistant", "Sorry — the chat is temporarily unavailable. " + e.message);
    }
  }

  send.addEventListener("click", submit);
  input.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      submit();
    }
  });
})();
