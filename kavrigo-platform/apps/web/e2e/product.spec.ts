import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

async function openWorkspace(page: Page) {
  const slug = `browser-${crypto.randomUUID().slice(0, 12)}`;
  await page.goto("/");
  await expect(
    page.getByText("PAPER · SIMULATED", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Development identity").fill(slug);
  await page.getByRole("button", { name: "Open workspace" }).click();
  await page.getByLabel("Name", { exact: true }).fill("Browser verification");
  await page.getByLabel("Unique slug").fill(slug);
  await page
    .getByRole("button", { name: "Create workspace", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Your agents. Under control." }),
  ).toBeVisible();
  return slug;
}

test("real API: draft, immutable version, workspace isolation, logout", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const slug = await openWorkspace(page);
  await page.screenshot({
    path: "test-results/overview-dark.png",
    fullPage: true,
  });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("link", { name: /^Studio/ }).click();
  await page.getByRole("button", { name: "Create agent" }).click();
  await page.getByLabel("Agent name").fill("browser-agent");
  await page.getByLabel("Purpose").fill("Browser verification paper draft");
  await page.getByLabel("Risk policy reference").fill(`rp_${"0".repeat(32)}`);
  await page
    .getByLabel("Execution policy reference")
    .fill(`ep_${"0".repeat(32)}`);
  await page.getByRole("button", { name: "Save paper draft" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: /VERSION 1.*browser-agent/ }).click();
  const editor = page.getByLabel("Structured specification · JSON");
  const first = JSON.parse(await editor.inputValue());
  await editor.fill(
    JSON.stringify(
      { ...first, description: "Updated immutable draft" },
      null,
      2,
    ),
  );
  await page
    .getByLabel("Reason for this version")
    .fill("Inspect immutable editing");
  await page.getByRole("button", { name: "Save new draft version" }).click();
  await expect(page.getByLabel("Inspect version")).toHaveValue("2");
  await page.getByLabel("Inspect version").selectOption("1");
  await expect(editor).toHaveValue(/Browser verification paper draft/);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Use light theme" }).click();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({
    path: "test-results/studio-light.png",
    fullPage: true,
  });
  await page.getByLabel("WORKSPACE", { exact: true }).selectOption("");
  await page.getByLabel("Name", { exact: true }).fill("Second workspace");
  await page.getByLabel("Unique slug").fill(`${slug}-second`);
  await page
    .getByRole("button", { name: "Create workspace", exact: true })
    .click();
  await expect(
    page.getByText("Your first agent starts with a specification"),
  ).toBeVisible();
  await expect(page.getByText("browser-agent", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByLabel("Development identity")).toBeVisible();
  expect(
    await page.evaluate(() => ({
      local: localStorage.length,
      session: sessionStorage.length,
      cookie: document.cookie,
    })),
  ).toEqual({ local: 0, session: 0, cookie: "" });
  expect(errors).toEqual([]);
});

test("mobile, keyboard navigation, and failure closes the paper gate", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openWorkspace(page);
  await page.getByRole("button", { name: "Search navigation" }).click();
  await page.getByLabel("Search pages").fill("Risk");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Risk", exact: true })
    .click();
  await expect(page).toHaveURL(/risk$/);
  await expect(page.locator("#main")).toBeFocused();
  await expect(
    page.getByRole("heading", { name: "Execution gates" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({
    path: "test-results/risk-mobile.png",
    fullPage: true,
  });
  await page.route("**/api/control/v1/platform/mode", (route) =>
    route.fulfill({ status: 503, json: { message: "Test outage" } }),
  );
  await expect(page.getByText("MODE UNVERIFIED", { exact: true })).toBeVisible({
    timeout: 22_000,
  });
  await page.getByRole("link", { name: /^Studio/ }).click();
  await page.getByRole("button", { name: "Create agent" }).click();
  await expect(
    page.getByRole("button", { name: "Save paper draft" }),
  ).toBeDisabled();
  await page.keyboard.press("Escape");
});

test("proxy rejects cross-origin writes and execution paths", async ({
  request,
}) => {
  const response = await request.post("/api/control/v1/workspaces", {
    data: { name: "x", slug: "xxx" },
    headers: { Origin: "https://untrusted.example" },
  });
  expect(response.status()).toBe(403);
  expect(
    (
      await request.post(
        `/api/control/v1/workspaces/ws_${"0".repeat(32)}/runs`,
        { data: {} },
      )
    ).status(),
  ).toBe(404);
});
