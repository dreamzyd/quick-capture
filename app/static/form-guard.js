document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".submit-once-form").forEach((form) => {
    form.addEventListener("submit", () => {
      const button = form.querySelector('button[type="submit"]');
      if (!button || button.disabled) return;
      button.dataset.originalText = button.textContent;
      button.disabled = true;
      button.textContent = button.dataset.loadingText || "提交中...";
    });
  });
});
