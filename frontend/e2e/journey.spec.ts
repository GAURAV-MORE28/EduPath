import { expect, test } from "@playwright/test";

/**
 * The whole adaptive loop through the real UI and real API, in demo mode
 * (NEXT_PUBLIC_DEMO_MODE=true): intake -> demo resume -> confirm claims ->
 * plan -> practice with a common misconception -> reflection -> revision.
 * Requires a fresh database.
 */
test("evidence to re-plan, end to end", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/start");
  await page.getByRole("button", { name: "Fill in for Asha" }).click();
  await expect(page.getByRole("radio", { name: /Machine Learning Engineer/ })).toBeChecked();
  await page.getByRole("button", { name: /Continue to evidence/ }).click();

  await page.getByRole("button", { name: "Use the demo resume" }).click();
  await expect(page.getByText(/skill claims? found/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Profiler").first()).toBeVisible(); // real SSE trace events
  await page.getByRole("button", { name: /Review what was found/ }).click();

  await expect(page.getByRole("heading", { name: "Is this what you meant?" })).toBeVisible();
  await expect(page.getByText("Python").first()).toBeVisible();
  await page.getByRole("button", { name: /^Confirm \d+ claims?$/ }).click();

  await page.getByRole("button", { name: "Build my plan" }).click();
  await expect(page.getByText("Plan Validator").first()).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Open my dashboard" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("Next:").first()).toBeVisible();

  // Fail an assessment the way a learner with the chain-rule misconception would.
  await page.goto("/dashboard/practice?skill=skill.backpropagation&purpose=practice");
  await page.getByRole("button", { name: "Start" }).click();
  await page.getByRole("button", { name: /Demo: answer with a common misconception/ }).click();
  await page.getByRole("button", { name: "Submit answers" }).click();
  await expect(page.getByRole("heading", { name: "Your plan changed" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Reflection Agent").first()).toBeVisible();

  await page.getByRole("link", { name: /See what changed and why/ }).click();
  await expect(page.getByRole("heading", { name: "Why did my plan change?" })).toBeVisible();
  await expect(page.getByText("Root cause: Chain Rule")).toBeVisible();
  await expect(page.getByRole("button", { name: /Revert to revision A/ })).toBeVisible();

  // Revert is one click and reversible in history. (Set JOURNEY_KEEP_REVISION=1 to stop here and inspect revision B.)
  if (process.env.JOURNEY_KEEP_REVISION) return;
  await page.getByRole("button", { name: /Revert to revision A/ }).click();
  await page.getByRole("button", { name: /Yes, restore A/ }).click();
  await expect(page.getByRole("cell", { name: /You reverted a revision/ })).toBeVisible({ timeout: 15_000 });
});
