"""
APK Analyzer Web App
Upload APK files and inspect their contents: manifest, permissions,
activities, layouts, resources, images, and file structure.
"""

import io
import os
import logging
import tempfile
import zipfile
from collections import defaultdict

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="APK Analyzer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 MB


def _analyze_apk(apk_path: str) -> dict:
    """Analyze an APK file and return structured information."""
    from androguard.core.apk import APK

    a = APK(apk_path)

    # Basic info
    info = {
        "package": a.get_package() or "N/A",
        "app_name": a.get_app_name() or "N/A",
        "version_name": a.get_androidversion_name() or "N/A",
        "version_code": a.get_androidversion_code() or "N/A",
        "min_sdk": a.get_min_sdk_version() or "N/A",
        "target_sdk": a.get_target_sdk_version() or "N/A",
        "max_sdk": a.get_max_sdk_version() or "N/A",
    }

    # Permissions
    permissions = a.get_permissions()

    # Components
    activities = a.get_activities()
    main_activity = a.get_main_activity() or "N/A"
    services = a.get_services()
    receivers = a.get_receivers()
    providers = a.get_providers()

    # Icon path
    icon_path = a.get_app_icon() or ""

    # File listing from ZIP
    file_tree = defaultdict(list)
    images = []
    layouts = []
    xml_files = []

    with zipfile.ZipFile(apk_path, "r") as z:
        for entry in z.infolist():
            name = entry.filename
            parts = name.split("/")
            folder = parts[0] if len(parts) > 1 else "(root)"
            file_tree[folder].append({
                "name": name,
                "size": entry.file_size,
                "compressed": entry.compress_size,
            })

            lower = name.lower()
            if lower.startswith("res/layout") and lower.endswith(".xml"):
                layouts.append(name)
            elif lower.endswith(".xml") and not lower.startswith("meta-inf"):
                xml_files.append(name)

            if any(lower.endswith(ext) for ext in
                   (".png", ".jpg", ".jpeg", ".webp", ".gif")):
                images.append({
                    "path": name,
                    "size": entry.file_size,
                })

        apk_size = os.path.getsize(apk_path)

        # Try to read icon
        icon_data = None
        if icon_path and not icon_path.endswith(".xml"):
            try:
                raw = z.read(icon_path)
                import base64
                icon_data = base64.b64encode(raw).decode()
            except Exception:
                pass

        # Try adaptive icon fallback
        if not icon_data:
            for candidate in z.namelist():
                if ("mipmap" in candidate and "ic_launcher" in candidate
                        and candidate.endswith(".png")):
                    try:
                        raw = z.read(candidate)
                        import base64
                        icon_data = base64.b64encode(raw).decode()
                        break
                    except Exception:
                        continue

    # Decode layout XML files using androguard
    decoded_layouts = []
    for layout_path in layouts[:50]:
        try:
            raw_xml = a.get_file(layout_path)
            if raw_xml:
                from androguard.core.axml import AXMLPrinter
                axp = AXMLPrinter(raw_xml)
                decoded_xml = axp.get_xml().decode("utf-8", errors="replace")
                decoded_layouts.append({
                    "path": layout_path,
                    "xml": decoded_xml,
                })
        except Exception as e:
            decoded_layouts.append({
                "path": layout_path,
                "xml": f"<!-- Error decoding: {e} -->",
            })

    # Build folder summary
    folder_summary = {}
    for folder, files in sorted(file_tree.items()):
        total_size = sum(f["size"] for f in files)
        folder_summary[folder] = {
            "count": len(files),
            "total_size": total_size,
        }

    return {
        "info": info,
        "permissions": permissions,
        "activities": activities,
        "main_activity": main_activity,
        "services": services,
        "receivers": receivers,
        "providers": providers,
        "icon_data": icon_data,
        "icon_path": icon_path,
        "layouts": decoded_layouts,
        "layout_count": len(layouts),
        "images": images[:200],
        "image_count": len(images),
        "xml_files": xml_files[:100],
        "folder_summary": folder_summary,
        "apk_size": apk_size,
    }


