(function () {
  "use strict";
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function inline(s) {
    // escape first, then the two markdown spans the model actually emits
    return esc(s)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");
  }

  function mdToHtml(text) {
    // Minimal markdown: escape, then bold/italic, bullets and paragraphs.
    // Everything is escaped before any tag is added, so model output cannot
    // inject markup.
    var lines = String(text || "").split("\n");
    var out = [], inList = false;
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (/^\s*[-*]\s+/.test(line)) {
        if (!inList) { out.push("<ul>"); inList = true; }
        out.push("<li>" + inline(line.replace(/^\s*[-*]\s+/, "")) + "</li>");
      } else {
        if (inList) { out.push("</ul>"); inList = false; }
        if (line.trim()) out.push("<p>" + inline(line) + "</p>");
      }
    }
    if (inList) out.push("</ul>");
    return out.join("");
  }

  function citeHref(path) {
    if (path.indexOf("catalog:") === 0) {
      return "/provenance.html?key=" + encodeURIComponent(path.slice(8));
    }
    if (path.indexOf("data/corpus/data-notes.md") === 0) {
      return "/data-notes.html";
    }
    return null;
  }

  var log = document.getElementById("chat-log");
  var input = document.getElementById("chat-in");
  var send = document.getElementById("chat-send");

  function addMsg(role, text, asHtml) {
    var d = document.createElement("div");
    d.className = "msg " + role;
    if (asHtml) { d.innerHTML = text; } else { d.textContent = text; }
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
    d.innerHTML = mdToHtml(a.answer || "");
    var cites = a.citations || [];
    if (cites.length) {
      var c = document.createElement("div");
      c.className = "cite";
      c.innerHTML = "Sources: " + cites.map(function (p) {
        var href = citeHref(p);
        return href ? '<a href="' + href + '">' + esc(p) + '</a>' : esc(p);
      }).join(" &middot; ");
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
