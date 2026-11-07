import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

const SHOTS = process.env.OFFICE_SHOTS || "/tmp/office-shots";

async function shot(page: Page, name: string) {
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

const NAV = [
  "Executive Office",
  "Agent Directory",
  "Virtual Office",
  "Research Laboratory",
  "Investment Strategies",
  "Portfolio Management",
  "Backtesting",
  "Paper Trading",
  "Agent Communications",
  "Activity & Audit Log",
  "Settings",
];

test("virtual office runs the engine and keeps the approval gate", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Fixture mode is enabled")).toBeVisible();
  await shot(page, "01-executive");
  for (const label of NAV) {
    await page.getByRole("link", { name: label }).click();
    await expect(page.getByRole("heading", { level: 2, name: label })).toBeVisible();
  }

  await page.getByRole("link", { name: "Investment Strategies" }).click();
  await page.getByRole("textbox", { name: "Name" }).fill("e2e-desk");
  await page.getByRole("checkbox", { name: "Earnings Drift" }).check();
  await page.getByRole("button", { name: "Save mandate" }).click();
  await expect(page.getByText("Saved")).toBeVisible();

  await page.getByRole("link", { name: "Research Laboratory" }).click();
  await page.getByRole("textbox", { name: "Title" }).fill("E2E swing");
  await page.getByRole("checkbox", { name: "Deep Value" }).check();
  await page.getByRole("textbox", { name: "Symbols" }).fill("AAPL");
  await expect(page.locator("input[name=as_of]")).not.toHaveValue("");
  await expect(page.locator("select[name=mode]")).toHaveValue("fixture");
  await page.getByRole("button", { name: "Run native analysts" }).click();
  await expect(page.getByRole("link", { name: /E2E swing/ })).toBeVisible({ timeout: 20000 });
  await page.getByRole("link", { name: /E2E swing/ }).click();
  await expect(page.getByText("Orders placed: false")).toBeVisible();
  await expect(page.getByText("Fixture response").first()).toBeVisible();
  await expect(page.getByText("Proposal only")).toBeVisible({ timeout: 20000 });
  await shot(page, "04-research-mission");

  await page.getByRole("link", { name: "Virtual Office" }).click();
  await expect(page.getByText("Warren Buffett").first()).toBeVisible();
  await shot(page, "02-virtual-office");
  await page.getByRole("link", { name: /Warren Buffett/ }).click();
  await expect(page.getByText("completed").first()).toBeVisible();
  await shot(page, "03-buffett-workspace");

  await page.getByRole("link", { name: "Backtesting" }).click();
  await page.locator("select[name=mandate]").selectOption("e2e-desk");
  await expect(page.locator("select[name=mode]")).toHaveValue("fixture");
  await page.getByRole("textbox", { name: "Symbols" }).fill("AAPL MSFT");
  await page.getByRole("button", { name: "Run historical job" }).click();
  await expect(page.getByRole("link", { name: "completed" })).toBeVisible({ timeout: 20000 });
  await page.getByRole("link", { name: "completed" }).click();
  await expect(page.getByText("performance_metrics")).toBeVisible();
  await shot(page, "05-backtest");

  await page.getByRole("link", { name: "Paper Trading" }).click();
  await page.getByRole("textbox", { name: "Name" }).fill("e2e-fund");
  await page.locator("select[name=mandate]").selectOption("e2e-desk");
  await expect(page.locator("select[name=mode]")).toHaveValue("fixture");
  await page.getByRole("textbox", { name: "Symbols" }).fill("AAPL");
  await page.getByRole("button", { name: "Deploy paper fund" }).click();
  await page.getByRole("link", { name: /e2e-fund/ }).click();
  await expect(page.getByRole("button", { name: "Run approved session" })).toBeDisabled();
  await expect(page.getByText("Nothing has been sent to the broker")).toBeVisible();
  await shot(page, "06-paper-before-approval");
  await page.getByRole("button", { name: "Approve this plan" }).click();
  await expect(page.getByRole("button", { name: "Run approved session" })).toBeEnabled();
  await page.getByRole("button", { name: "Run approved session" }).click();
  await expect(page.getByText(/Recorded/)).toBeVisible({ timeout: 20000 });

  await page.getByRole("link", { name: "Portfolio Management" }).click();
  await page.getByRole("link", { name: /e2e-fund/ }).click();
  await expect(page.getByText("Fixture-backed ledger")).toBeVisible();
  await expect(page.getByText("Total P&L")).toBeVisible();
  await shot(page, "07-portfolio");

  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByText("Values included in this response: false")).toBeVisible();
  await expect(page.getByText("Master key missing", { exact: false })).toBeVisible();
  await shot(page, "08-settings");
  await page.getByRole("link", { name: "Agent Directory" }).click();
  await shot(page, "09-directory");
  await page.getByRole("link", { name: "Activity & Audit Log" }).click();
  await shot(page, "10-audit");
});
