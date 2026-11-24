function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

let currentDir = (window.AndroidBridge && AndroidBridge.getRootPath) ? AndroidBridge.getRootPath() : "/storage/emulated/0";
let currentEntries = [];
let selectedPaths = new Set();
let recursiveSubfolders = true;
let screen = "explorer";
let returnAfterEdit = "explorer";

let detectedTypes = [];
let approvedPatterns = new Set();
let scannedItems = [];
let checkedItems = new Set();
let manualDates = {};
let editingPath = "";
let lastUndoPath = "";

function showBanner(msg) {
  const b = document.getElementById("banner");
  b.textContent = msg;
  b.style.display = msg ? "block" : "none";
}

function setScreen(name, title, sub) {
  screen = name;
  ["screenExplorer", "screenTypes", "screenPreview", "screenBundle", "screenEdit", "screenResults"].forEach(id => {
    document.getElementById(id).classList.remove("active");
  });
  const map = {
    explorer: "screenExplorer",
    types: "screenTypes",
    preview: "screenPreview",
    bundle: "screenBundle",
    edit: "screenEdit",
    results: "screenResults"
  };
  document.getElementById(map[name]).classList.add("active");
  document.getElementById("btnSelectAll").style.display = name === "explorer" ? "inline-block" : "none";
  document.getElementById("btnSubfolders").style.display = name === "explorer" ? "inline-block" : "none";
  if (title !== undefined) document.getElementById("topTitle").textContent = title;
  if (sub !== undefined) document.getElementById("topSub").textContent = sub;
}

function loadDir(dirPath) {
  if (!window.AndroidBridge) return;
  const raw = AndroidBridge.listDirectory(dirPath);
  const data = JSON.parse(raw);
  if (data.error) { showBanner(data.error); return; }
  currentDir = data.path;
  currentEntries = data.entries;
  const parts = currentDir.split("/").filter(Boolean);
  setScreen("explorer", parts[parts.length - 1] || "/", currentDir);
  renderExplorer();
}

function renderExplorer() {
  const list = document.getElementById("explorerList");
  list.innerHTML = "";
  if (currentDir !== "/") {
    const up = document.createElement("div");
    up.className = "row";
    up.innerHTML = `<span class="icon icon-up">↑</span><div class="meta"><div class="name">..</div></div>`;
    up.onclick = () => {
      const parent = currentDir.substring(0, currentDir.lastIndexOf("/")) || "/";
      selectedPaths.clear();
      loadDir(parent);
    };
    list.appendChild(up);
  }
  currentEntries.forEach(e => {
    const row = document.createElement("div");
    const sel = selectedPaths.has(e.path);
    row.className = "row" + (sel ? " selected" : "");
    const iconCls = e.is_dir ? "icon-dir" : (e.media_type === "VID" ? "icon-vid" : (e.media_type === "IMG" ? "icon-img" : "icon-file"));
    const sub = e.is_dir ? (e.item_count >= 0 ? `${e.item_count} items` : "<DIR>") : `${Math.round(e.size_bytes / 1024)} KB`;

    row.innerHTML = `
      <span class="icon ${iconCls}">${e.media_type}</span>
      <div class="meta">
        <div class="name"></div>
        <div class="subrow"><span>${sub}</span><span>${e.mtime_str}</span></div>
      </div>
      <input type="checkbox" ${sel ? "checked" : ""}>
    `;
    row.querySelector(".name").textContent = e.name;
    const cb = row.querySelector("input");
    cb.onclick = ev => {
      ev.stopPropagation();
      if (cb.checked) selectedPaths.add(e.path); else selectedPaths.delete(e.path);
      row.classList.toggle("selected", cb.checked);
      updateModifyBtn();
    };
    row.onclick = () => {
      if (e.is_dir) {
        selectedPaths.clear();
        loadDir(e.path);
      } else {
        openEditor(e.path, "explorer");
      }
    };
    list.appendChild(row);
  });
  updateModifyBtn();
}

