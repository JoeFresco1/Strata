import { PROJECT_STAGE_META, TABS } from "./appUtils";

export default function ProjectTabs({ activeTab, currentStage, currentStageContext, currentTabLabel, onTabChange }) {
  function handleProjectTabKeyDown(event, tabId) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const currentIndex = TABS.findIndex((tab) => tab.id === tabId);
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? TABS.length - 1
        : event.key === "ArrowRight"
          ? (currentIndex + 1) % TABS.length
          : (currentIndex - 1 + TABS.length) % TABS.length;
    const nextTab = TABS[nextIndex];
    onTabChange(nextTab.id);
    window.requestAnimationFrame(() => {
      document.getElementById(`tab-${nextTab.id.replaceAll(" ", "-").toLowerCase()}`)?.focus();
    });
  }

  return (
    <>
      <section className="project-stage-strip panel" aria-label="Current project stage">
        <div className="project-stage-copy">
          <span className="project-stage-kicker">{currentStage.kicker}</span>
          <h3>{currentStage.title}</h3>
          <p className="muted">{currentStage.body}</p>
        </div>
        <div className="project-stage-context">
          <strong>{currentTabLabel}</strong>
          <span>{currentStageContext}</span>
        </div>
      </section>
      <div className="tabs" role="tablist" aria-label="Project workspace sections">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-label={tab.label}
            id={`tab-${tab.id.replaceAll(" ", "-").toLowerCase()}`}
            aria-selected={tab.id === activeTab}
            aria-controls={`panel-${tab.id.replaceAll(" ", "-").toLowerCase()}`}
            className={tab.id === activeTab ? "tab active" : "tab"}
            onClick={() => onTabChange(tab.id)}
            onKeyDown={(event) => handleProjectTabKeyDown(event, tab.id)}
          >
            <span className="tab-kicker">{PROJECT_STAGE_META[tab.id]?.kicker || tab.id}</span>
            <strong>{tab.label}</strong>
            <small>{PROJECT_STAGE_META[tab.id]?.short || tab.label}</small>
          </button>
        ))}
      </div>
    </>
  );
}
