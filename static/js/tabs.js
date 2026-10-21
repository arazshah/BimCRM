// Accessible tabs shared by the landing page (template gallery) and the features page (journey).
// wireTabs(tablist, onSelect): arrow keys / Home / End move between tabs; onSelect(tab) swaps the content.
function wireTabs(list, onSelect) {
  const tabs = [...list.querySelectorAll('[role="tab"]')];
  const select = (tab, focus) => {
    tabs.forEach(t => { const on = t === tab; t.setAttribute("aria-selected", on); t.tabIndex = on ? 0 : -1; });
    onSelect(tab);
    if (focus) tab.focus();
  };
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => select(tab));
    tab.addEventListener("keydown", e => {
      const vertical = getComputedStyle(list).flexDirection === "column";
      const prev = vertical ? "ArrowUp" : "ArrowRight", nextK = vertical ? "ArrowDown" : "ArrowLeft";
      let j = null;
      if (e.key === nextK) j = (i + 1) % tabs.length;
      if (e.key === prev) j = (i - 1 + tabs.length) % tabs.length;
      if (e.key === "Home") j = 0;
      if (e.key === "End") j = tabs.length - 1;
      if (j !== null) { e.preventDefault(); select(tabs[j], true); }
    });
  });
}
document.querySelectorAll("[data-tabs]").forEach(box => {
  wireTabs(box.querySelector('[role="tablist"]'), tab => {
    box.querySelectorAll('[role="tabpanel"]').forEach(p => { p.hidden = p.id !== tab.getAttribute("aria-controls"); });
  });
});
