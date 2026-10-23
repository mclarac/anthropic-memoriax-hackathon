import { expect, test } from "@playwright/test";
import { createTenant, expectNoHorizontalScroll, resetMock, shoot, startSession } from "./helpers";

test.beforeEach(async () => {
  await resetMock();
});

test("shows an honest empty state, then lists the tenant that was created", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Memoria" })).toBeVisible();
  await expect(page.getByText("No tenants yet.")).toBeVisible();
  await expectNoHorizontalScroll(page);
  await shoot(page, "home-empty");

  await createTenant(page, "Northwind Freight");
  const card = page.getByRole("article", { name: "Northwind Freight" });
  await expect(card).toContainText("Yard management software");
  await expect(card).toContainText("Default assets: Deck, Email sequence");
  await expect(page.getByLabel("Company name")).toHaveValue("");
});

test("keeps the tenant after a reload and shows several tenants", async ({ page }) => {
  await page.goto("/");
  await createTenant(page, "Northwind Freight");
  await createTenant(page, "Kestrel Analytics");
  await page.reload();
  await expect(page.getByRole("article")).toHaveCount(2);
  await expectNoHorizontalScroll(page);
  await shoot(page, "home-with-tenants");
});

test("sends only the asset types that are checked", async ({ page }) => {
  await page.goto("/");
  const request = page.waitForRequest((r) => r.url().endsWith("/api/tenants") && r.method() === "POST");
  await page.getByLabel("Company name").fill("Solo Co");
  await page.getByLabel("What you sell").fill("One thing.");
  await page.getByLabel("Deck").uncheck();
  await page.getByLabel("Email sequence").uncheck();
  await page.getByLabel("Whitepaper").check();
  await page.getByLabel("Blog post").check();
  await page.getByRole("button", { name: "Create tenant" }).click();
  const body = (await request).postDataJSON();
  expect(body.default_assets).toEqual(["blog", "whitepaper"]);
  expect(body.approved_claims).toEqual([]);
});

test("uploads a document at tenant and account scope and reports rejected types", async ({ page }) => {
  await page.goto("/");
  await createTenant(page);
  const card = page.getByRole("article", { name: "Northwind Freight" });
  const upload = card.getByRole("form", { name: /Upload a document/ });

  await upload.getByLabel("File").setInputFiles({ name: "positioning.md", mimeType: "text/markdown", buffer: Buffer.from("# Positioning\nWe cut dwell time.") });
  await upload.getByRole("button", { name: "Upload" }).click();
  await expect(upload.getByRole("status")).toContainText("Uploaded positioning.md");
  await expect(card.getByRole("list", { name: "Documents" })).toContainText("positioning.md");
  await expect(card).toContainText("1 document");

  await upload.getByLabel("Scope").selectOption("account");
  await upload.getByLabel("File").setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("call notes") });
  await upload.getByRole("button", { name: "Upload" }).click();
  await expect(upload.getByLabel("Account")).toHaveAttribute("aria-invalid", "true");
  await upload.getByLabel("Account").fill("acme-logistics");
  await upload.getByRole("button", { name: "Upload" }).click();
  await expect(card.getByRole("list", { name: "Documents" })).toContainText("account acme-logistics");

  await upload.getByLabel("File").setInputFiles({ name: "malware.exe", mimeType: "application/octet-stream", buffer: Buffer.from("MZ") });
  await upload.getByRole("button", { name: "Upload" }).click();
  await expect(upload.getByRole("alert")).toContainText("Only PDF, DOCX, MD and TXT");
});

test("asks for a file before uploading", async ({ page }) => {
  await page.goto("/");
  await createTenant(page);
  const upload = page.getByRole("form", { name: /Upload a document/ });
  await upload.getByRole("button", { name: "Upload" }).click();
  await expect(upload.getByRole("alert")).toContainText("Choose a PDF");
});

test("validates account and rep slugs before starting a session", async ({ page }) => {
  await page.goto("/");
  await createTenant(page);
  const card = page.getByRole("article", { name: "Northwind Freight" });
  await card.getByLabel("Account", { exact: true }).fill("Acme Logistics");
  await card.getByLabel("Rep", { exact: true }).fill("");
  await card.getByRole("button", { name: "Start interview" }).click();
  await expect(card.getByLabel("Account", { exact: true })).toHaveAttribute("aria-invalid", "true");
  await expect(card.getByLabel("Rep", { exact: true })).toHaveAttribute("aria-invalid", "true");
  await expect(card.getByText(/Not valid\./).first()).toBeVisible();
  await expect(page).toHaveURL("/");

  await card.getByLabel("Account", { exact: true }).fill("acme-logistics");
  await card.getByLabel("Rep", { exact: true }).fill("sam-rivera");
  await card.getByRole("button", { name: "Start interview" }).click();
  await expect(page).toHaveURL(/\/session\//);
});

test("navigates to the session page when a session starts", async ({ page }) => {
  await page.goto("/");
  await createTenant(page);
  await startSession(page, "Northwind Freight");
  await expect(page.getByRole("heading", { name: "Interview" })).toBeVisible();
});
