(function () {
  var KEY = "reportBackUrl";

  function segs(path) {
    return (path || "").split("/").filter(Boolean);
  }

  function isHistoryPage(path) {
    var s = segs(path);
    return s[s.length - 1] === "reports";
  }

  function isReportPage(path) {
    var s = segs(path);
    if (s[0] === "report") return true;
    var sections = [
      "ending",
      "opening",
      "sale",
      "sales",
      "expense",
      "deposit",
      "cash_count",
    ];
    return s.some(function (x) {
      return sections.indexOf(x) >= 0;
    });
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
