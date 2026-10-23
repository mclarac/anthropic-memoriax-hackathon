import { expect, test, type Page } from "@playwright/test";
import {
  answer,
  answerUntilComplete,
  configureMock,
  createTenant,
  expectNoHorizontalScroll,
  releaseMock,
  resetMock,
  shoot,
  startSession,
} from "./helpers";

async function openSession(page: Page, account = "acme-logistics") {
  await page.goto("/");
  await page.getByRole("heading", { name: "Memoria" }).waitFor();
  if ((await page.getByRole("article").count()) === 0) await createTenant(page);
  await startSession(page, "Northwind Freight", account);
  await expect(page.getByTestId("phase")).toHaveText("Interview");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
}

test.beforeEach(async () => {
  await resetMock();
});

test("Memoria opens the interview and the rep answers by typing", async ({ page }) => {
  await openSession(page);
  const log = page.getByRole("log", { name: "Conversation" });
  await expect(log).toContainText("Hi, I'm Memoria, your sales engineer.");
  await expect(log).toContainText("What is the next meeting");
  await expect(log).toHaveAttribute("aria-live", "polite");

  await answer(page, "Thursday at 10 with the VP of Operations");
  await expect(log.locator('[data-speaker="rep"]')).toHaveText(/Thursday at 10/);
  await expect(log).toContainText("What would a win look like");
  await expect(page.getByLabel("Type instead")).toHaveValue("");
});

test("does not send an empty or whitespace-only answer", async ({ page }) => {
  await openSession(page);
  const send = page.getByRole("button", { name: "Send", exact: true });
  await expect(send).toBeDisabled();
  await page.getByLabel("Type instead").fill("   ");
  await expect(send).toBeDisabled();
});

test("slots fill as answers arrive and show their evidence on expand", async ({ page }) => {
  await openSession(page);
  await expect(page.getByText("0 of 16 answered")).toBeVisible();
  const groups = ["Deal", "Pain", "Decision", "Risk", "Campaign"];
  for (const group of groups) await expect(page.getByRole("heading", { name: group, level: 3 })).toBeVisible();
  await expect(page.locator("[data-slot]")).toHaveCount(16);

  await answer(page, "Thursday at 10 with the VP of Operations");
  await expect(page.getByText("1 of 16 answered")).toBeVisible();
  const slot = page.locator('[data-slot="next_meeting"]');
  await expect(slot).toContainText("confirmed");
  await expect(slot).toContainText("Thursday at 10 with the VP of Operations");

  await slot.getByText("next_meeting").click();
  await expect(slot.getByText("Evidence:")).toBeVisible();

  await answer(page, "A signed 12-month pilot at two sites");
  await expect(page.getByText("2 of 16 answered")).toBeVisible();
  await expect(page.locator('[data-slot="win_condition"]')).toContainText("confirmed");
  await expect(page.locator('[data-slot="pain"]')).toContainText("open");
  await shoot(page, "slot-board-partial");
});

test("screenshot: interview mid-conversation", async ({ page }) => {
  await openSession(page);
  await answer(page, "Thursday at 10 with the VP of Operations");
  await expect(page.getByText("1 of 16 answered")).toBeVisible();
  await answer(page, "A signed 12-month pilot at two sites");
  await answer(page, "Trucks wait too long in the yard before they can unload");
  await expect(page.getByText("3 of 16 answered")).toBeVisible();
  await expect(page.locator('[data-speaker="memoria"]:not([data-streaming])')).toHaveCount(4);
  await expectNoHorizontalScroll(page);
  await shoot(page, "interview-mid-conversation");
});

test("the Build campaign button is offered from the start and ends the interview early", async ({ page }) => {
  await openSession(page);
  await answer(page, "Thursday at 10 with the VP of Operations");
  await expect(page.getByText("1 of 16 answered")).toBeVisible();
  await page.getByRole("button", { name: "Build campaign" }).click();
  await expect(page.getByTestId("phase")).toHaveText("Complete");
  await expect(page.getByText("You ended the interview.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Build campaign" })).toHaveCount(0);
  await expect(page.getByLabel("Type instead")).toBeDisabled();
});

