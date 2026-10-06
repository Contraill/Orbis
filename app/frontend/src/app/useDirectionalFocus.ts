import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

const selector = 'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]';

export function useDirectionalFocus(enabled = true) {
  const navigate = useNavigate();
  useEffect(() => {
    if (!enabled) return;
    function keydown(event: KeyboardEvent) {
      if (event.key === "Escape" || event.key === "Backspace" && !(event.target instanceof HTMLInputElement)) {
        if (event.key === "Backspace") event.preventDefault();
        navigate(-1);
        return;
      }
      if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) return;
      const active = document.activeElement;
      if (active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement || active instanceof HTMLSelectElement) return;
      const nodes = Array.from(document.querySelectorAll<HTMLElement>(selector)).filter(node => node.getClientRects().length && getComputedStyle(node).visibility !== "hidden");
      if (!(active instanceof HTMLElement) || !nodes.includes(active)) return;
      const current = active.getBoundingClientRect();
      const cx = current.left + current.width / 2, cy = current.top + current.height / 2;
      const horizontal = event.key === "ArrowLeft" || event.key === "ArrowRight";
      const sign = event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1;
      const candidates = nodes.filter(node => node !== active).map(node => {
        const r = node.getBoundingClientRect();
        const dx = r.left + r.width / 2 - cx, dy = r.top + r.height / 2 - cy;
        const primary = (horizontal ? dx : dy) * sign;
        const secondary = Math.abs(horizontal ? dy : dx);
        return { node, primary, score: primary + secondary * 2.4 };
      }).filter(item => item.primary > 4).sort((a, b) => a.score - b.score);
      if (candidates.length) { event.preventDefault(); candidates[0].node.focus(); candidates[0].node.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" }); }
    }
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [navigate, enabled]);
}