@app.get("/", response_class=HTMLResponse)
async def index():
    return get_html()


@app.post("/analyze")
async def analyze_apk(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".apk"):
        return JSONResponse(
            status_code=400,
            content={"error": "Please upload a valid .apk file"},
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        return JSONResponse(
            status_code=400,
            content={"error": f"File too large. Max size: {MAX_FILE_SIZE // (1024*1024)} MB"},
        )

    with tempfile.NamedTemporaryFile(suffix=".apk", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = _analyze_apk(tmp_path)
        return JSONResponse(content=result)
    except Exception as e:
        logger.exception("Error analyzing APK")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to analyze APK: {str(e)}"},
        )
    finally:
        os.unlink(tmp_path)


@app.get("/extract-image")
async def extract_image(apk_path: str = "", image_path: str = ""):
    return JSONResponse(
        status_code=400,
        content={"error": "Direct image extraction not supported in upload mode"},
    )


def get_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APK Analyzer</title>
<style>
:root {
  --bg: #0f172a;
  --surface: #1e293b;
  --surface2: #334155;
  --border: #475569;
  --text: #f1f5f9;
  --text2: #94a3b8;
  --accent: #3b82f6;
  --accent2: #60a5fa;
  --green: #22c55e;
  --red: #ef4444;
  --orange: #f59e0b;
  --purple: #a855f7;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
}
.container { max-width: 1200px; margin: 0 auto; padding: 20px; }

/* Header */
header {
  text-align: center;
  padding: 40px 20px;
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  border-bottom: 1px solid var(--border);
}
header h1 { font-size: 2.5em; margin-bottom: 10px; }
header h1 span { color: var(--accent2); }
header p { color: var(--text2); font-size: 1.1em; }

/* Upload Area */
.upload-area {
  border: 2px dashed var(--border);
  border-radius: 16px;
  padding: 60px 40px;
  text-align: center;
  margin: 30px 0;
  transition: all 0.3s;
  cursor: pointer;
  background: var(--surface);
}
.upload-area:hover, .upload-area.drag-over {
  border-color: var(--accent);
  background: rgba(59, 130, 246, 0.05);
}
.upload-area svg { width: 64px; height: 64px; margin-bottom: 16px; color: var(--accent); }
.upload-area h3 { font-size: 1.3em; margin-bottom: 8px; }
.upload-area p { color: var(--text2); }
.upload-area input { display: none; }
.upload-btn {
  display: inline-block;
  margin-top: 16px;
  padding: 12px 32px;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 1em;
  cursor: pointer;
  transition: background 0.2s;
}
.upload-btn:hover { background: #2563eb; }

/* Progress */
.progress-container {
  display: none;
  margin: 20px 0;
  padding: 20px;
  background: var(--surface);
  border-radius: 12px;
}
.progress-bar {
  height: 8px;
  background: var(--surface2);
  border-radius: 4px;
  overflow: hidden;
  margin-top: 10px;
}
.progress-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 4px;
  transition: width 0.3s;
  width: 0%;
}
.progress-text { color: var(--text2); font-size: 0.9em; }

/* Results */
#results { display: none; }

/* App Header Card */
.app-header-card {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 24px;
  background: var(--surface);
  border-radius: 16px;
  margin-bottom: 24px;
  border: 1px solid var(--border);
}
.app-icon {
  width: 80px;
  height: 80px;
  border-radius: 16px;
  background: var(--surface2);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  flex-shrink: 0;
}
.app-icon img { width: 100%; height: 100%; object-fit: cover; }
.app-icon svg { width: 40px; height: 40px; color: var(--text2); }
.app-details h2 { font-size: 1.5em; margin-bottom: 4px; }
.app-details .package { color: var(--accent2); font-size: 0.95em; }
.app-details .meta { color: var(--text2); margin-top: 8px; font-size: 0.9em; }
.app-details .meta span { margin-right: 16px; }

/* Tabs */
.tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 20px;
  flex-wrap: wrap;
  background: var(--surface);
  padding: 4px;
  border-radius: 12px;
}
.tab {
  padding: 10px 20px;
  border: none;
  background: transparent;
  color: var(--text2);
  cursor: pointer;
  border-radius: 8px;
  font-size: 0.9em;
  transition: all 0.2s;
  white-space: nowrap;
}
.tab:hover { color: var(--text); background: var(--surface2); }
.tab.active { background: var(--accent); color: white; }
.tab-content { display: none; }
.tab-content.active { display: block; }

