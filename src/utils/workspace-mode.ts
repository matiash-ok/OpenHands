import type { BackendKind } from "#/api/backend-registry/types";
import type { WorkspaceMode } from "#/api/conversation-metadata-store";
import { I18nKey } from "#/i18n/declaration";

export const DEFAULT_WORKSPACE_MODE: WorkspaceMode = "local_repo";

const HOST_WORKSPACE_MODES: WorkspaceMode[] = ["local_repo", "new_worktree"];

const DOCKER_WORKSPACE_MODE = "docker_container";
export const STANDARD_CONTAINER_ISOLATION = "standard";

/** Whether the conversation runs in a container of its own. */
export function isDockerWorkspaceMode(
  mode: WorkspaceMode | null | undefined,
): boolean {
  return (
    mode === DOCKER_WORKSPACE_MODE ||
    !!mode?.startsWith(`${DOCKER_WORKSPACE_MODE}:`)
  );
}

/**
 * The isolation a Docker mode asks the server for (`container.isolation`);
 * undefined for the standard container and for host modes, so the request
 * leaves the field out and the server applies its own default.
 */
export function getContainerIsolation(
  mode: WorkspaceMode | null | undefined,
): string | undefined {
  const prefix = `${DOCKER_WORKSPACE_MODE}:`;
  return mode?.startsWith(prefix)
    ? mode.slice(prefix.length) || undefined
    : undefined;
}

function dockerWorkspaceModes(isolations: readonly string[]): WorkspaceMode[] {
  const extra = isolations.filter(
    (name) => name && name !== STANDARD_CONTAINER_ISOLATION,
  );
  return [
    DOCKER_WORKSPACE_MODE,
    ...extra.map((name): WorkspaceMode => `${DOCKER_WORKSPACE_MODE}:${name}`),
  ];
}

/**
 * The modes the launcher offers; Docker only when the server can run it, with
 * one more entry per extra container isolation the server offers.
 * Without a workspace there is no repo to work in or branch, so the only
 * choice left is where the conversation runs.
 */
export function getWorkspaceModeOptions(
  dockerSelectable: boolean,
  hasWorkspace: boolean,
  containerIsolations: readonly string[] = [],
): WorkspaceMode[] {
  const docker = dockerSelectable
    ? dockerWorkspaceModes(containerIsolations)
    : [];
  if (!hasWorkspace) {
    return dockerSelectable ? ["local_repo", ...docker] : [];
  }
  return [...HOST_WORKSPACE_MODES, ...docker];
}

const MODE_BY_DEFAULT_RUNTIME: Record<string, WorkspaceMode> = {
  local: "local_repo",
  worktree: "new_worktree",
  docker: "docker_container",
};

/**
 * The mode the launcher starts on: the Settings → Runtime default
 * (`conversation_settings.default_runtime`), or the last one used on a server
 * whose settings have no such field.
 */
export function getDefaultWorkspaceMode(
  defaultRuntime: unknown,
  lastUsed: WorkspaceMode,
): WorkspaceMode {
  return typeof defaultRuntime === "string" &&
    defaultRuntime in MODE_BY_DEFAULT_RUNTIME
    ? MODE_BY_DEFAULT_RUNTIME[defaultRuntime]
    : lastUsed;
}

export const LAST_LOCAL_WORKSPACE_MODE_STORAGE_KEY =
  "openhands-last-local-workspace-mode";

function isWorkspaceMode(value: string | null): value is WorkspaceMode {
  return (
    value === "local_repo" ||
    value === "new_worktree" ||
    isDockerWorkspaceMode(value as WorkspaceMode | null)
  );
}

export function readStoredLocalWorkspaceMode(): WorkspaceMode {
  if (typeof window === "undefined") return DEFAULT_WORKSPACE_MODE;

  try {
    const stored = window.localStorage.getItem(
      LAST_LOCAL_WORKSPACE_MODE_STORAGE_KEY,
    );
    return isWorkspaceMode(stored) ? stored : DEFAULT_WORKSPACE_MODE;
  } catch {
    return DEFAULT_WORKSPACE_MODE;
  }
}

export function writeStoredLocalWorkspaceMode(mode: WorkspaceMode): void {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(LAST_LOCAL_WORKSPACE_MODE_STORAGE_KEY, mode);
  } catch {
    // Ignore storage failures; the selector still works for this render.
  }
}

export function getWorkspaceModeI18nKey(
  mode: WorkspaceMode,
  backendKind: BackendKind,
): I18nKey {
  if (mode === "new_worktree") {
    return I18nKey.COMMON$WORKSPACE_MODE_NEW_WORKTREE;
  }
  if (isDockerWorkspaceMode(mode)) {
    const isolation = getContainerIsolation(mode);
    if (isolation === "sysbox") {
      return I18nKey.COMMON$WORKSPACE_MODE_DOCKER_SYSBOX;
    }
    if (isolation === "vm") {
      return I18nKey.COMMON$WORKSPACE_MODE_DOCKER_VM;
    }
    return I18nKey.COMMON$WORKSPACE_MODE_DOCKER_CONTAINER;
  }
  return backendKind === "cloud"
    ? I18nKey.COMMON$WORKSPACE_MODE_CLOUD_REPO
    : I18nKey.COMMON$WORKSPACE_MODE_LOCAL_REPO;
}

/**
 * The launcher's label for a mode. An isolation the UI has no name for shows
 * the server's own name next to "Docker", so it stays distinguishable.
 */
export function getWorkspaceModeLabel(
  mode: WorkspaceMode,
  backendKind: BackendKind,
  t: (key: I18nKey) => string,
): string {
  const label = t(getWorkspaceModeI18nKey(mode, backendKind));
  const isolation = getContainerIsolation(mode);
  return isolation && isolation !== "sysbox" && isolation !== "vm"
    ? `${label} (${isolation})`
    : label;
}