function updateModifyBtn() {
  const btn = document.getElementById("btnModifySelected");
  const b2 = document.getElementById("btnBundleDate");
  if (selectedPaths.size > 0 && screen === "explorer") {
    btn.style.display = "block";
    btn.textContent = `Auto-Fix (${selectedPaths.size})`;
    b2.style.display = "block";
    b2.textContent = `Set Date (${selectedPaths.size})`;
  } else {
    btn.style.display = "none";
    b2.style.display = "none";
  }
}

document.getElementById("btnSelectAll").onclick = () => {
  if (selectedPaths.size === currentEntries.length && currentEntries.length > 0) {
    selectedPaths.clear();
  } else {
    currentEntries.forEach(e => selectedPaths.add(e.path));
  }
  renderExplorer();
};

document.getElementById("btnSubfolders").onclick = () => {
  recursiveSubfolders = !recursiveSubfolders;
  document.getElementById("btnSubfolders").textContent = `Sub: ${recursiveSubfolders ? "ON" : "OFF"}`;
};

document.getElementById("btnModifySelected").onclick = () => {
  const customRx = document.getElementById("txtCustomRegex").value || "";
  const allowShort = document.getElementById("chkShortYear").checked;
  const raw = AndroidBridge.scanSelection(JSON.stringify(Array.from(selectedPaths)), recursiveSubfolders, customRx, allowShort);
  const res = JSON.parse(raw);
  detectedTypes = res.types;
  scannedItems = res.items;
  approvedPatterns = new Set(detectedTypes.filter(t => t.matched).map(t => t.pattern));

  document.getElementById("typesSummary").textContent = `Found ${res.total} media files. Allow which detected types to modify:`;
  const tl = document.getElementById("typesList");
  tl.innerHTML = "";
  detectedTypes.forEach(t => {
    const c = document.createElement("div");
    c.className = "card";
    const futWarn = t.has_future ? ` · <span class="warn">Contains future date (&gt; now)</span>` : "";
    const note = !t.matched ? `<span class="warn">Unmatched — asks user before changing</span>` :
      ((t.has_time ? `Full date &amp; time` : `<span class="ok">Date only — keeps existing HH:MM:SS</span>`) + futWarn);
    c.innerHTML = `
      <div style="display:flex; gap:10px; align-items:center;">
        <input type="checkbox" ${approvedPatterns.has(t.pattern) ? "checked" : ""}>
        <div>
          <div style="font-weight:700;">${esc(t.pattern)} (${t.count})</div>
          <div style="font-size:12px; color:var(--sub);">e.g. ${esc(t.sample)} · ${note}</div>
        </div>
      </div>
    `;
    const cb = c.querySelector("input");
    cb.onchange = () => { if (cb.checked) approvedPatterns.add(t.pattern); else approvedPatterns.delete(t.pattern); };
    tl.appendChild(c);
  });
  setScreen("types", "Permission to Modify Types", "Step 1 of 2");
};

document.getElementById("btnApproveTypes").onclick = () => {
  checkedItems = new Set(scannedItems.filter(i => approvedPatterns.has(i.pattern) && i.matched && !i.is_future).map(i => i.path));
  renderPreview();
  setScreen("preview", "Dry-Run Preview", "Tap any file to edit details");
};

function renderPreview() {
  const pl = document.getElementById("previewList");
  pl.innerHTML = "";
  const visible = scannedItems.filter(i => approvedPatterns.has(i.pattern) || !i.matched);
  visible.forEach(i => {
    const eff = manualDates[i.path] || i.new_dt;
    const ok = eff.length > 0;
    const chk = checkedItems.has(i.path) && ok;
    const c = document.createElement("div");
    c.className = "card";
    c.innerHTML = `
      <div style="display:flex; gap:10px; align-items:center;">
        <input type="checkbox" ${chk ? "checked" : ""} ${ok ? "" : "disabled"}>
        <div style="flex:1; min-width:0;">
          <div class="name"></div>
          <div style="font-size:12px;" class="${(!ok || i.is_future) ? "warn" : "ok"}">
            ${!ok ? "No date matched — Tap to set date or skip" : (i.is_future ? `${i.current_dt} → ${eff} (WARNING: Future date > now — check to confirm)` : `${i.current_dt} → ${eff}`)}
          </div>
        </div>
      </div>
    `;
    c.querySelector(".name").textContent = i.name;
    const cb = c.querySelector("input");
    cb.onclick = ev => {
      ev.stopPropagation();
      if (cb.checked) checkedItems.add(i.path); else checkedItems.delete(i.path);
    };
    c.onclick = () => openEditor(i.path, "preview", eff);
    pl.appendChild(c);
  });
}

