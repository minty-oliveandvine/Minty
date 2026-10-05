/**
 * "‹ Back" on the settings pages: back to the page the person came from (2026-10-05).
 *
 * It replaced the ?from=bills flag, which only told two places apart and broke on every hop
 * that dropped it. "Came from" = the last page in this tab's history OUTSIDE the settings area
 * (/entity/settings/... and /entity/<id>/settings/...): moving between the tabs, saving (a POST
 * then a redirect) and reloading all add entries inside the area, and Back skips them.
 *
 * - Navigation API: walk back over this site's entries. The first one outside the area is the
 *   target. If they run out, the person came from another app (Payments, minty-web) and the
 *   entry before them is that app's page; if there is none (a new tab), follow the fallback.
 * - Without it: history.back() when there is anything to go back to, else the fallback.
 *
 * The link is a real <a data-back-link href="<fallback>">: middle-click, a new tab or no script
 * at all lands on the fallback (the company's home). Leave guards replay the click after
 * "Discard changes", so they need nothing extra; a guard that navigates by itself calls
 * window.MintyBack.go(link).
 *
 * minty-web's lib/backLink.ts is the same rule for its pages.
 */
(function () {
  "use strict";

  // /entity/<shortid>/<name>/settings/... since 2026-10-05; the two older shapes still redirect.
  var SETTINGS_AREA = [
    /^\/entity\/[^/]+\/[^/]+\/settings\//,
    /^\/entity\/settings\//,
    /^\/entity\/[^/]+\/settings\//,
  ];

  function inSettingsArea(href) {
    try {
      var url = new URL(href, window.location.href);
      return (
        url.origin === window.location.origin &&
        SETTINGS_AREA.some(function (rule) {
          return rule.test(url.pathname);
        })
      );
    } catch (err) {
      return false;
    }
  }

  /** How many entries to go back: a number (0 = nothing to go back to), or null when the
   * browser cannot say (no Navigation API).
   *
   * navigation.entries() lists only THIS site's run of entries, and an entry's `index` is its
   * place in that list - not in the tab's whole history. So when every entry before this one is
   * in the settings area, history.length tells whether another app's page came before the run:
   * the tab holds more entries than the run (new navigations clear the forward ones). */
  function stepsBack() {
    var nav = window.navigation;
    if (!nav || !nav.currentEntry || typeof nav.entries !== "function") return null;
    var entries = nav.entries();
    var at = nav.currentEntry.index;
    if (at < 0 || at >= entries.length) return null;
    for (var p = at - 1; p >= 0; p--) {
      if (!inSettingsArea(entries[p].url)) return at - p;
    }
    return window.history.length > entries.length ? at + 1 : 0;
  }

  function go(link) {
    var steps = stepsBack();
    if (steps === null) {
      if (window.history.length > 1) window.history.back();
      else window.location.assign(link.href);
      return;
    }
    if (steps > 0) window.history.go(-steps);
    else window.location.assign(link.href);
  }

  document.addEventListener("click", function (event) {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    var target = event.target instanceof Element ? event.target : null;
    var link = target ? target.closest("a[data-back-link]") : null;
    if (!link) return;
    event.preventDefault();
    go(link);
  });

  window.MintyBack = { go: go, stepsBack: stepsBack };
})();
