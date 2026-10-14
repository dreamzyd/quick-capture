// quick-capture PWA 安装引导（2026-10-14 v2: 增加"拿不到浏览器安装事件"时的兜底指引）
(function () {
  "use strict";

      };
      var render = function () {
        dLines = ["diag qc-pwa " + new Date().toISOString() + "  +" + secs + "s",
          "protocol=" + location.protocol + "  isSecureContext=" + window.isSecureContext,
          "standalone=" + isStandalone() + "  SW supported=" + ("serviceWorker" in navigator),
          "SW controller=" + !!(navigator.serviceWorker && navigator.serviceWorker.controller),
          "beforeinstallprompt=" + (bipFired ? "FIRED" : "NOT-FIRED-YET"),
          "已回传服务端: " + sentCount + " 次（请在页面停留 15 秒）",
          "UA=" + navigator.userAgent];
        paint();
      };
      (document.body || document.documentElement).appendChild(box);
      window.setInterval(function () { secs = Math.round((Date.now() - t0) / 1000); render(); }, 1000);
      window.addEventListener("beforeinstallprompt", function () { bipFired = true; send("bip"); render(); });
      window.addEventListener("appinstalled", function () { send("appinstalled"); render(); });
      send("load"); render();
      window.setTimeout(function () { render(); send("t5"); }, 5000);
      window.setTimeout(function () { render(); send("t15"); }, 15000);
      if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
        navigator.serviceWorker.getRegistrations().then(function (rs) {
          dLines.push("registrations=" + rs.length + " [" + rs.map(function (r) { return r.scope; }).join(", ") + "]");
          paint();
        });
      }
    }
  } catch (e) {}
  var tip = document.getElementById("pwa-install-tip");
  var text = document.getElementById("pwa-install-text");
  var btn = document.getElementById("pwa-install-btn");
  var deferred = null;
  var BTN_STYLE = "display:none; margin-left: 8px; background: none; border: 0; padding: 0; " +
    "color: inherit; font: inherit; text-decoration: underline; cursor: pointer;";

  function isStandalone() {
    return (
      (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
      window.navigator.standalone === true
    );
  }
  function show() { if (tip) { tip.style.display = "block"; } }
  function hide() { if (tip) { tip.style.display = "none"; } }
  function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k) { try { localStorage.setItem(k, "1"); } catch (e) {} }

  if (isStandalone()) { return; } // 已经装到桌面，不再提示

  // 页面若没有安装条占位，就在主容器末尾自动注入一个（保证任何页面都能给出安装指引）
  if (!tip) {
    var host = document.querySelector("main.container") ||
      document.querySelector("main") ||
      document.body;
    if (!host) { return; }
    tip = document.createElement("section");
    tip.id = "pwa-install-tip";
    tip.className = "hint-block";
    tip.style.display = "none";
    tip.style.marginTop = "16px";
    text = document.createElement("span");
    text.id = "pwa-install-text";
    tip.appendChild(text);
    btn = document.createElement("button");
    btn.type = "button";
    btn.id = "pwa-install-btn";
    btn.style.cssText = BTN_STYLE;
    btn.textContent = "立即安装";
    tip.appendChild(btn);
    host.appendChild(tip);
  }

  // 通用指引：一句话 + 「知道了」，每个原因只提示一次
  function guide(msg, dismissKey) {
    if (lsGet(dismissKey) === "1") { return false; }
    if (text) { text.textContent = msg; }
    if (tip && !document.getElementById("pwa-install-guide-close")) {
      var close = document.createElement("button");
      close.type = "button";
      close.id = "pwa-install-guide-close";
      close.textContent = "知道了";
      close.style.cssText = BTN_STYLE.replace("display:none", "display:inline-block");
      close.addEventListener("click", function () { lsSet(dismissKey); hide(); });
      tip.appendChild(close);
    }
    show();
    return true;
  }
  function removeGuideClose() {
    var close = document.getElementById("pwa-install-guide-close");
    if (close && close.parentNode) { close.parentNode.removeChild(close); }
  }

  var ua = navigator.userAgent || "";
  var isIOS = /iPhone|iPad|iPod/.test(ua) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  // 应用内浏览器（微信/QQ/企业微信/钉钉/飞书/微博/小红书/UC/夸克/华为小米自带等）不支持安装 PWA
  var isInApp = /MicroMessenger|QQ\/|QQBrowser|Weibo|XiaoHongShu|Quark|UCBrowser|Alipay|DingTalk|Feishu|Lark|baiduboxapp|HuaweiBrowser|MiuiBrowser/i.test(ua);

  if (isInApp) {
    guide("当前是应用内浏览器，装不了桌面版：点右上角 ⋯ → 「在浏览器打开」，再用 Chrome / 系统浏览器安装。", "qc_pwa_inapp_tip_dismissed");
    return;
  }

  // iOS Safari 没有 beforeinstallprompt：给一次性「分享 → 添加到主屏幕」引导
  if (isIOS) {
    guide("iPhone 上点底部分享按钮 → 「添加到主屏幕」，以后就能像 App 一样打开。", "qc_pwa_ios_tip_dismissed");
    return;
  }

  // Android / 桌面 Chrome：拿到浏览器安装事件后，才显示真正的「安装」按钮
  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    deferred = event;
    removeGuideClose();
    if (btn) { btn.style.cssText = BTN_STYLE.replace("display:none", "display:inline-block"); }
    if (text) { text.textContent = "把“记一下”装到手机桌面，打开更快、更像 App。"; }
    show();
  });

  if (btn) {
    btn.addEventListener("click", function () {
      if (!deferred) { return; }
      deferred.prompt();
      var choice = deferred.userChoice;
      if (choice && choice.then) {
        choice.then(function (result) {
          if (result && result.outcome === "accepted") { hide(); } else { deferred = null; }
        });
      }
    });
  }

  window.addEventListener("appinstalled", function () {
    deferred = null;
    hide();
    lsSet("qc_pwa_installed");
  });

  // 兜底：2.5 秒内浏览器没给安装事件 → 直接给手动步骤（Chrome 早就不自动弹窗了，不能让用户"什么也看不到"）
  window.setTimeout(function () {
    if (deferred || isStandalone()) { return; }
    guide("装到桌面：点浏览器右上角 ⋮（或地址栏右侧安装图标）→ 「安装应用 / 添加到主屏幕」。", "qc_pwa_manual_tip_dismissed");
  }, 2500);
})();