/* Cards */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 16px;
}
.card h3 {
  font-size: 1.1em;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.card h3 .badge {
  background: var(--accent);
  color: white;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 0.75em;
}

/* Info Grid */
.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}
.info-item {
  padding: 12px;
  background: var(--surface2);
  border-radius: 8px;
}
.info-item .label { color: var(--text2); font-size: 0.8em; text-transform: uppercase; letter-spacing: 0.5px; }
.info-item .value { font-size: 1.1em; margin-top: 4px; word-break: break-all; }

/* Permission list */
.perm-list { list-style: none; }
.perm-list li {
  padding: 8px 12px;
  background: var(--surface2);
  margin-bottom: 4px;
  border-radius: 6px;
  font-size: 0.9em;
  display: flex;
  align-items: center;
  gap: 8px;
}
.perm-list li .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.perm-dangerous { background: var(--red); }
.perm-normal { background: var(--green); }

/* Component list */
.comp-list { list-style: none; }
.comp-list li {
  padding: 8px 12px;
  background: var(--surface2);
  margin-bottom: 4px;
  border-radius: 6px;
  font-size: 0.85em;
  font-family: 'Fira Code', monospace;
  word-break: break-all;
}
.comp-list li.main { border-left: 3px solid var(--green); }

/* Layout XML */
.layout-item { margin-bottom: 16px; }
.layout-item .layout-path {
  padding: 8px 12px;
  background: var(--surface2);
  border-radius: 8px 8px 0 0;
  font-size: 0.85em;
  color: var(--accent2);
  font-family: monospace;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.layout-item .layout-path:hover { background: var(--border); }
.layout-xml {
  display: none;
  background: #0d1117;
  padding: 16px;
  border-radius: 0 0 8px 8px;
  overflow-x: auto;
  font-size: 0.8em;
  line-height: 1.6;
  max-height: 500px;
  overflow-y: auto;
}
.layout-xml.open { display: block; }
.layout-xml pre {
  font-family: 'Fira Code', 'Courier New', monospace;
  white-space: pre-wrap;
  word-break: break-all;
  color: #c9d1d9;
}

/* Images grid */
.images-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}
.image-item {
  background: var(--surface2);
  border-radius: 8px;
  padding: 8px;
  text-align: center;
}
.image-item .path {
  font-size: 0.7em;
  color: var(--text2);
  margin-top: 6px;
  word-break: break-all;
}
.image-item .size-label {
  font-size: 0.7em;
  color: var(--accent2);
}

/* File tree */
.folder-item {
  margin-bottom: 8px;
}
.folder-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: var(--surface2);
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}
.folder-header:hover { background: var(--border); }
.folder-name { font-weight: 600; display: flex; align-items: center; gap: 8px; }
.folder-meta { color: var(--text2); font-size: 0.85em; }

/* Stats bar */
.stats-bar {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}
.stat-card {
  flex: 1;
  min-width: 120px;
  padding: 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  text-align: center;
}
.stat-card .stat-val { font-size: 1.8em; font-weight: 700; color: var(--accent2); }
.stat-card .stat-label { color: var(--text2); font-size: 0.8em; margin-top: 4px; }

/* Error */
.error-msg {
  padding: 16px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid var(--red);
  border-radius: 8px;
  color: var(--red);
  margin: 20px 0;
  display: none;
}

