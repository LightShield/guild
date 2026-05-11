import { test, expect } from '@playwright/test';

test.describe('Visual Team Composer (REQ-05.6, REQ-04.24a)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/composer');
  });

  test('composer page loads with block palette', async ({ page }) => {
    // The sidebar with blocks should be visible
    await expect(page.locator('h3:has-text("Blocks")')).toBeVisible();
  });

  test('composer page has flow canvas', async ({ page }) => {
    // The @xyflow/svelte canvas should render
    await expect(page.locator('.svelte-flow')).toBeVisible();
  });

  test('clicking a block adds it to the canvas', async ({ page }) => {
    // Find a block button in the palette and click it
    const blockButtons = page.locator('button:has-text("(")');
    const count = await blockButtons.count();
    if (count > 0) {
      await blockButtons.first().click();
      // A node should appear on the canvas
      await expect(page.locator('.svelte-flow__node')).toHaveCount(1);
    }
  });

  test('dragging a block to canvas creates a node', async ({ page }) => {
    // Find a draggable block button
    const blockButton = page.locator('[draggable="true"]').first();
    if (await blockButton.count() > 0) {
      const canvas = page.locator('.svelte-flow');
      // Drag from palette to canvas
      await blockButton.dragTo(canvas);
      // Should have at least one node
      const nodes = page.locator('.svelte-flow__node');
      await expect(nodes).toHaveCount(1, { timeout: 2000 });
    }
  });

  test('save team button exists', async ({ page }) => {
    await expect(page.locator('button:has-text("Save")')).toBeVisible();
  });

  test('clear button removes all nodes', async ({ page }) => {
    // Add a node first
    const blockButtons = page.locator('button:has-text("(")');
    if (await blockButtons.count() > 0) {
      await blockButtons.first().click();
      await expect(page.locator('.svelte-flow__node')).toHaveCount(1);
    }
    // Click clear
    await page.locator('button:has-text("Clear")').click();
    await expect(page.locator('.svelte-flow__node')).toHaveCount(0);
  });

  test('team name input exists for saving', async ({ page }) => {
    // There should be an input for team name
    await expect(page.locator('input[placeholder*="name" i], input[type="text"]')).toBeVisible();
  });
});
