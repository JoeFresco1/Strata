import { useEffect, useMemo, useRef, useState } from "react";
import Tree from "react-d3-tree";
import { buildTreeFromSnapshot } from "./workspaceSelectors";

function countDescendants(node) {
  return (node.children || []).reduce((total, child) => total + 1 + countDescendants(child), 0);
}

function graphStatusClass(status) {
  if (["kept", "prioritized", "approved", "published", "complete"].includes(status)) return "kept";
  if (["cut", "rejected", "exclude"].includes(status)) return "cut";
  if (["needs_review", "undecided", "draft", "candidate", "generated"].includes(status)) return "pending";
  if (status === "merged") return "merged";
  return "pending";
}

function nodeTabLabel(tab) {
  if (tab === "tree") return "Tree";
  if (tab === "layer0") return "Layer 0";
  if (tab === "layer1") return "Layer 1";
  if (tab === "layer2") return "Layer 2";
  if (tab === "export") return "Export";
  return "Workspace";
}

export default function TreeGraphView({ snapshot, onNavigate }) {
  const wrapperRef = useRef(null);
  const treeData = useMemo(() => buildTreeFromSnapshot(snapshot), [snapshot]);
  const [translate, setTranslate] = useState({ x: 420, y: 80 });
  const [zoom, setZoom] = useState(0.82);
  const [treeKey, setTreeKey] = useState(0);
  const [initialDepth, setInitialDepth] = useState(2);

  function fitToView() {
    const rect = wrapperRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTranslate({ x: rect.width / 2, y: 74 });
    setZoom(rect.width < 760 ? 0.58 : 0.82);
  }

  useEffect(() => {
    fitToView();
  }, [treeData.id]);

  function remountWithDepth(depth) {
    setInitialDepth(depth);
    setTreeKey((current) => current + 1);
    window.requestAnimationFrame(fitToView);
  }

  function renderNode({ nodeDatum, toggleNode }) {
    const childCount = countDescendants(nodeDatum);
    const collapsed = Boolean(nodeDatum.__rd3t?.collapsed);
    const canToggle = childCount > 0;
    return (
      <g>
        <foreignObject width="248" height="126" x="-124" y="-48">
          <div className={`tree-node-card ${graphStatusClass(nodeDatum.status)}`}>
            <div className="tree-node-topline">
              {canToggle ? (
                <button
                  type="button"
                  className="tree-node-toggle"
                  aria-label={`${collapsed ? "Expand" : "Collapse"} ${nodeDatum.name}`}
                  title={`${collapsed ? "Expand" : "Collapse"} ${nodeDatum.name}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    toggleNode();
                  }}
                >
                  {collapsed ? "+" : "-"}
                </button>
              ) : <span className="tree-node-toggle-spacer" aria-hidden="true" />}
              <span className="tree-node-source">{nodeTabLabel(nodeDatum.tab)}</span>
            </div>
            <button
              type="button"
              className="tree-node-body"
              aria-label={`Open ${nodeDatum.name} in ${nodeTabLabel(nodeDatum.tab)}`}
              title={`Open ${nodeDatum.name}`}
              onClick={(event) => {
                event.stopPropagation();
                onNavigate(nodeDatum.tab, nodeDatum.id);
              }}
            >
              <strong>{nodeDatum.name}</strong>
              <span>{nodeDatum.status}</span>
            </button>
            {collapsed && childCount ? <span className="tree-hidden-count">{childCount} hidden</span> : null}
          </div>
        </foreignObject>
      </g>
    );
  }

  return (
    <section className="tree-graph-view" id="workspace-panel-tree" role="tabpanel" aria-label="Tree graph">
      <div className="workspace-toolbar panel">
        <button type="button" className="secondary-button" onClick={() => remountWithDepth(undefined)}>
          Expand all
        </button>
        <button type="button" className="secondary-button" onClick={() => remountWithDepth(0)}>
          Collapse all
        </button>
        <button type="button" className="secondary-button" onClick={() => setZoom((current) => Math.min(1.6, Number((current + 0.12).toFixed(2))))} aria-label="Zoom in" title="Zoom in">
          +
        </button>
        <button type="button" className="secondary-button" onClick={() => setZoom((current) => Math.max(0.35, Number((current - 0.12).toFixed(2))))} aria-label="Zoom out" title="Zoom out">
          -
        </button>
        <button type="button" onClick={fitToView}>Fit to view</button>
      </div>
      <div ref={wrapperRef} className="tree-graph-canvas">
        <Tree
          key={treeKey}
          data={treeData}
          orientation="vertical"
          translate={translate}
          zoom={zoom}
          zoomable
          draggable
          scaleExtent={{ min: 0.35, max: 1.6 }}
          initialDepth={initialDepth}
          nodeSize={{ x: 280, y: 168 }}
          separation={{ siblings: 1.2, nonSiblings: 1.5 }}
          pathFunc="step"
          renderCustomNodeElement={renderNode}
        />
      </div>
    </section>
  );
}