test("six answers complete the interview, then the build runs to completion", async ({ page }) => {
  await configureMock({ hold_at: "verifier" });
  await openSession(page);
  await answerUntilComplete(page);
  await expect(page.getByText("6 of 16 answered")).toBeVisible();
  await expect(page.getByText("Every slot is answered. Ready to build.")).toBeVisible();

  await page.getByRole("button", { name: "Build campaign" }).click();
  await expect(page.getByTestId("phase")).toHaveText("Building");

  const stages = page.locator("[data-stage]");
  await expect(stages).toHaveCount(9);
  await expect(page.locator('[data-stage="verifier"]')).toHaveAttribute("data-status", "running");
  await expect(page.locator('[data-stage="assets"]')).toHaveAttribute("data-status", "done");
  await expect(page.locator('[data-stage="memory_writer"]')).toHaveAttribute("data-status", "pending");
  await expect(page.locator('[data-stage="deal_brief"]')).toContainText("1.2 s");
  await expect(page.getByText("Assets appear here as the verifier approves them.")).toBeVisible();
  await shoot(page, "build-in-progress");

  await releaseMock();
  await expect(page.getByTestId("phase")).toHaveText("Complete");
  const order = await stages.evaluateAll((els) => els.map((el) => el.getAttribute("data-stage")));
  expect(order).toEqual(["deal_brief", "retrieval", "research", "personas", "strategy", "assets", "verifier", "memory_writer", "strategy_answer"]);
  await expect(stages.locator("xpath=self::*[@data-status='done']")).toHaveCount(9);

  await expect(page.locator("[data-asset]")).toHaveCount(5);
  const deck = page.locator('[data-asset="deck"]');
  await expect(deck).toContainText("Northwind renewal deck");
  await expect(deck).toContainText("Verified");
  await expect(deck.getByRole("link", { name: /PowerPoint/ })).toHaveAttribute("href", /\/api\/files\/.+\/deck\.pptx$/);
  const blog = page.locator('[data-asset="blog"]');
  await expect(blog).toContainText("Needs human review");
  await expect(blog).toContainText("2 placeholders to fill");
  await expect(blog).toContainText("[CUSTOMER QUOTE]");
  await expect(blog.getByRole("link")).toHaveCount(2);
  await shoot(page, "build-complete-assets");

  await expect(page.getByRole("heading", { name: "Lead with dwell time, not features" })).toBeVisible();
  await expect(page.getByText("slow yard turnaround", { exact: false })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What Memoria will remember" })).toBeVisible();
  const change = page.locator('[data-change="added"]');
  await expect(change).toContainText("/accounts/acme-logistics/objections.md");
  await change.getByText("/accounts/acme-logistics/objections.md").click();
  await expect(change.getByRole("group")).toContainText("Pricing was raised");
  await expectNoHorizontalScroll(page);
  await page.getByRole("heading", { name: "Strategy answer" }).scrollIntoViewIfNeeded();
  await shoot(page, "strategy-and-memory-diff");
});

test("downloads link to files the server can serve", async ({ page }) => {
  await openSession(page);
  await page.getByRole("button", { name: "Build campaign" }).click();
  await expect(page.getByTestId("phase")).toHaveText("Complete");
  const href = await page.locator('[data-asset="blog"]').getByRole("link", { name: /Markdown/ }).getAttribute("href");
  const response = await page.request.get(href as string);
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("text/markdown");
});

test("a second session for the same account shows a modified memory file with a line diff", async ({ page }) => {
  await openSession(page);
  await page.getByRole("button", { name: "Build campaign" }).click();
  await expect(page.locator('[data-change="added"]')).toBeVisible();

  await page.goto("/");
  await startSession(page, "Northwind Freight", "acme-logistics", "jo-park");
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Build campaign" }).click();
  const change = page.locator('[data-change="modified"]');
  await expect(change).toBeVisible();
  await change.getByText("objections.md").click();
  const diff = change.getByRole("group");
  await expect(diff).toContainText("Pricing was raised on sam-rivera");
  await expect(diff).toContainText("Pricing was raised on jo-park");
  const lines = await diff.locator("div").allTextContents();
  expect(lines.some((l) => l.startsWith("+"))).toBe(true);
  expect(lines.some((l) => l.startsWith(" "))).toBe(true);
});

test("a failed build keeps what was produced and says so", async ({ page }) => {
  await configureMock({ fail_at: "verifier" });
  await openSession(page);
  await page.getByRole("button", { name: "Build campaign" }).click();
  await expect(page.getByTestId("phase")).toHaveText("Failed");
  await expect(page.getByRole("alert").filter({ hasText: "The build stopped" })).toContainText("The verifier stage failed");
  await expect(page.locator('[data-stage="verifier"]')).toHaveAttribute("data-status", "failed");
  await expect(page.locator('[data-stage="deal_brief"]')).toHaveAttribute("data-status", "done");
  await expect(page.getByText("No assets were produced.")).toBeVisible();
});

test("reloading mid-build restores the session state", async ({ page }) => {
  await configureMock({ hold_at: "verifier" });
  await openSession(page);
  await page.getByRole("button", { name: "Build campaign" }).click();
  await expect(page.locator('[data-stage="verifier"]')).toHaveAttribute("data-status", "running");
  await page.reload();
  await expect(page.locator('[data-stage="deal_brief"]')).toHaveAttribute("data-status", "done");
  await expect(page.locator('[data-stage="verifier"]')).toHaveAttribute("data-status", "running");
  await expect(page.getByTestId("phase")).toHaveText("Building");
  await releaseMock();
});

test("an unknown session explains itself", async ({ page }) => {
  await page.goto("/session/does-not-exist");
  await expect(page.getByRole("alert").filter({ hasText: "could not be loaded" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to tenants" })).toBeVisible();
});

test("speech is requested sentence by sentence in order, and mute skips synthesis", async ({ page }) => {
  const spoken: string[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/api/tts")) spoken.push(request.postDataJSON().text);
  });
  await configureMock({ tts_seconds: 1.2 });
  await openSession(page);
  await expect.poll(() => spoken.length).toBe(2);
  expect(spoken).toEqual(["Hi, I'm Memoria, your sales engineer.", "What is the next meeting with this account, and when is it?"]);
  await expect(page.getByText("Memoria is speaking")).toBeVisible();

  const mute = page.getByRole("button", { name: "Mute Memoria" });
  await mute.click();
  await expect(page.getByRole("button", { name: "Unmute Memoria" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("Memoria is speaking")).toBeHidden();

  await answer(page, "Thursday at 10 with the VP of Operations");
  await expect(page.getByRole("log", { name: "Conversation" })).toContainText("What would a win look like");
  expect(spoken).toHaveLength(2);

  await page.getByRole("button", { name: "Unmute Memoria" }).click();
  await answer(page, "A signed 12-month pilot at two sites");
  await expect.poll(() => spoken.length).toBeGreaterThan(2);
});

test("keyboard alone can answer, expand a slot, and start the build", async ({ page }) => {
  await openSession(page);
  await expect(page.getByRole("log", { name: "Conversation" })).toContainText("What is the next meeting");

  await page.getByLabel("Type instead").focus();
  await page.keyboard.type("Thursday at 10 with the VP of Operations");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Send", exact: true })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByText("1 of 16 answered")).toBeVisible();

  await page.getByLabel("Type instead").focus();
  await page.keyboard.type("A signed pilot");
  await page.keyboard.press("Enter");
  await expect(page.getByText("2 of 16 answered")).toBeVisible();

  // With nothing typed, Send is disabled and Tab moves straight on to the build button.
  await page.getByLabel("Type instead").focus();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Build campaign" })).toBeFocused();

  await page.locator('[data-slot="next_meeting"] summary').focus();
  await page.keyboard.press("Enter");
  await expect(page.locator('[data-slot="next_meeting"]')).toHaveAttribute("open", "");

  await page.getByRole("button", { name: "Build campaign" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("phase")).toHaveText("Complete");

  await page.locator('[data-change="added"] summary').focus();
  await page.keyboard.press("Enter");
  await expect(page.locator('[data-change="added"]')).toHaveAttribute("open", "");
});

test("focus is always visible on interactive controls", async ({ page }) => {
  await openSession(page);
  await page.getByLabel("Type instead").focus();
  const outline = await page.getByLabel("Type instead").evaluate((el) => getComputedStyle(el).outlineStyle);
  expect(outline).not.toBe("none");
  await page.getByRole("button", { name: "Mute Memoria" }).focus();
  const width = await page.getByRole("button", { name: "Mute Memoria" }).evaluate((el) => getComputedStyle(el).outlineWidth);
  expect(parseFloat(width)).toBeGreaterThanOrEqual(2);
});

test.describe("voice input availability", () => {
  test("without WebGPU it says so and defaults to typing", async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(Navigator.prototype, "gpu", { value: undefined, configurable: true });
    });
    await openSession(page);
    await expect(page.getByRole("note")).toContainText("Voice input needs WebGPU");
    await expect(page.getByRole("button", { name: "Enable voice input" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Hold to talk/ })).toHaveCount(0);
    await answer(page, "Thursday at 10 with the VP of Operations");
    await expect(page.getByText("1 of 16 answered")).toBeVisible();
  });

  test("with WebGPU it offers to download the speech model first", async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(Navigator.prototype, "gpu", { value: {}, configurable: true });
    });
    await openSession(page);
    await expect(page.getByRole("button", { name: "Enable voice input" })).toBeVisible();
    await expect(page.getByText("Voice input needs WebGPU")).toHaveCount(0);
  });
});
