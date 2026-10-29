(function () {
  "use strict";
  var root = document.getElementById("bulk-import");
  if (!root) return;
  var endpoint = root.dataset.endpoint;
  var csrf = root.querySelector("[name=csrfmiddlewaretoken]").value;
  var storeSelect = document.getElementById("bulk-store");
  var folderInput = document.getElementById("bulk-folder");
  var startButton = document.getElementById("bulk-start");
  var stopButton = document.getElementById("bulk-stop");
  var notice = document.getElementById("bulk-notice");
  var progress = document.getElementById("bulk-progress");
  var table = document.getElementById("bulk-table");
  var tbody = table.querySelector("tbody");
  var rows = [];
  var stopRequested = false;
  var running = false;

  // RFC 4180 parser: quoted fields may contain commas, quotes and newlines.
  function parseCsv(text) {
    var out = [], row = [], field = "", quoted = false;
    text = text.replace(/^﻿/, "");
    for (var i = 0; i < text.length; i++) {
      var c = text[i];
      if (quoted) {
        if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
        else if (c === '"') quoted = false;
        else field += c;
      } else if (c === '"') quoted = true;
      else if (c === ",") { row.push(field); field = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(field); field = "";
        if (row.length > 1 || row[0] !== "") out.push(row);
        row = [];
      } else field += c;
    }
    if (field !== "" || row.length) { row.push(field); out.push(row); }
    var header = out.shift() || [];
    return out.map(function (values) {
      var record = {};
      header.forEach(function (key, index) { record[key.trim()] = (values[index] || "").trim(); });
      return record;
    });
  }

  function cell(tr, content) {
    var td = document.createElement("td");
    if (content instanceof Node) td.appendChild(content); else td.textContent = content;
    tr.appendChild(td);
    return td;
  }

  function badge(text, tone) {
    var span = document.createElement("span");
    span.className = "badge me-1 text-bg-" + tone;
    span.textContent = text;
    return span;
  }

  function setResult(row, text, tone) {
    row.resultCell.textContent = "";
    row.resultCell.appendChild(badge(text, tone));
  }

  function updateStartButton() {
    startButton.disabled = running || !rows.length || !storeSelect.value;
  }

  folderInput.addEventListener("change", function () {
    var files = Array.prototype.slice.call(folderInput.files);
    var byPath = {};
    var manifest = null;
    files.forEach(function (file) {
      // Drop the chosen folder's own name so paths match the manifest.
      var path = (file.webkitRelativePath || file.name).split("/").slice(1).join("/");
      byPath[path.toLowerCase()] = file;
      if (path.toLowerCase() === "_manifest.csv") manifest = file;
    });
    rows = [];
    tbody.textContent = "";
    table.hidden = true;
    updateStartButton();
    if (!manifest) {
      notice.textContent = "No _manifest.csv found at the top of that folder.";
      return;
    }
    manifest.text().then(function (text) {
      var records = parseCsv(text);
      var nameCounts = {};
      records.forEach(function (r) {
        var key = (r.Description || "").toLowerCase();
        nameCounts[key] = (nameCounts[key] || 0) + 1;
      });
      var counts = { generic: 0, uncategorised: 0, duplicate: 0, missing: 0 };
      records.forEach(function (r) {
        var file = byPath[((r.Folder || "") + "/" + (r["Image file"] || "")).toLowerCase()] || null;
        var row = { record: r, file: file };
        var tr = document.createElement("tr");
        cell(tr, r["Sl.No"]);
        if (file) {
          var img = document.createElement("img");
          img.src = URL.createObjectURL(file);
          img.alt = "";
          img.loading = "lazy";
          img.width = 48;
          img.height = 48;
          img.style.objectFit = "contain";
          cell(tr, img);
        } else cell(tr, "—");
        cell(tr, r.Description);
        cell(tr, r.Item || "Uncategorised");
        var flags = cell(tr, "");
        if (!file) { flags.appendChild(badge("Missing image", "danger")); counts.missing++; }
        if (/^GENERIC/i.test(r.Status || "")) { flags.appendChild(badge("Generic photo", "warning")); counts.generic++; }
        if (!r.Item) { flags.appendChild(badge("No category", "secondary")); counts.uncategorised++; }
        if (nameCounts[(r.Description || "").toLowerCase()] > 1) { flags.appendChild(badge("Duplicate name", "info")); counts.duplicate++; }
        row.resultCell = cell(tr, "");
        tbody.appendChild(tr);
        rows.push(row);
      });
      table.hidden = false;
      notice.textContent = records.length + " products found · " + counts.generic + " generic photos · " +
        counts.uncategorised + " without a category · " + counts.duplicate + " sharing a name · " +
        counts.missing + " missing images.";
      updateStartButton();
    });
  });

  storeSelect.addEventListener("change", updateStartButton);
  stopButton.addEventListener("click", function () {
    stopRequested = true;
    stopButton.disabled = true;
    notice.textContent = "Stopping after the current row…";
  });

  function importRow(row) {
    var body = new FormData();
    body.append("store", storeSelect.value);
    body.append("sl_no", row.record["Sl.No"]);
    body.append("name", row.record.Description);
    body.append("category", row.record.Item || "");
    body.append("image", row.file, row.file.name);
    return fetch(endpoint, {
      method: "POST",
      body: body,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf },
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) {
          var error = data.error;
          if (error && typeof error === "object" && !Array.isArray(error)) error = Object.values(error).flat();
          throw new Error([].concat(error || ("HTTP " + response.status)).join(" "));
        }
        return data;
      });
    });
  }

  startButton.addEventListener("click", function () {
    if (running) return;
    running = true;
    stopRequested = false;
    storeSelect.disabled = true;
    folderInput.disabled = true;
    stopButton.hidden = false;
    stopButton.disabled = false;
    progress.hidden = false;
    progress.max = rows.length;
    progress.value = 0;
    updateStartButton();
    var tally = { created: 0, exists: 0, duplicate: 0, failed: 0 };
    var index = 0;

    function finish() {
      running = false;
      storeSelect.disabled = false;
      folderInput.disabled = false;
      stopButton.hidden = true;
      updateStartButton();
      notice.textContent = (stopRequested ? "Stopped. " : "Finished. ") + tally.created + " created · " +
        tally.exists + " already imported · " + tally.duplicate + " duplicates skipped · " +
        tally.failed + " failed.";
    }

    function next() {
      if (stopRequested || index >= rows.length) return finish();
      var row = rows[index++];
      progress.value = index;
      notice.textContent = "Importing " + index + " of " + rows.length + "…";
      if (!row.file) {
        tally.failed++;
        setResult(row, "No image", "danger");
        return next();
      }
      setResult(row, "Working…", "light");
      importRow(row).then(function (data) {
        if (data.state === "created") {
          tally.created++;
          setResult(row, "Created " + data.sku + " · " + data.unit, "success");
        } else if (data.state === "exists") {
          tally.exists++;
          setResult(row, "Already imported", "secondary");
        } else {
          tally.duplicate++;
          setResult(row, "Duplicate of " + data.sku, "info");
        }
      }, function (error) {
        tally.failed++;
        setResult(row, error.message, "danger");
      }).then(next);
    }
    next();
  });
})();