@media (max-width: 768px) {
  header h1 { font-size: 1.8em; }
  .upload-area { padding: 30px 20px; }
  .app-header-card { flex-direction: column; text-align: center; }
  .info-grid { grid-template-columns: 1fr; }
  .tabs { justify-content: center; }
}
</style>
</head>
<body>

<header>
  <h1><span>APK</span> Analyzer</h1>
  <p>Upload an Android APK file to inspect its contents, layouts, permissions, and resources</p>
</header>

<div class="container">
  <div class="upload-area" id="dropZone">
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
        d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
    </svg>
    <h3>Drop your APK file here</h3>
    <p>or click to browse (max 200 MB)</p>
    <button class="upload-btn" onclick="document.getElementById('fileInput').click()">Choose APK File</button>
    <input type="file" id="fileInput" accept=".apk">
  </div>

  <div class="progress-container" id="progressContainer">
    <p class="progress-text" id="progressText">Uploading and analyzing...</p>
    <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
  </div>

  <div class="error-msg" id="errorMsg"></div>

  <div id="results">
    <div class="app-header-card" id="appHeader"></div>

    <div class="stats-bar" id="statsBar"></div>

    <div class="tabs" id="tabsContainer">
      <button class="tab active" data-tab="overview">Overview</button>
      <button class="tab" data-tab="permissions">Permissions</button>
      <button class="tab" data-tab="components">Components</button>
      <button class="tab" data-tab="layouts">Layouts</button>
      <button class="tab" data-tab="images">Images</button>
      <button class="tab" data-tab="files">File Structure</button>
    </div>

    <div class="tab-content active" id="tab-overview"></div>
    <div class="tab-content" id="tab-permissions"></div>
    <div class="tab-content" id="tab-components"></div>
    <div class="tab-content" id="tab-layouts"></div>
    <div class="tab-content" id="tab-images"></div>
    <div class="tab-content" id="tab-files"></div>
  </div>
</div>

<script>
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const progressContainer = document.getElementById('progressContainer');
const progressFill = document.getElementById('progressFill');
const progressText = document.getElementById('progressText');
const errorMsg = document.getElementById('errorMsg');
const results = document.getElementById('results');

// Drag & drop
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const files = e.dataTransfer.files;
  if (files.length > 0) uploadFile(files[0]);
});
fileInput.addEventListener('change', () => { if (fileInput.files.length > 0) uploadFile(fileInput.files[0]); });

// Tabs
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
  });
});

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

async function uploadFile(file) {
  if (!file.name.toLowerCase().endsWith('.apk')) {
    showError('Please select a valid APK file.');
    return;
  }

  errorMsg.style.display = 'none';
  results.style.display = 'none';
  progressContainer.style.display = 'block';
  progressFill.style.width = '0%';
  progressText.textContent = 'Uploading APK (' + formatSize(file.size) + ')...';

  const formData = new FormData();
  formData.append('file', file);

  try {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/analyze');

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 70);
        progressFill.style.width = pct + '%';
        if (pct >= 70) progressText.textContent = 'Analyzing APK structure...';
      }
    };

    xhr.onload = () => {
      progressFill.style.width = '100%';
      progressContainer.style.display = 'none';
      if (xhr.status === 200) {
        const data = JSON.parse(xhr.responseText);
        renderResults(data);
      } else {
        const err = JSON.parse(xhr.responseText);
        showError(err.error || 'Unknown error');
      }
    };

    xhr.onerror = () => {
      progressContainer.style.display = 'none';
      showError('Network error. Please try again.');
    };

    xhr.send(formData);
  } catch (err) {
    progressContainer.style.display = 'none';
    showError('Error: ' + err.message);
  }
}

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.style.display = 'block';
}