document.getElementById("btnApply").onclick = () => {
  const payload = scannedItems
    .filter(i => checkedItems.has(i.path))
    .map(i => ({ path: i.path, new_dt: manualDates[i.path] || i.new_dt }))
    .filter(x => x.new_dt);
  if (payload.length === 0) return;

  const res = JSON.parse(AndroidBridge.applyUpdates(JSON.stringify(payload), currentDir));
  AndroidBridge.refreshMediaStore(JSON.stringify(payload.map(x => x.path)));
  lastUndoPath = res.undo_path;
  document.getElementById("resSummary").textContent = `Updated ${res.updated} of ${res.total} file(s) offline.`;
  document.getElementById("resLogs").innerHTML = res.results.map(r => `<div>${esc(r.name)}: ${esc(r.detail)}</div>`).join("");
  document.getElementById("btnUndo").style.display = lastUndoPath ? "block" : "none";
  setScreen("results", "Update Complete", "Filesystem + EXIF/MP4 updated");
};

function openEditor(filePath, retScreen, overrideDt) {
  const d = JSON.parse(AndroidBridge.getFileDetails(filePath));
  if (d.error) { showBanner(d.error); return; }
  editingPath = d.path;
  returnAfterEdit = retScreen;
  document.getElementById("edName").value = d.name;
  document.getElementById("edDateTime").value = overrideDt || d.date_time;
  document.getElementById("edDesc").value = d.description || "";
  document.getElementById("edArtist").value = d.artist || "";
  document.getElementById("edMake").value = d.make || "";
  document.getElementById("edModel").value = d.model || "";
  document.getElementById("edLat").value = d.gps_lat || "";
  document.getElementById("edLon").value = d.gps_lon || "";
  document.getElementById("edComment").value = d.user_comment || "";
  document.getElementById("jpegFields").style.display = d.is_jpeg ? "flex" : "none";
  document.getElementById("edError").textContent = "";
  setScreen("edit", "Edit All File Details", d.name);
}

document.getElementById("btnSaveDetails").onclick = () => {
  const payload = {
    path: editingPath,
    name: document.getElementById("edName").value.trim(),
    date_time: document.getElementById("edDateTime").value.trim(),
    description: document.getElementById("edDesc").value,
    artist: document.getElementById("edArtist").value,
    make: document.getElementById("edMake").value,
    model: document.getElementById("edModel").value,
    gps_lat: document.getElementById("edLat").value,
    gps_lon: document.getElementById("edLon").value,
    user_comment: document.getElementById("edComment").value
  };
  const res = JSON.parse(AndroidBridge.saveFileDetails(JSON.stringify(payload)));
  if (!res.ok) { document.getElementById("edError").textContent = res.error; return; }
  const newPath = res.path || editingPath;
  scannedItems.forEach(it => {
    if (it.path === editingPath) {
      it.path = newPath;
      it.name = res.name || payload.name;
    }
  });
  checkedItems.delete(editingPath);
  checkedItems.add(newPath);
  manualDates[newPath] = payload.date_time;
  AndroidBridge.refreshMediaStore(JSON.stringify([res.path]));
  showBanner(`Saved details for ${res.name}`);
  if (returnAfterEdit === "preview") {
    renderPreview();
    setScreen("preview", "Dry-Run Preview", "Tap any file to edit details");
  } else {
    loadDir(currentDir);
  }
};

