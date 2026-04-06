"""Web UI routes – landing page for the OCR Service."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

ui_router = APIRouter(include_in_schema=False)

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>OCR Service</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    @keyframes spin { to { transform: rotate(360deg); } }
    .spinner { animation: spin 0.8s linear infinite; }
  </style>
</head>
<body class="min-h-screen bg-gradient-to-br from-slate-50 to-indigo-50 flex flex-col items-center justify-start p-8">

  <div class="w-full max-w-xl space-y-8">

    <!-- Header -->
    <div class="text-center pt-6">
      <div class="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-indigo-600 shadow-md mb-4">
        <svg class="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1
               0 01.707.293l5.414 5.414A1 1 0 0119 9.414V19a2 2 0 01-2 2z"/>
        </svg>
      </div>
      <h1 class="text-3xl font-bold text-slate-800 tracking-tight">Welcome to OCR Service</h1>
      <p class="mt-2 text-slate-500 text-sm">Please upload any image to extract its text</p>
    </div>

    <!-- ── Upload Card ───────────────────────────────────────────────────── -->
    <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 space-y-4">
      <h2 class="text-sm font-semibold text-slate-700 uppercase tracking-wider">Upload Image</h2>

      <label class="flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed
                    border-slate-300 bg-slate-50 py-8 px-4 cursor-pointer transition-colors
                    hover:border-indigo-400 hover:bg-indigo-50">
        <svg class="w-9 h-9 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0
               012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2
               2 0 00-2 2v12a2 2 0 002 2z"/>
        </svg>
        <span class="text-sm text-slate-500">
          <span class="font-medium text-indigo-600">Click to choose a file</span>
          &nbsp;or drag &amp; drop
        </span>
        <span id="chosen-file" class="text-xs text-indigo-500 font-medium hidden"></span>
        <input id="file-input" type="file"
               accept="image/jpeg,image/jpg,image/png,image/tiff,image/bmp,image/webp"
               class="hidden" />
      </label>

      <button id="upload-btn"
              onclick="uploadImage()"
              disabled
              class="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800
                     text-white text-sm font-semibold shadow transition-colors
                     disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2">
        <svg id="upload-icon" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/>
        </svg>
        <span id="upload-label">Upload Image</span>
      </button>
    </div>

    <!-- ── Get OCR Card ──────────────────────────────────────────────────── -->
    <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 space-y-4">
      <h2 class="text-sm font-semibold text-slate-700 uppercase tracking-wider">Get OCR Text</h2>

      <div class="flex gap-2">
        <input id="image-id-input"
               type="text"
               placeholder="Paste image_id here…"
               class="flex-1 rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm
                      text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2
                      focus:ring-indigo-300 transition" />
        <button id="ocr-btn"
                onclick="getOCR()"
                class="px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800
                       text-white text-sm font-semibold shadow transition-colors
                       flex items-center gap-2">
          <svg id="ocr-icon" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943
                 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
          </svg>
          <span id="ocr-label">Get OCR</span>
        </button>
      </div>

      <!-- Status / spinner -->
      <div id="ocr-status" class="hidden text-xs text-slate-400 flex items-center gap-2">
        <svg class="spinner w-3 h-3 text-indigo-500" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
        </svg>
        <span id="ocr-status-msg">Fetching OCR text…</span>
      </div>

      <!-- Output textarea -->
      <div>
        <div class="flex items-center justify-between mb-1.5">
          <label class="text-xs font-medium text-slate-500">Extracted Text</label>
          <button id="copy-btn"
                  onclick="copyText()"
                  class="hidden text-xs text-indigo-600 hover:text-indigo-800 font-medium transition-colors">
            Copy
          </button>
        </div>
        <textarea id="ocr-output"
                  readonly
                  rows="10"
                  placeholder="OCR text will appear here…"
                  class="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm
                         text-slate-700 placeholder-slate-400 resize-y focus:outline-none
                         focus:ring-2 focus:ring-indigo-300 transition"></textarea>
        <div id="ocr-meta" class="hidden mt-1.5 text-xs text-slate-400 flex gap-4">
          <span id="meta-confidence"></span>
          <span id="meta-time"></span>
        </div>
      </div>

      <!-- Error box -->
      <div id="ocr-error"
           class="hidden rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-600">
      </div>
    </div>

    <p class="text-center text-xs text-slate-400 pb-6">
      OCR Service &bull;
      <a href="/docs" class="text-indigo-400 hover:underline">API Docs</a>
    </p>
  </div>

  <!-- ── Success popup ─────────────────────────────────────────────────────── -->
  <div id="popup-overlay"
       class="hidden fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50"
       onclick="closePopup(event)">
    <div class="bg-white rounded-2xl shadow-xl p-8 max-w-sm w-full mx-4 text-center space-y-4">
      <div class="inline-flex items-center justify-center w-12 h-12 rounded-full bg-green-100">
        <svg class="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
        </svg>
      </div>
      <h3 class="text-lg font-bold text-slate-800">Upload Successful!</h3>
      <p class="text-sm text-slate-500">Your image has been accepted for processing.</p>
      <div class="rounded-lg bg-indigo-50 border border-indigo-100 px-4 py-3 text-left">
        <p class="text-xs font-medium text-slate-500 mb-1">Image ID</p>
        <p id="popup-image-id" class="text-sm font-mono text-indigo-700 break-all"></p>
      </div>
      <button onclick="useImageId()"
              class="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white
                     text-sm font-semibold shadow transition-colors">
        Use this Image ID
      </button>
      <button onclick="closePopup()"
              class="w-full py-2 rounded-xl border border-slate-200 text-slate-500
                     text-sm font-medium hover:bg-slate-50 transition-colors">
        Close
      </button>
    </div>
  </div>

  <script>
    const fileInput     = document.getElementById('file-input');
    const chosenFile    = document.getElementById('chosen-file');
    const uploadBtn     = document.getElementById('upload-btn');
    const uploadLabel   = document.getElementById('upload-label');
    const uploadIcon    = document.getElementById('upload-icon');
    const imageIdInput  = document.getElementById('image-id-input');
    const ocrBtn        = document.getElementById('ocr-btn');
    const ocrLabel      = document.getElementById('ocr-label');
    const ocrIcon       = document.getElementById('ocr-icon');
    const ocrOutput     = document.getElementById('ocr-output');
    const ocrStatus     = document.getElementById('ocr-status');
    const ocrStatusMsg  = document.getElementById('ocr-status-msg');
    const ocrError      = document.getElementById('ocr-error');
    const ocrMeta       = document.getElementById('ocr-meta');
    const copyBtn       = document.getElementById('copy-btn');
    const popupOverlay  = document.getElementById('popup-overlay');
    const popupImageId  = document.getElementById('popup-image-id');

    let _lastImageId = null;

    // ── File selection ───────────────────────────────────────────────────────
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length) {
        chosenFile.textContent = fileInput.files[0].name;
        chosenFile.classList.remove('hidden');
        uploadBtn.disabled = false;
      }
    });

    // ── Upload ───────────────────────────────────────────────────────────────
    async function uploadImage() {
      const file = fileInput.files[0];
      if (!file) return;

      setUploadLoading(true);
      const formData = new FormData();
      formData.append('file', file);

      try {
        const res  = await fetch('/api/v1/upload', { method: 'POST', body: formData });
        const data = await res.json();

        if (!res.ok) {
          alert('Upload failed: ' + (data.detail || `HTTP ${res.status}`));
          return;
        }

        _lastImageId = data.image_id;
        popupImageId.textContent = data.image_id;
        popupOverlay.classList.remove('hidden');

      } catch (err) {
        alert('Network error – could not reach the service.');
      } finally {
        setUploadLoading(false);
      }
    }

    function setUploadLoading(on) {
      uploadBtn.disabled = on;
      if (on) {
        uploadLabel.textContent = 'Uploading…';
        uploadIcon.outerHTML = '<svg id="upload-icon" class="spinner w-4 h-4" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/></svg>';
      } else {
        uploadLabel.textContent = 'Upload Image';
        document.getElementById('upload-icon').outerHTML = '<svg id="upload-icon" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/></svg>';
      }
    }

    // ── Popup helpers ─────────────────────────────────────────────────────────
    function closePopup(e) {
      if (e && e.target !== popupOverlay) return;
      popupOverlay.classList.add('hidden');
    }

    function useImageId() {
      imageIdInput.value = _lastImageId || '';
      popupOverlay.classList.add('hidden');
    }

    // ── Get OCR ───────────────────────────────────────────────────────────────
    async function getOCR() {
      const imageId = imageIdInput.value.trim();
      if (!imageId) {
        imageIdInput.focus();
        return;
      }

      setOCRLoading(true);
      clearOCRResults();

      try {
        const res  = await fetch(`/api/v1/images/${encodeURIComponent(imageId)}/text`);
        const data = await res.json();

        if (!res.ok) {
          showOCRError(data.detail || `HTTP ${res.status}`);
          return;
        }

        if (data.text == null) {
          ocrStatusMsg.textContent = data.message || 'OCR not complete yet — try again shortly.';
          ocrStatus.classList.remove('hidden');
          return;
        }

        ocrOutput.value = data.text;
        copyBtn.classList.remove('hidden');

        if (data.confidence != null || data.processing_time_ms != null) {
          ocrMeta.classList.remove('hidden');
          document.getElementById('meta-confidence').textContent =
            data.confidence != null ? `Confidence: ${(data.confidence * 100).toFixed(1)}%` : '';
          document.getElementById('meta-time').textContent =
            data.processing_time_ms != null
              ? `Processed in ${data.processing_time_ms.toFixed(0)} ms`
              : '';
        }

      } catch (err) {
        showOCRError('Network error – could not reach the service.');
      } finally {
        setOCRLoading(false);
      }
    }

    function setOCRLoading(on) {
      ocrBtn.disabled = on;
      ocrStatus.classList.toggle('hidden', !on);
      if (on) {
        ocrStatusMsg.textContent = 'Fetching OCR text…';
        ocrLabel.textContent = 'Loading…';
      } else {
        ocrLabel.textContent = 'Get OCR';
        if (ocrOutput.value === '') ocrStatus.classList.add('hidden');
      }
    }

    function clearOCRResults() {
      ocrOutput.value = '';
      ocrMeta.classList.add('hidden');
      ocrError.classList.add('hidden');
      ocrError.textContent = '';
      copyBtn.classList.add('hidden');
    }

    function showOCRError(msg) {
      ocrError.textContent = msg;
      ocrError.classList.remove('hidden');
    }

    function copyText() {
      navigator.clipboard.writeText(ocrOutput.value).then(() => {
        copyBtn.textContent = 'Copied!';
        setTimeout(() => { copyBtn.textContent = 'Copy'; }, 2000);
      });
    }
  </script>
</body>
</html>"""


@ui_router.get("/", response_class=HTMLResponse)
async def homepage() -> HTMLResponse:
    return HTMLResponse(content=_HTML)
