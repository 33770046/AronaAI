"use strict";

// Clean-room QWebChannel-compatible facade over the qtwebview2 bridge.
// Provides window.qt.webChannelTransport and window.QWebChannel with the
// subset of the Qt qwebchannel.js API that index.html uses:
//   new QWebChannel(transport, function (channel) { channel.objects.<name> ... })
// Message envelope (both directions): JSON {m: name, a: [args...]}.
// JS -> Python: transport.send -> window.qtwebview2.api.wcMessage(str)
// Python -> JS: evaluate_js -> transport.onmessage({data: str})
(function () {
    var queue = [];
    var deliver = null;

    window.qt = window.qt || {};
    window.qt.webChannelTransport = {
        send: function (str) {
            var api = window.qtwebview2 && window.qtwebview2.api;
            if (!api) {
                console.error("bridge-shim: qtwebview2 api not injected");
                return Promise.resolve();
            }
            return api.wcMessage(str).catch(function (e) {
                console.error("bridge-shim: wcMessage failed: " + e);
            });
        },
        onmessage: function (message) {
            var data = (message && typeof message === "object" && "data" in message)
                ? message.data : message;
            if (deliver) {
                deliver(data);
            } else {
                queue.push(data);
            }
        }
    };

    function makeSignal() {
        var subs = [];
        return {
            connect: function (fn) {
                if (typeof fn === "function") subs.push(fn);
            },
            disconnect: function (fn) {
                subs = subs.filter(function (f) { return f !== fn; });
            },
            _fire: function (args) {
                subs.slice().forEach(function (fn) {
                    try { fn.apply(null, args); }
                    catch (e) { console.error("bridge-shim: signal handler error: " + e); }
                });
            }
        };
    }

    function QWebChannel(transport, initCallback) {
        var methods = [
            "setModelSize", "setModelRect", "showError",
            "onDoubleClick", "sendTextToModel",
            "patZone", "patState", "chatZone", "dragState"
        ];
        var signals = ["layoutChanged", "moveTo", "cursorMoved"];
        var bridge = {};
        var i;

        for (i = 0; i < methods.length; i++) {
            (function (name) {
                bridge[name] = function () {
                    transport.send(JSON.stringify({
                        m: name,
                        a: Array.prototype.slice.call(arguments)
                    }));
                };
            })(methods[i]);
        }
        for (i = 0; i < signals.length; i++) {
            bridge[signals[i]] = makeSignal();
        }

        deliver = function (raw) {
            var msg;
            try {
                msg = typeof raw === "string" ? JSON.parse(raw) : raw;
            } catch (e) {
                console.error("bridge-shim: bad message: " + e);
                return;
            }
            if (!msg || typeof msg.m !== "string") return;
            var slot = bridge[msg.m];
            if (slot && typeof slot._fire === "function") {
                slot._fire(msg.a || []);
            }
        };
        while (queue.length) {
            deliver(queue.shift());
        }

        if (typeof initCallback === "function") {
            initCallback({objects: {bridge: bridge}});
        }
    }

    window.QWebChannel = QWebChannel;
})();