document.getElementById("btnUndo").onclick = () => {
  const res = JSON.parse(AndroidBridge.undoLastRun(lastUndoPath));
  showBanner(`Undo complete: restored ${res.restored} file(s).`);
  selectedPaths.clear();
  loadDir(currentDir);
};

document.getElementById("btnDone").onclick = () => {
  selectedPaths.clear();
  loadDir(currentDir);
};

document.getElementById("btnBack").onclick = () => window.handleAndroidBack();

window.handleAndroidBack = () => {
  if (screen === "edit") {
    if (returnAfterEdit === "preview") {
      setScreen("preview", "Dry-Run Preview", "Tap any file to edit details");
    } else {
      loadDir(currentDir);
    }
    return true;
  }
  if (screen === "preview") { setScreen("types", "Permission to Modify Types", "Step 1 of 2"); return true; }
  if (screen === "types" || screen === "results" || screen === "bundle") { loadDir(currentDir); return true; }
  if (screen === "explorer" && currentDir !== "/") {
    const parent = currentDir.substring(0, currentDir.lastIndexOf("/")) || "/";
    selectedPaths.clear();
    loadDir(parent);
    return true;
  }
  return false;
};

window.onStorageReady = () => {
  if (screen === "explorer" && currentEntries.length === 0) loadDir(currentDir);
};

if (window.AndroidBridge && AndroidBridge.hasPermission()) {
  loadDir(currentDir);
}

document.getElementById("btnBundleDate").onclick = () => {
  const selEntries = currentEntries.filter(e => selectedPaths.has(e.path));
  const folderCount = selEntries.filter(e => e.is_dir).length;
  const fileCount = selEntries.length - folderCount;
  document.getElementById("bundleSummary").textContent = `Overwrite date & time on ${selectedPaths.size} selected item(s):`;
  const warnBox = document.getElementById("bundleFolderWarnBox");
  const chkFolder = document.getElementById("chkConfirmFolderDate");
  chkFolder.checked = false;
  if (folderCount > 0) {
    warnBox.style.display = "block";
    document.getElementById("bundleFolderWarnText").textContent = fileCount > 0
      ? `Warning: Your selection includes ${folderCount} folder(s) along with ${fileCount} file(s)/media. Changing a folder's date updates the folder itself.`
      : `Warning: Your selection includes ${folderCount} folder(s). Confirm before changing folder date/time.`;
  } else {
    warnBox.style.display = "none";
  }
  const now = new Date();
  const pad = n => String(n).padStart(2, "0");
  document.getElementById("bundleDateInput").value = `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  document.getElementById("bundleError").textContent = "";
  setScreen("bundle", "Set Date & Time (Bundle)", "Files & folders");
};

document.getElementById("btnApplyBundle").onclick = () => {
  const warnVisible = document.getElementById("bundleFolderWarnBox").style.display !== "none";
  if (warnVisible && !document.getElementById("chkConfirmFolderDate").checked) {
    document.getElementById("bundleError").textContent = "Please check the folder confirmation box above before applying.";
    return;
  }
  const dtStr = document.getElementById("bundleDateInput").value.trim();
  const res = JSON.parse(AndroidBridge.applyBundleDate(JSON.stringify(Array.from(selectedPaths)), dtStr, currentDir));
  if (!res.ok) { document.getElementById("bundleError").textContent = res.error; return; }
  if (res.media_paths && res.media_paths.length > 0) {
    AndroidBridge.refreshMediaStore(JSON.stringify(res.media_paths));
  }
  lastUndoPath = res.undo_path;
  document.getElementById("resSummary").textContent = `Updated ${res.updated} of ${res.total} item(s) offline.`;
  document.getElementById("resLogs").innerHTML = res.results.map(r => `<div>${esc(r.name)}: ${esc(r.detail)}</div>`).join("");
  document.getElementById("btnUndo").style.display = lastUndoPath ? "block" : "none";
  setScreen("results", "Bundle Update Complete", "Files & folders updated");
};
