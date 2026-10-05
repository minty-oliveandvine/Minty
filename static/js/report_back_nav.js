(function () {
  var KEY = "reportBackUrl";

  function segs(path) {
    return (path || "").split("/").filter(Boolean);
  }

  function isHistoryPage(path) {
    var s = segs(path);
    return s[s.length - 1] === "reports";
  }

  // A report page: the old /report/... addresses, or anything BELOW a company's reports
  // (/entity/<shortid>/<name>/reports/<id or new>/<step>, .../reports/<id>/summary). Keyed on
  // what follows "reports" - a company named "Sale" must not make its dashboard look like one.
  function isReportPage(path) {
    var s = segs(path);
    if (s[0] === "report") return true;
    var at = s.indexOf("reports");
    return at >= 0 && at < s.length - 1;
  }

  function init() {
    var link = document.getElementById("reportBackLink");
    if (!link) return;

    var dashboard = link.getAttribute("href") || "/";
    var back = dashboard;

    try {
      var ref = document.referrer ? new URL(document.referrer) : null;
      if (ref && ref.origin === window.location.origin) {
        var path = ref.pathname;
        if (isHistoryPage(path)) {
          back = path + ref.search;
          sessionStorage.setItem(KEY, back);
        } else if (isReportPage(path)) {
          back = sessionStorage.getItem(KEY) || dashboard;
        } else {
          sessionStorage.removeItem(KEY);
          back = dashboard;
        }
      } else {
        back = sessionStorage.getItem(KEY) || dashboard;
      }
    } catch (e) {
      back = dashboard;
    }

    link.setAttribute("href", back);
  }

  if (document.readyState !== "loading") init();
  else document.addEventListener("DOMContentLoaded", init);
})();