const DANGEROUS_PERMS = [
  'CAMERA', 'READ_CONTACTS', 'WRITE_CONTACTS', 'GET_ACCOUNTS',
  'ACCESS_FINE_LOCATION', 'ACCESS_COARSE_LOCATION', 'RECORD_AUDIO',
  'READ_PHONE_STATE', 'CALL_PHONE', 'READ_CALL_LOG', 'WRITE_CALL_LOG',
  'SEND_SMS', 'RECEIVE_SMS', 'READ_SMS', 'READ_EXTERNAL_STORAGE',
  'WRITE_EXTERNAL_STORAGE', 'READ_CALENDAR', 'WRITE_CALENDAR',
  'BODY_SENSORS', 'USE_BIOMETRIC', 'ACCESS_BACKGROUND_LOCATION',
];

function isDangerous(perm) {
  return DANGEROUS_PERMS.some(d => perm.toUpperCase().includes(d));
}

function renderResults(data) {
  results.style.display = 'block';

  // App header
  const info = data.info;
  let iconHtml = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z"/></svg>';
  if (data.icon_data) {
    iconHtml = '<img src="data:image/png;base64,' + data.icon_data + '" alt="App Icon">';
  }
  document.getElementById('appHeader').innerHTML =
    '<div class="app-icon">' + iconHtml + '</div>' +
    '<div class="app-details">' +
      '<h2>' + escapeHtml(info.app_name) + '</h2>' +
      '<div class="package">' + escapeHtml(info.package) + '</div>' +
      '<div class="meta">' +
        '<span>Version ' + escapeHtml(info.version_name) + ' (' + escapeHtml(info.version_code) + ')</span>' +
        '<span>Min SDK: ' + escapeHtml(info.min_sdk) + '</span>' +
        '<span>Target SDK: ' + escapeHtml(info.target_sdk) + '</span>' +
      '</div>' +
    '</div>';

  // Stats
  document.getElementById('statsBar').innerHTML =
    '<div class="stat-card"><div class="stat-val">' + formatSize(data.apk_size) + '</div><div class="stat-label">APK Size</div></div>' +
    '<div class="stat-card"><div class="stat-val">' + data.permissions.length + '</div><div class="stat-label">Permissions</div></div>' +
    '<div class="stat-card"><div class="stat-val">' + data.activities.length + '</div><div class="stat-label">Activities</div></div>' +
    '<div class="stat-card"><div class="stat-val">' + data.layout_count + '</div><div class="stat-label">Layouts</div></div>' +
    '<div class="stat-card"><div class="stat-val">' + data.image_count + '</div><div class="stat-label">Images</div></div>';

  // Overview tab
  document.getElementById('tab-overview').innerHTML =
    '<div class="card"><h3>App Information</h3><div class="info-grid">' +
    Object.entries(info).map(([k, v]) =>
      '<div class="info-item"><div class="label">' + escapeHtml(k.replace(/_/g, ' ')) + '</div><div class="value">' + escapeHtml(String(v)) + '</div></div>'
    ).join('') +
    '</div></div>' +
    '<div class="card"><h3>Icon Path</h3><p style="color:var(--text2);font-family:monospace;font-size:0.9em">' + escapeHtml(data.icon_path || 'N/A') + '</p></div>';

  // Permissions tab
  const dangerousPerms = data.permissions.filter(isDangerous);
  const normalPerms = data.permissions.filter(p => !isDangerous(p));
  let permHtml = '';
  if (dangerousPerms.length > 0) {
    permHtml += '<div class="card"><h3>Sensitive Permissions <span class="badge" style="background:var(--red)">' + dangerousPerms.length + '</span></h3><ul class="perm-list">' +
      dangerousPerms.map(p => '<li><span class="dot perm-dangerous"></span>' + escapeHtml(p) + '</li>').join('') + '</ul></div>';
  }
  permHtml += '<div class="card"><h3>Other Permissions <span class="badge">' + normalPerms.length + '</span></h3><ul class="perm-list">' +
    normalPerms.map(p => '<li><span class="dot perm-normal"></span>' + escapeHtml(p) + '</li>').join('') + '</ul></div>';
  document.getElementById('tab-permissions').innerHTML = permHtml;

  // Components tab
  let compHtml = '<div class="card"><h3>Activities <span class="badge">' + data.activities.length + '</span></h3><ul class="comp-list">' +
    data.activities.map(a => '<li' + (a === data.main_activity ? ' class="main"' : '') + '>' + escapeHtml(a) + (a === data.main_activity ? ' <span style="color:var(--green);font-size:0.8em">(MAIN)</span>' : '') + '</li>').join('') + '</ul></div>';
  compHtml += '<div class="card"><h3>Services <span class="badge">' + data.services.length + '</span></h3><ul class="comp-list">' +
    data.services.map(s => '<li>' + escapeHtml(s) + '</li>').join('') + '</ul></div>';
  compHtml += '<div class="card"><h3>Broadcast Receivers <span class="badge">' + data.receivers.length + '</span></h3><ul class="comp-list">' +
    data.receivers.map(r => '<li>' + escapeHtml(r) + '</li>').join('') + '</ul></div>';
  if (data.providers.length > 0) {
    compHtml += '<div class="card"><h3>Content Providers <span class="badge">' + data.providers.length + '</span></h3><ul class="comp-list">' +
      data.providers.map(p => '<li>' + escapeHtml(p) + '</li>').join('') + '</ul></div>';
  }
  document.getElementById('tab-components').innerHTML = compHtml;

  // Layouts tab
  let layoutHtml = '<div class="card"><h3>Layout XML Files <span class="badge">' + data.layout_count + '</span></h3>';
  if (data.layouts.length === 0) {
    layoutHtml += '<p style="color:var(--text2)">No layout files found (this APK might use Jetpack Compose or React Native).</p>';
  } else {
    data.layouts.forEach((layout, i) => {
      layoutHtml += '<div class="layout-item">' +
        '<div class="layout-path" onclick="toggleLayout(' + i + ')">' +
          '<span>' + escapeHtml(layout.path) + '</span>' +
          '<span id="arrow-' + i + '">&#9654;</span>' +
        '</div>' +
        '<div class="layout-xml" id="layout-' + i + '"><pre>' + escapeHtml(layout.xml) + '</pre></div>' +
      '</div>';
    });
  }
  layoutHtml += '</div>';
  document.getElementById('tab-layouts').innerHTML = layoutHtml;

  // Images tab
  let imgHtml = '<div class="card"><h3>Image Resources <span class="badge">' + data.image_count + '</span></h3>';
  if (data.images.length === 0) {
    imgHtml += '<p style="color:var(--text2)">No image resources found.</p>';
  } else {
    imgHtml += '<div class="images-grid">';
    data.images.forEach(img => {
      imgHtml += '<div class="image-item">' +
        '<div class="path">' + escapeHtml(img.path) + '</div>' +
        '<div class="size-label">' + formatSize(img.size) + '</div>' +
      '</div>';
    });
    imgHtml += '</div>';
  }
  imgHtml += '</div>';
  document.getElementById('tab-images').innerHTML = imgHtml;

  // Files tab
  let filesHtml = '<div class="card"><h3>File Structure</h3>';
  Object.entries(data.folder_summary)
    .sort((a, b) => b[1].total_size - a[1].total_size)
    .forEach(([folder, meta]) => {
      filesHtml += '<div class="folder-item"><div class="folder-header">' +
        '<span class="folder-name">' +
          '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/></svg>' +
          escapeHtml(folder) +
        '</span>' +
        '<span class="folder-meta">' + meta.count + ' files &middot; ' + formatSize(meta.total_size) + '</span>' +
      '</div></div>';
    });
  filesHtml += '</div>';
  document.getElementById('tab-files').innerHTML = filesHtml;

  results.scrollIntoView({ behavior: 'smooth' });
}

function toggleLayout(i) {
  const el = document.getElementById('layout-' + i);
  const arrow = document.getElementById('arrow-' + i);
  el.classList.toggle('open');
  arrow.textContent = el.classList.contains('open') ? '\\u25BC' : '\\u25B6';
}
</script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
