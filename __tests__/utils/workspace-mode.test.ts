import { describe, expect, it } from "vitest";
import { I18nKey } from "#/i18n/declaration";
import {
  getContainerIsolation,
  getWorkspaceModeLabel,
  getWorkspaceModeOptions,
  isDockerWorkspaceMode,
} from "#/utils/workspace-mode";

const t = (key: I18nKey) => key;

describe("workspace mode container isolations", () => {
  it("offers plain Docker only when the server lists no extra isolation", () => {
    expect(getWorkspaceModeOptions(true, true)).toEqual([
      "local_repo",
      "new_worktree",
      "docker_container",
    ]);
    expect(getWorkspaceModeOptions(true, true, ["standard"])).toEqual([
      "local_repo",
      "new_worktree",
      "docker_container",
    ]);
  });

  it("adds one Docker entry per extra isolation the server offers", () => {
    expect(
      getWorkspaceModeOptions(true, true, ["standard", "sysbox", "vm"]),
    ).toEqual([
      "local_repo",
      "new_worktree",
      "docker_container",
      "docker_container:sysbox",
      "docker_container:vm",
    ]);
    expect(getWorkspaceModeOptions(true, false, ["standard", "vm"])).toEqual([
      "local_repo",
      "docker_container",
      "docker_container:vm",
    ]);
  });

  it("offers no isolation when the server cannot run Docker conversations", () => {
    expect(getWorkspaceModeOptions(false, true, ["standard", "vm"])).toEqual([
      "local_repo",
      "new_worktree",
    ]);
    expect(getWorkspaceModeOptions(false, false, ["standard", "vm"])).toEqual(
      [],
    );
  });

  it("treats every isolation as a Docker mode", () => {
    expect(isDockerWorkspaceMode("docker_container")).toBe(true);
    expect(isDockerWorkspaceMode("docker_container:vm")).toBe(true);
    expect(isDockerWorkspaceMode("new_worktree")).toBe(false);
    expect(isDockerWorkspaceMode(null)).toBe(false);
  });

  it("sends an isolation only for the extra ones", () => {
    expect(getContainerIsolation("docker_container")).toBeUndefined();
    expect(getContainerIsolation("local_repo")).toBeUndefined();
    expect(getContainerIsolation("docker_container:sysbox")).toBe("sysbox");
  });

  it("names known isolations and shows the server's name for others", () => {
    expect(getWorkspaceModeLabel("docker_container", "local", t)).toBe(
      I18nKey.COMMON$WORKSPACE_MODE_DOCKER_CONTAINER,
    );
    expect(getWorkspaceModeLabel("docker_container:sysbox", "local", t)).toBe(
      I18nKey.COMMON$WORKSPACE_MODE_DOCKER_SYSBOX,
    );
    expect(getWorkspaceModeLabel("docker_container:vm", "local", t)).toBe(
      I18nKey.COMMON$WORKSPACE_MODE_DOCKER_VM,
    );
    expect(getWorkspaceModeLabel("docker_container:gvisor", "local", t)).toBe(
      `${I18nKey.COMMON$WORKSPACE_MODE_DOCKER_CONTAINER} (gvisor)`,
    );
  });
});
