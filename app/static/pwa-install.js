(function () {
  "use strict";
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

  if (isStandalone()) { return; } // 已经装到桌面，不再提示

  // 页面若没有安装条占位，就在主容器末尾自动注入一个（保证任何页面都能装）
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

  // Android / 桌面 Chrome：拿到浏览器安装事件后，才显示真正的「安装」按钮
  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    deferred = event;
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
    try { localStorage.setItem("qc_pwa_installed", "1"); } catch (err) {}
  });

  // iOS Safari 没有 beforeinstallprompt：给一次性「分享 → 添加到主屏幕」引导
  var ua = navigator.userAgent || "";
  var isIOS = /iPhone|iPad|iPod/.test(ua) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  if (!isIOS) { return; }

  var dismissed = false;
  try { dismissed = localStorage.getItem("qc_pwa_ios_tip_dismissed") === "1"; } catch (err) {}
  if (dismissed) { return; }

  if (text) { text.textContent = "iPhone 上点底部分享按钮 → “添加到主屏幕”，以后就能像 App 一样打开。"; }
  var close = document.createElement("button");
  close.type = "button";
  close.textContent = "知道了";
  close.style.cssText = BTN_STYLE.replace("display:none", "display:inline-block");
  close.addEventListener("click", function () {
    try { localStorage.setItem("qc_pwa_ios_tip_dismissed", "1"); } catch (err) {}
    hide();
  });
  tip.appendChild(close);
  show();
})();
