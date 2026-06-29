import PromptCatalogEditor from "./PromptCatalogEditor";
import { AppSettingsModal } from "./ModelSettingsPanel";
import { CreateProjectModal, EditProjectModal, GuideModal, ImportProjectModal, ModalFrame } from "./ProjectShell";

export default function AppModals({
  appSettings,
  config,
  editProjectIdea,
  editProjectName,
  editingProject,
  handleCreateProject,
  handleEditProject,
  handleImportProject,
  handleSaveModelSettings,
  importArchivePath,
  modelSettingsSaveState,
  newProjectIdea,
  newProjectName,
  setAppSettings,
  setEditProjectIdea,
  setEditProjectName,
  setEditingProject,
  setImportArchivePath,
  setNewProjectIdea,
  setNewProjectName,
  setShowCreateProject,
  setShowGuide,
  setShowImportProject,
  setShowPrompts,
  setShowSettings,
  showCreateProject,
  showGuide,
  showImportProject,
  showPrompts,
  showSettings,
}) {
  return (
    <>
      {showCreateProject ? (
        <CreateProjectModal
          name={newProjectName}
          idea={newProjectIdea}
          onNameChange={setNewProjectName}
          onIdeaChange={setNewProjectIdea}
          onSubmit={handleCreateProject}
          onClose={() => setShowCreateProject(false)}
        />
      ) : null}
      {editingProject ? (
        <EditProjectModal
          project={editingProject}
          name={editProjectName}
          idea={editProjectIdea}
          onNameChange={setEditProjectName}
          onIdeaChange={setEditProjectIdea}
          onSubmit={handleEditProject}
          onClose={() => setEditingProject(null)}
        />
      ) : null}
      {showImportProject ? (
        <ImportProjectModal
          archivePath={importArchivePath}
          onArchivePathChange={setImportArchivePath}
          onSubmit={handleImportProject}
          onClose={() => setShowImportProject(false)}
        />
      ) : null}
      {showSettings ? (
        <AppSettingsModal
          settings={appSettings}
          config={config}
          saveState={modelSettingsSaveState}
          onChange={setAppSettings}
          onSave={handleSaveModelSettings}
          onClose={() => setShowSettings(false)}
        />
      ) : null}
      {showPrompts ? (
        <ModalFrame
          title="System Prompts"
          subtitle="Edit the shared prompt templates here. These edits apply to new projects created after you save."
          onClose={() => setShowPrompts(false)}
          className="prompts-modal"
        >
          <PromptCatalogEditor
            settings={appSettings}
            onChange={setAppSettings}
            onSave={handleSaveModelSettings}
            saveState={modelSettingsSaveState}
          />
        </ModalFrame>
      ) : null}
      {showGuide ? <GuideModal onClose={() => setShowGuide(false)} /> : null}
    </>
  );
}
