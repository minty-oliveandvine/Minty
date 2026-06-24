/**
 * Shared Datadog client logging: loads SDK, initializes from window config, exposes sendLogToDataDog,
 * and installs global error/console handlers. Pages only set window.DD_CLIENT_TOKEN (or window.DD_CONFIG)
 * and include this script.
 */
(function() {
  'use strict';

  var config = window.DD_CONFIG || {};
  var clientToken = config.clientToken || window.DD_CLIENT_TOKEN;
  if (!clientToken) {
    return;
  }

  var initOptions = Object.assign({
    clientToken: clientToken,
    site: 'ap1.datadoghq.com',
    forwardErrorsToLogs: true,
    sessionSampleRate: 100
  }, config);

  if (!window.DD_LOGS) {
    window.DD_LOGS = { q: [], onReady: function(cb) { this.q.push(cb); } };
    (function(h, o, u, n, d) {
      d = o.createElement(u);
      d.async = 1;
      d.src = n;
      o.getElementsByTagName(u)[0].parentNode.insertBefore(d, o.getElementsByTagName(u)[0]);
    })(window, document, 'script', 'https://www.datadoghq-browser-agent.com/ap1/v6/datadog-logs.js', 'DD_LOGS');
  }

  function serializeForLog(val) {
    if (val === null) return 'null';
    if (val === undefined) return 'undefined';
    if (typeof val !== 'object') return String(val);
    if (typeof val.message === 'string' && (val.stack || val.name)) {
      return val.message + (val.stack ? '\n' + val.stack : '');
    }
    try {
      return JSON.stringify(val);
    } catch (e) {
      return Object.prototype.toString.call(val);
    }
  }

  function normalizeLogData(obj) {
    var out = {};
    var key;
    for (key in obj) {
      if (Object.prototype.hasOwnProperty.call(obj, key)) {
        var val = obj[key];
        if (val === null || val === undefined) {
          out[key] = val === null ? 'null' : 'undefined';
        } else if (typeof val === 'object') {
          if (typeof val.message === 'string' && (val.stack || val.name)) {
            out[key] = val.message;
            if (val.stack) out[key + 'Stack'] = val.stack;
          } else {
            try {
              out[key] = JSON.stringify(val);
            } catch (e) {
              out[key] = Object.prototype.toString.call(val);
            }
          }
        } else {
          out[key] = val;
        }
      }
    }
    return out;
  }

  function sendLogToDataDog(level, message, extra) {
    if (typeof message !== 'string') {
      message = serializeForLog(message);
    }
    extra = extra || {};
    if (window.DD_LOGS && window.DD_LOGS.logger) {
      try {
        var logData = Object.assign({}, extra, {
          url: window.location.href,
          userAgent: navigator.userAgent,
          timestamp: new Date().toISOString()
        });
        logData = normalizeLogData(logData);
        if (level === 'error') {
          window.DD_LOGS.logger.error(message, logData);
        } else if (level === 'warn') {
          window.DD_LOGS.logger.warn(message, logData);
        } else {
          window.DD_LOGS.logger.info(message, logData);
        }
      } catch (err) {
        try { console.error('Failed to send log to DataDog:', err); } catch (e) {}
      }
    } else {
      window.DD_LOGS = window.DD_LOGS || { q: [] };
      window.DD_LOGS.onReady = window.DD_LOGS.onReady || function(callback) {
        window.DD_LOGS.q.push(callback);
      };
      window.DD_LOGS.onReady(function() {
        sendLogToDataDog(level, message, extra);
      });
    }
  }

  window.sendLogToDataDog = sendLogToDataDog;

  window.DD_LOGS.onReady(function() {
    if (window.DD_LOGS.init) {
      window.DD_LOGS.init(initOptions);
    }

    var originalConsole = {
      error: console.error.bind(console),
      warn: console.warn.bind(console),
      log: console.log.bind(console)
    };

    console.error = function() {
      originalConsole.error.apply(console, arguments);
      var parts = [];
      for (var i = 0; i < arguments.length; i++) {
        parts.push(serializeForLog(arguments[i]));
      }
      sendLogToDataDog('error', parts.join(' '), { type: 'console.error' });
    };
    console.warn = function() {
      originalConsole.warn.apply(console, arguments);
      var parts = [];
      for (var i = 0; i < arguments.length; i++) {
        parts.push(serializeForLog(arguments[i]));
      }
      sendLogToDataDog('warn', parts.join(' '), { type: 'console.warn' });
    };
    console.log = function() {
      originalConsole.log.apply(console, arguments);
      var parts = [];
      for (var i = 0; i < arguments.length; i++) {
        parts.push(serializeForLog(arguments[i]));
      }
      sendLogToDataDog('info', parts.join(' '), { type: 'console.log' });
    };

    window.onerror = function(message, source, lineno, colno, error) {
      sendLogToDataDog('error', message, {
        type: 'uncaught_error',
        source: source,
        lineno: lineno,
        colno: colno,
        stack: error && error.stack,
        errorName: error && error.name
      });
      return false;
    };

    window.addEventListener('unhandledrejection', function(event) {
      sendLogToDataDog('error', (event.reason && event.reason.message) || 'Unhandled Promise Rejection', {
        type: 'unhandled_rejection',
        stack: event.reason && event.reason.stack,
        errorName: event.reason && event.reason.name
      });
    });

    sendLogToDataDog('info', 'Page loaded', { path: window.location.pathname });
  });
})();
