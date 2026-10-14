// quick-capture PWA 安装引导（2026-10-14 v2: 增加"拿不到浏览器安装事件"时的兜底指引）
(function () {
  "use strict";

  // 诊断模式（临时排查用）：URL 带 ?diag=1 → 页面顶部显示关键判据。定位真机"没有安装入口"后可删。
  try {
    if (/[?&]diag=1/.test(window.location.search)) {
      var dLines = [];
      var box = document.createElement("pre");
      box.style.cssText = "position:fixed;left:0;right:0;top:0;z-index:2147483647;margin:0;padding:8px;" +
        "background:#000;color:#0f0;font:12px/1.5 monospace;white-space:pre-wrap;max-height:60vh;overflow:auto";
      var paint = function () { box.textContent = dLines.join("\n"); };
      dLines.push("diag qc-pwa " + new Date().toISOString());
      dLines.push("protocol=" + location.protocol + " isSecureContext=" + window.isSecureContext);
      dLines.push("standalone=" + isStandalone());
      dLines.push("SW supported=" + ("serviceWorker" in navigator) + " SW controller=" + !!(navigator.serviceWorker && navigator.serviceWorker.controller));
      dLines.push("beforeinstallprompt=NOT-FIRED-YET");
      dLines.push("UA=" + navigator.userAgent);
      (document.body || document.documentElement).appendChild(box);
      paint();
      window.addEventListener("beforeinstallprompt", function () {
        dLines[4] = "beforeinstallprompt=FIRED(浏览器认为可安装)";
        paint();
      });
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
