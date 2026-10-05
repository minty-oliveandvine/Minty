/**
 * A receipt drawn on the page (2026-10-05): the Expenses step's preview, in the Payment Request
 * app's look (minty-payment-request-web/components/PdfJsCanvasPreview.tsx, ported to plain JS).
 *
 * - An image is an <img>.
 * - A PDF is one canvas per page, drawn by pdf.js - an <iframe> shows nothing on Android Chrome
 *   and only page 1 on iOS. pdf.js is loaded on first use, pinned, from jsDelivr (Flask has no
 *   build step; it loads Tailwind, jQuery and flatpickr the same way). It fetches the file, so a
 *   saved receipt is read from this origin (/preview/<key>, report/routes/download.py), never
 *   through /download's redirect to the bucket.
 * - Anything that can't be drawn says why in a sentence; the box is never left blank.
 *
 *   ReceiptPreview.kind(nameOrMimeType)               -> "image" | "pdf" | "other"
 *   ReceiptPreview.render(host, source, options)      -> Promise; source = File/Blob or URL
 *       options: { kind, maxPages (default 50), title, fit: "width" | "contain" }
 */
(function () {
  "use strict";

  var PDFJS_VERSION = "4.10.38";
  var PDFJS_BASE = "https://cdn.jsdelivr.net/npm/pdfjs-dist@" + PDFJS_VERSION;
  var DEFAULT_MAX_PAGES = 50;
  var pdfjsPromise = null;

  function loadPdfjs() {
    if (!pdfjsPromise) {
      pdfjsPromise = import(PDFJS_BASE + "/build/pdf.min.mjs").then(function (pdfjs) {
        pdfjs.GlobalWorkerOptions.workerSrc = PDFJS_BASE + "/build/pdf.worker.min.mjs";
        return pdfjs;
      });
      pdfjsPromise.catch(function () {
        pdfjsPromise = null; // a failed load (offline) may be retried by the next preview
      });
    }
    return pdfjsPromise;
  }

  function kind(nameOrType) {
    var v = String(nameOrType || "").toLowerCase().split("?")[0];
    if (v.indexOf("application/pdf") === 0 || /\.pdf$/.test(v)) return "pdf";
    if (v.indexOf("image/") === 0 || /\.(jpe?g|png|gif|webp)$/.test(v)) return "image";
    return "other";
  }

  function kindOf(source) {
    if (source && typeof source === "object" && "type" in source) {
      var k = kind(source.type);
      return k !== "other" ? k : kind(source.name);
    }
    return kind(source);
  }

  // The Payment Request app's sentences (describePdfError), so both apps say the same thing.
  function describePdfError(err) {
    switch (err && err.name) {
      case "InvalidPDFException":
        return "This file looks damaged or isn't a valid PDF, so it can't be previewed.";
      case "PasswordException":
        return "This PDF's locked, so I couldn't open it for preview.";
      case "MissingPDFException":
      case "UnexpectedResponseException":
        return "That PDF didn't come through. Check your connection, then mind trying again?";
      default:
        return "This PDF can't be previewed here.";
    }
  }

  function message(host, text) {
    var p = document.createElement("p");
    p.className = "receipt-preview-message px-4 py-6 text-center text-sm text-gray-500";
    p.style.lineHeight = "1.4";
    p.textContent = text;
    host.replaceChildren(p);
  }

  function renderImage(host, url, title, fit) {
    return new Promise(function (resolve) {
      var img = document.createElement("img");
      img.alt = title || "Receipt";
      img.className = fit === "contain"
        ? "mx-auto block max-h-full max-w-full object-contain"
        : "mx-auto block h-auto w-full rounded border border-gray-200 bg-white";
      img.onload = function () { resolve(); };
      img.onerror = function () {
        message(host, "This image can't be previewed here.");
        resolve();
      };
      img.src = url;
      host.replaceChildren(img);
    });
  }

  function renderPdf(host, url, opts) {
    // Each render owns the host; a newer one (another file picked) cancels this one.
    var token = {};
    host.__receiptPreviewToken = token;
    var live = function () { return host.__receiptPreviewToken === token; };
    host.replaceChildren();
    var loading = document.createElement("p");
    loading.className = "receipt-preview-message px-4 py-6 text-center text-sm text-gray-400";
    loading.textContent = "Loading preview…";
    host.appendChild(loading);

    var pdfDoc = null;
    return loadPdfjs()
      .then(function (pdfjs) {
        return pdfjs.getDocument({
          url: url,
          cMapUrl: PDFJS_BASE + "/cmaps/",
          cMapPacked: true,
          standardFontDataUrl: PDFJS_BASE + "/standard_fonts/",
        }).promise;
      })
      .then(function (doc) {
        pdfDoc = doc;
        if (!live()) return null;
        var limit = Math.min(doc.numPages, Math.max(1, opts.maxPages || DEFAULT_MAX_PAGES));
        // at least 2x and up to 3x the CSS size, so small print stays sharp on any screen
        var dpr = Math.min(Math.max(window.devicePixelRatio || 1, 2), 3);
        var width = Math.max(host.clientWidth || 0, 280);
        var pages = document.createElement("div");
        pages.className = "flex flex-col gap-3";
        var chain = Promise.resolve();
        for (var n = 1; n <= limit; n++) {
          chain = chain.then(drawPage.bind(null, n));
        }
        function drawPage(n) {
          if (!live()) return null;
          return doc.getPage(n).then(function (page) {
            var base = page.getViewport({ scale: 1 });
            var scale = Math.min(width / base.width, 4);
            var viewport = page.getViewport({ scale: scale });
            var canvas = document.createElement("canvas");
            canvas.setAttribute("role", "img");
            canvas.setAttribute("aria-label", (opts.title || "Receipt") + " - page " + n + " of " + doc.numPages);
            canvas.width = Math.floor(viewport.width * dpr);
            canvas.height = Math.floor(viewport.height * dpr);
            canvas.style.width = "100%";
            canvas.style.height = "auto";
            canvas.style.maxWidth = Math.ceil(viewport.width) + "px";
            canvas.className = "mx-auto block rounded border border-gray-200 bg-white shadow-sm";
            var ctx = canvas.getContext("2d");
            ctx.scale(dpr, dpr);
            return page.render({ canvasContext: ctx, viewport: viewport }).promise.then(function () {
              if (!live()) return;
              pages.appendChild(canvas);
              if (n === 1) host.replaceChildren(pages);
            });
          });
        }
        return chain.then(function () {
          if (live() && limit < doc.numPages) {
            var note = document.createElement("p");
            note.className = "mt-2 text-center text-xs text-gray-500";
            note.textContent = "Showing first " + limit + " of " + doc.numPages + " pages.";
            pages.appendChild(note);
          }
        });
      })
      .catch(function (err) {
        if (live()) message(host, describePdfError(err));
        if (window.console) console.warn("Receipt preview failed:", err);
      })
      .finally(function () {
        if (pdfDoc) pdfDoc.destroy();
      });
  }

  function render(host, source, options) {
    var opts = options || {};
    if (!host) return Promise.resolve();
    var k = opts.kind || kindOf(source);
    var isBlob = source && typeof source === "object";
    var url = isBlob ? URL.createObjectURL(source) : String(source || "");
    var done = function () {
      // the blob URL is only for the draw; keep it for an <img>, which reads it lazily
      if (isBlob && k === "pdf") URL.revokeObjectURL(url);
    };
    if (k === "image") return renderImage(host, url, opts.title, opts.fit);
    if (k === "pdf") return renderPdf(host, url, opts).then(done, done);
    message(host, "This file can't be previewed here.");
    return Promise.resolve();
  }

  window.ReceiptPreview = { kind: kind, render: render };
})();
