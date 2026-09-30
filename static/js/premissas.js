// Abre/fecha o balão de premissas (comportamento puramente visual).
(() => {
  const helper = document.querySelector(".premissas-helper");
  if (!helper) return;
  const setOpen = (open) => {
    helper.classList.toggle("is-open", open);
    helper.setAttribute("aria-expanded", String(open));
  };
  helper.addEventListener("click", (event) => {
    event.stopPropagation();
    setOpen(!helper.classList.contains("is-open"));
  });
  helper.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setOpen(!helper.classList.contains("is-open"));
    } else if (event.key === "Escape") {
      setOpen(false);
      helper.blur();
    }
  });
  document.addEventListener("click", () => setOpen(false));
})();
