// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";

const state = vi.hoisted(() => ({ enabled: true, fresh: null as unknown }));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) =>
      path === "/api/v1/admin/users/{username}/"
        ? state.fresh
          ? Promise.resolve({ data: state.fresh, response: new Response("{}") })
          : new Promise(() => {})
        : Promise.resolve({
            data: {
              security_enabled: state.enabled,
              security_classifications: [
                { id: "c1", name: "Öppen", description: null, security_level: 1 },
                { id: "c2", name: "Intern", description: null, security_level: 2 }
              ]
            },
            response: new Response("{}")
          })
  }
}));

import { UserSecurityLevel } from "./user-security-level";
import type { AdminUser } from "./users";

afterEach(() => {
  cleanup();
  state.enabled = true;
  state.fresh = null;
});

function user(effective: AdminUser["effective_security_level"]): AdminUser {
  return {
    id: "u1",
    username: "bo.ek",
    user_groups: [{ id: "g1", name: "Ekonomi" }],
    effective_security_level: effective
  } as unknown as AdminUser;
}

it("names the level and the group it comes from", async () => {
  renderInApp(
    <UserSecurityLevel
      user={user({ security_classification_id: "c2", source: "group", user_group_id: "g1" })}
    />
  );
  expect(await screen.findByText("Intern, från användargruppen Ekonomi")).toBeTruthy();
});

it("says when the level is the organisation's default", async () => {
  renderInApp(
    <UserSecurityLevel
      user={user({ security_classification_id: "c1", source: "default", user_group_id: null })}
    />
  );
  expect(await screen.findByText("Öppen, organisationens standardnivå")).toBeTruthy();
});

it("says when the user has no level", async () => {
  renderInApp(
    <UserSecurityLevel
      user={user({ security_classification_id: null, source: "none", user_group_id: null })}
    />
  );
  expect(await screen.findByText("Ingen säkerhetsnivå")).toBeTruthy();
});

it("shows nothing while classification is disabled", async () => {
  state.enabled = false;
  const { container } = renderInApp(
    <UserSecurityLevel
      user={user({ security_classification_id: "c2", source: "group", user_group_id: "g1" })}
    />
  );
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(container.textContent).toBe("");
});

it("follows the user's groups as they change, not the list's snapshot", async () => {
  state.fresh = user({ security_classification_id: "c2", source: "group", user_group_id: "g1" });
  renderInApp(
    <UserSecurityLevel
      user={{
        ...user({ security_classification_id: "c1", source: "default", user_group_id: null }),
        user_groups: [],
        username: "eva.ek"
      }}
    />
  );
  expect(await screen.findByText("Intern, från användargruppen Ekonomi")).toBeTruthy();
});
