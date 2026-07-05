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
  function closeAllModals() {
    setShowCreateProject(false);
    setEditingProject(null);
    setShowImportProject(false);
    setShowSettings(false);
    setShowPrompts(false);
    setShowGuide(false);
  }

  if (showCreateProject) {
    return (
      <CreateProjectModal
        name={newProjectName}
        idea={newProjectIdea}
        onNameChange={setNewProjectName}
        onIdeaChange={setNewProjectIdea}
        onSubmit={handleCreateProject}
        onClose={closeAllModals}
      />
    );
  }

  if (editingProject) {
    return (
      <EditProjectModal
        project={editingProject}
        name={editProjectName}
        idea={editProjectIdea}
        onNameChange={setEditProjectName}
        onIdeaChange={setEditProjectIdea}
        onSubmit={handleEditProject}
        onClose={closeAllModals}
      />
    );
  }

  if (showImportProject) {
    return (
      <ImportProjectModal
        archivePath={importArchivePath}
        onArchivePathChange={setImportArchivePath}
        onSubmit={handleImportProject}
        onClose={closeAllModals}
      />
    );
  }

  if (showSettings) {
    return (
      <AppSettingsModal
        settings={appSettings}
        config={config}
        saveState={modelSettingsSaveState}
        onChange={setAppSettings}
        onSave={handleSaveModelSettings}
        onClose={closeAllModals}
      />
    );
  }

  if (showPrompts) {
    return (
      <ModalFrame
        title="System Prompts"
        subtitle="Review the shared prompt catalog by layer, then save only when the reusable defaults for future projects should change."
        onClose={closeAllModals}
        className="prompts-modal"
      >
        <PromptCatalogEditor
          settings={appSettings}
          onChange={setAppSettings}
          onSave={handleSaveModelSettings}
          saveState={modelSettingsSaveState}
        />
      </ModalFrame>
    );
  }

  if (showGuide) {
    return <GuideModal onClose={closeAllModals} />;
  }

  return null;
}
