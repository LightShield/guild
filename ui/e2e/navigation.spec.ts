import { test, expect } from '@playwright/test';

test.describe('Navigation', () => {
  test('home page loads', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/Guild/);
  });

  test('navigation links exist', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('a[href="/composer"]')).toBeVisible();
    await expect(page.locator('a[href="/messages"]')).toBeVisible();
  });

  test('can navigate to composer', async ({ page }) => {
    await page.goto('/');
    await page.click('a[href="/composer"]');
    await expect(page).toHaveURL(/composer/);
  });

  test('can navigate to messages', async ({ page }) => {
    await page.goto('/');
    await page.click('a[href="/messages"]');
    await expect(page).toHaveURL(/messages/);
  });
});
