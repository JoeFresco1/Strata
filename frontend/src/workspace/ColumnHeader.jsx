import { useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export default function ColumnHeader({ label, description, sortKey, activeSortKey, sortDirection = "asc", onSort }) {
  const [tooltipOpen, setTooltipOpen] = useState(false);
  const [tooltipStyle, setTooltipStyle] = useState({});
  const buttonRef = useRef(null);
  const tooltipId = useId();
  const sortable = Boolean(sortKey && onSort);
  const active = sortable && activeSortKey === sortKey;

  useLayoutEffect(() => {
    if (!tooltipOpen || !buttonRef.current) return undefined;
    function positionTooltip() {
      const rect = buttonRef.current.getBoundingClientRect();
      const top = Math.max(8, rect.top - 10);
      const left = Math.min(window.innerWidth - 140, Math.max(140, rect.left + rect.width / 2));
      setTooltipStyle({ top, left });
    }
    positionTooltip();
    window.addEventListener("scroll", positionTooltip, true);
    window.addEventListener("resize", positionTooltip);
    return () => {
      window.removeEventListener("scroll", positionTooltip, true);
      window.removeEventListener("resize", positionTooltip);
    };
  }, [tooltipOpen]);

  return (
    <span className="column-header-help">
      {sortable ? (
        <button
          type="button"
          className={active ? "column-sort-button active" : "column-sort-button"}
          onClick={() => onSort(sortKey)}
          aria-label={`Sort by ${label} ${active && sortDirection === "asc" ? "descending" : "ascending"}`}
        >
          <span>{label}</span>
          <span className="sort-arrows" aria-hidden="true">{active ? (sortDirection === "asc" ? "▲" : "▼") : "↕"}</span>
        </button>
      ) : (
        <span>{label}</span>
      )}
      <button
        ref={buttonRef}
        type="button"
        className="info-tooltip"
        aria-label={`${label}: ${description}`}
        aria-describedby={tooltipOpen ? tooltipId : undefined}
        onBlur={() => setTooltipOpen(false)}
        onFocus={() => setTooltipOpen(true)}
        onMouseEnter={() => setTooltipOpen(true)}
        onMouseLeave={() => setTooltipOpen(false)}
      >
        i
      </button>
      {tooltipOpen ? createPortal(
        <span id={tooltipId} role="tooltip" className="floating-tooltip" style={tooltipStyle}>
          {description}
        </span>,
        document.body,
      ) : null}
    </span>
  );
}
