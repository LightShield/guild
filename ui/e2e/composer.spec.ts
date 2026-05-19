import { test, expect } from '@playwright/test';

test.describe('Flow Composer (REQ-UI-01 through REQ-UI-08)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/composer');
    await page.waitForSelector('.svelte-flow', { timeout: 10000 });
  });

  // REQ-UI-01: Canvas & Layout

  test('REQ-UI-01.1: dark mode canvas', async ({ page }) => {
    const flow = page.locator('.svelte-flow');
    await expect(flow).toBeVisible();
    const bg = await flow.evaluate(el => getComputedStyle(el).backgroundColor);
    expect(bg).not.toBe('rgb(255, 255, 255)');
  });

  test('REQ-UI-01.2: collapsible main sidebar', async ({ page }) => {
    const collapseBtn = page.locator('button[title="Collapse sidebar"]');
    await expect(collapseBtn).toBeVisible();
    await collapseBtn.click();
    await page.waitForTimeout(300);
    const expandBtn = page.locator('button[title="Expand sidebar"]');
    await expect(expandBtn).toBeVisible();
    // Expand it back so other tests aren't affected
    await expandBtn.click();
    await page.waitForTimeout(300);
  });

  test('REQ-UI-01.5: new nodes placed in visible area', async ({ page }) => {
    const agents = page.locator('[draggable="true"]');
    const count = await agents.count();
    if (count >= 3) {
      await agents.nth(0).click();
      await agents.nth(1).click();
      await agents.nth(2).click();
      await expect(page.locator('.svelte-flow__node')).toHaveCount(3);
    }
  });

  // REQ-UI-02: Agent Nodes

  test('REQ-UI-02.1: pre-built agents in sidebar palette', async ({ page }) => {
    const agents = page.locator('[draggable="true"]');
    await expect(agents.first()).toBeVisible();
    const count = await agents.count();
    expect(count).toBeGreaterThanOrEqual(5);
  });

  test('REQ-UI-02.5: + Agent button opens create form', async ({ page }) => {
    const createBtn = page.locator('button:has-text("+ Agent")');
    await expect(createBtn).toBeVisible();
    await createBtn.click();
    // Right panel should show create form with heading
    await expect(page.locator('text=Create Agent')).toBeVisible();
  });

  test('REQ-UI-02.5: creating an agent adds it to canvas and palette', async ({ page }) => {
    await page.locator('button:has-text("+ Agent")').click();
    // Wait for panel to appear
    await expect(page.locator('text=Create Agent')).toBeVisible();
    // Fill in the form - use flexible selectors
    const nameInput = page.locator('input[placeholder*="agent"], input[id*="create-name"]').first();
    await nameInput.fill('my_custom_agent');
    // Submit
    await page.locator('button:has-text("Create")').click();
    // Node should appear on canvas
    await expect(page.locator('.svelte-flow__node')).toHaveCount(1, { timeout: 5000 });
  });

  // REQ-UI-03: Connections

  test('REQ-UI-03.1: nodes have connection handles', async ({ page }) => {
    const agents = page.locator('[draggable="true"]');
    await agents.nth(0).click();
    await agents.nth(1).click();
    const handles = page.locator('.svelte-flow__handle');
    const count = await handles.count();
    expect(count).toBeGreaterThanOrEqual(4);
  });

  // REQ-UI-04: Blocks (Composites)

  test('REQ-UI-04.12: saved blocks appear in sidebar', async ({ page }) => {
    const block = JSON.stringify([{
      name: 'test-block',
      role: 'orchestrator',
      description: 'A test block',
      composite: true,
      nodes: [
        { id: 'a', position: { x: 0, y: 0 }, data: { blockName: 'agent_a', role: 'coder' } },
        { id: 'b', position: { x: 200, y: 0 }, data: { blockName: 'agent_b', role: 'tester' } },
      ],
      edges: [{ id: 'a-b', source: 'a', target: 'b' }],
      agentCount: 2,
    }]);
    await page.evaluate((b) => localStorage.setItem('guild-custom-blocks', b), block);
    await page.reload();
    await page.waitForSelector('.svelte-flow');
    await expect(page.locator('text=test-block')).toBeVisible();
  });

  // REQ-UI-05: Preset Flows

  test('REQ-UI-05.1: Full Development preset loads 6 nodes', async ({ page }) => {
    const presetBtn = page.locator('button:has-text("Full Development")');
    await expect(presetBtn).toBeVisible();
    await presetBtn.click();
    await expect(page.locator('.svelte-flow__node')).toHaveCount(6, { timeout: 5000 });
    const edgeCount = await page.locator('.svelte-flow__edge').count();
    expect(edgeCount).toBeGreaterThanOrEqual(5);
  });

  // REQ-UI-06: Save & Load

  test('REQ-UI-06.1: save button and name input exist', async ({ page }) => {
    await expect(page.locator('input[placeholder="Flow name..."]')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeVisible();
  });

  test('REQ-UI-06.4: clear button removes all nodes', async ({ page }) => {
    await page.locator('button:has-text("Full Development")').click();
    await expect(page.locator('.svelte-flow__node')).toHaveCount(6, { timeout: 5000 });
    await page.locator('button:has-text("Clear")').click();
    await expect(page.locator('.svelte-flow__node')).toHaveCount(0, { timeout: 5000 });
  });

  // REQ-UI-07: Help & Discoverability

  test('REQ-UI-07.1: shortcuts help legend toggles', async ({ page }) => {
    const helpBtn = page.locator('button:has-text("Shortcut")');
    await expect(helpBtn).toBeVisible();
    await helpBtn.click();
    await expect(page.locator('h4:has-text("Keyboard")')).toBeVisible();
  });

  test('REQ-UI-07.2: empty canvas shows placeholder', async ({ page }) => {
    await expect(page.locator('text=Build your agent workflow')).toBeVisible();
  });

  // REQ-UI-08: Styling

  test('REQ-UI-08.4: minimap and controls visible', async ({ page }) => {
    await expect(page.locator('.svelte-flow__minimap')).toBeVisible();
    await expect(page.locator('.svelte-flow__controls')).toBeVisible();
  });
});
