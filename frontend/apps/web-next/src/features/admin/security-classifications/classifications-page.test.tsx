// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { openMenuOnRelease } from "@/test/menus";
import { renderInApp } from "@/test/render";

const post = vi.hoisted(() => vi.fn());
const put = vi.hoisted(() => vi.fn());
const state = vi.hoisted(() => ({ defaultLevel: null as string | null }));
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  warning: vi.fn()
}));
vi.mock("@/lib/toast", () => ({ toast }));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    POST: post,
    PUT: put,
    GET: () =>
      Promise.resolve({
        data: {
          security_enabled: true,
          default_user_security_classification_id: state.defaultLevel,
          security_classifications: [
            { id: "c1", name: "Klass 1 · Öppen", description: null, security_level: 1 },
            { id: "c2", name: "Klass 2 · Intern", description: null, security_level: 2 }
          ]
        },
        response: new Response("{}")
      })
  }
}));

import { SecurityClassificationsPage } from "./classifications-page";

afterEach(() => {
  cleanup();
  post.mockReset();
  put.mockReset();
  toast.error.mockReset();
  state.defaultLevel = null;
});

async function chooseDefaultLevel(name: string) {
  fireEvent.click(await screen.findByRole("combobox", { name: "Standardnivå för användare" }));
  fireEvent.click(await screen.findByRole("option", { name }));
  return screen.findByRole("alertdialog", { name: "Ändra standardnivå" });
}

describe("SecurityClassificationsPage", () => {
  it("names each classification's menu after the classification", async () => {
    renderInApp(<SecurityClassificationsPage />);

    expect(
      await screen.findByRole("button", { name: "Fler åtgärder för Klass 2 · Intern" })
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fler åtgärder för Klass 1 · Öppen" })).toBeTruthy();
  });

  it("opens a classification's menu on release, not on press (2.5.2)", async () => {
    renderInApp(<SecurityClassificationsPage />);
    const menu = await openMenuOnRelease(
      await screen.findByRole("button", { name: "Fler åtgärder för Klass 2 · Intern" })
    );

    // The highest classification cannot move up; deleting it asks first.
    expect(
      within(menu).getByRole("menuitem", { name: "Flytta upp" }).getAttribute("aria-disabled")
    ).toBe("true");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Ta bort" }));
    expect(
      await screen.findByRole("alertdialog", { name: "Ta bort säkerhetsklassificering" })
    ).toBeTruthy();
  });

  it("names the create button short enough to stay one line on a 320 px phone", async () => {
    // "Skapa en ny säkerhetsklassificering" wrapped to two lines and filled the card at
    // 320 px while it sat at the end at 390; the short name fits both, like "Ny prompt".
    renderInApp(<SecurityClassificationsPage />);
    expect(await screen.findByRole("button", { name: "Ny säkerhetsklassificering" })).toBeTruthy();
  });

  it("keeps focus on a busy Inaktivera and switches off once", async () => {
    post.mockReturnValue(new Promise(() => {}));
    renderInApp(<SecurityClassificationsPage />);
    fireEvent.click(await screen.findByRole("switch", { name: /Aktiverad/ }));
    const dialog = await screen.findByRole("alertdialog", {
      name: "Inaktivera säkerhetsklassificeringar"
    });
    const disable = within(dialog).getByRole("button", { name: "Inaktivera" });
    disable.focus();

    fireEvent.click(disable);

    await waitFor(() => expect(disable.getAttribute("aria-busy")).toBe("true"));
    expect(disable.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(disable);
    fireEvent.click(disable);
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("keeps the switch enabled and the confirmation open while the change saves", async () => {
    post.mockReturnValue(new Promise(() => {}));
    renderInApp(<SecurityClassificationsPage />);
    const toggle = await screen.findByRole("switch", { name: /Aktiverad/ });
    toggle.focus();
    fireEvent.click(toggle);
    const dialog = await screen.findByRole("alertdialog", {
      name: "Inaktivera säkerhetsklassificeringar"
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Inaktivera" }));
    await waitFor(() => expect(toggle.getAttribute("aria-busy")).toBe("true"));

    // Escape cannot close it while it saves, and a second press is ignored.
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("alertdialog")).toBe(dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: "Inaktivera" }));
    expect(toggle.hasAttribute("disabled")).toBe(false);
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("shows the organisation's default level", async () => {
    state.defaultLevel = "c2";
    renderInApp(<SecurityClassificationsPage />);

    const select = await screen.findByRole("combobox", { name: "Standardnivå för användare" });
    expect(select.textContent).toContain("Klass 2 · Intern");
  });

  it("saves a chosen default level once it is confirmed", async () => {
    put.mockResolvedValue({ data: {}, response: new Response("{}") });
    renderInApp(<SecurityClassificationsPage />);

    const dialog = await chooseDefaultLevel("Klass 2 · Intern");
    expect(put).not.toHaveBeenCalled();
    expect(dialog.textContent).toContain("Klass 2 · Intern");
    fireEvent.click(within(dialog).getByRole("button", { name: "Bekräfta" }));

    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/v1/security-classifications/default-user-level/", {
        body: { security_classification: { id: "c2" } }
      })
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("clears the default level", async () => {
    state.defaultLevel = "c2";
    put.mockResolvedValue({ data: {}, response: new Response("{}") });
    renderInApp(<SecurityClassificationsPage />);

    const dialog = await chooseDefaultLevel("Ingen standardnivå");
    fireEvent.click(within(dialog).getByRole("button", { name: "Bekräfta" }));

    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/v1/security-classifications/default-user-level/", {
        body: { security_classification: null }
      })
    );
  });

  it("says why a default level could not be saved", async () => {
    put.mockResolvedValue({
      error: { message: "No model meets the level" },
      response: new Response("{}", { status: 400 })
    });
    renderInApp(<SecurityClassificationsPage />);

    const dialog = await chooseDefaultLevel("Klass 2 · Intern");
    fireEvent.click(within(dialog).getByRole("button", { name: "Bekräfta" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.getByRole("alertdialog")).toBe(dialog);
  });
});
