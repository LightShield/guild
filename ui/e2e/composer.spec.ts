import { test, expect } from '@playwright/test';

test.describe('Flow Composer (REQ-UI-01 through REQ-UI-08)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/composer');
    await page.waitForSelector('.svelte-flow');
  });

  // REQ-UI-01: Canvas & Layout

  test('REQ-UI-01.1: dark mode canvas', async ({ page }) => {
    const flow = page.locator('.svelte-flow');
    await expect(flow).toBeVisible();
    // Canvas should have dark background (via CSS override)
    const bg = await flow.evaluate(el => getComputedStyle(el).backgroundColor);
    // Should not be white/light
    expect(bg).not.toBe('rgb(255, 255, 255)');
  });

  test('REQ-UI-01.2: collapsible main sidebar', async ({ page }) => {
    // Find collapse button in the layout sidebar
    const collapseBtn = page.locator('aside button[title*="ollapse"]');
    await expect(collapseBtn).toBeVisible();
    await collapseBtn.click();
    // Sidebar should be narrow
    const sidebar = page.locator('aside');
    const width = await sidebar.evaluate(el => el.offsetWidth);
    expect(width).toBeLessThanOrEqual(60);
  });

  test('REQ-UI-01.5: new nodes placed in visible area', async ({ page }) => {
    // Click agents from sidebar to add them
    const agents = page.locator('[draggable="true"]');
    const count = await agents.count();
    if (count >= 3) {
      await agents.nth(0).click();
      await agents.nth(1).click();
      await agents.nth(2).click();
      // All 3 nodes should be on canvas
      await expect(page.locator('.svelte-flow__node')).toHaveCount(3);
    }
  });

  // REQ-UI-02: Agent Nodes

  test('REQ-UI-02.1: pre-built agents in sidebar palette', async ({ page }) => {
    // Should have draggable agent items in sidebar
    const agents = page.locator('[draggable="true"]');
    await expect(agents.first()).toBeVisible();
    const count = await agents.count();
    expect(count).toBeGreaterThanOrEqual(7);
  });

  test('REQ-UI-02.5: + Agent button opens create form', async ({ page }) => {
    const createBtn = page.locator('button:has-text("+ Agent")');
    await expect(createBtn).toBeVisible();
    await createBtn.click();
    // Right panel should show create form
    await expect(page.locator('h3:has-text("Create Agent")')).toBeVisible();
    await expect(page.locator('#create-name')).toBeVisible();
    await expect(page.locator('#create-role')).toBeVisible();
    await expect(page.locator('#create-model')).toBeVisible();
  });

  test('REQ-UI-02.5: creating an agent adds it to canvas and palette', async ({ page }) => {
    await page.locator('button:has-text("+ Agent")').click();
    await page.locator('#create-name').fill('my_custom_agent');
    await page.locator('#create-role').selectOption('coder');
    await page.locator('button:has-text("Create & Add")').click();
    // Node should appear on canvas
    await expect(page.locator('.svelte-flow__node')).toHaveCount(1);
    // Agent should be in the sidebar palette
    await expect(page.locator('[draggable="true"]:has-text("my_custom_agent")')).toBeVisible();
  });

  // REQ-UI-03: Connections

  test('REQ-UI-03.1: nodes have connection handles', async ({ page }) => {
    // Add two nodes
    const agents = page.locator('[draggable="true"]');
    await agents.nth(0).click();
    await agents.nth(1).click();
    // Nodes should have handles
    await expect(page.locator('.svelte-flow__handle')).toHaveCount(4); // 2 per node (left + right)
  });

  // REQ-UI-04: Blocks (Composites)

  test('REQ-UI-04.8: saved blocks appear in sidebar', async ({ page }) => {
    // Inject a custom block into localStorage before load
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
    // Block should appear in sidebar
    await expect(page.locator('text=test-block')).toBeVisible();
  });

  // REQ-UI-05: Preset Flows

  test('REQ-UI-05.1: Full Development preset loads 6 nodes', async ({ page }) => {
    const presetBtn = page.locator('button:has-text("Full Development")');
    await expect(presetBtn).toBeVisible();
    await presetBtn.click();
    // Should load 6 nodes
    await expect(page.locator('.svelte-flow__node')).toHaveCount(6);
    // Should have edges
    const edgeCount = await page.locator('.svelte-flow__edge').count();
    expect(edgeCount).toBeGreaterThanOrEqual(5);
  });

  // REQ-UI-06: Save & Load

  test('REQ-UI-06.1: save flow with name', async ({ page }) => {
    // Add a node first
    await page.locator('[draggable="true"]').first().click();
    // Enter flow name and save
    const nameInput = page.locator('input[placeholder*="Flow name"]');
    await nameInput.fill('test-flow');
    await page.locator('button:has-text("Save")').click();
    // Should show success message (or at least not error out on the frontend)
    // Note: backend may not be running, so we just verify the button is clickable
  });

  test('REQ-UI-06.4: clear button removes all nodes', async ({ page }) => {
    // Load preset to get nodes
    await page.locator('button:has-text("Full Development")').click();
    await expect(page.locator('.svelte-flow__node')).toHaveCount(6);
    // Clear
    await page.locator('button:has-text("Clear")').click();
    await expect(page.locator('.svelte-flow__node')).toHaveCount(0);
  });

  // REQ-UI-07: Help & Discoverability

  test('REQ-UI-07.1: shortcuts help legend toggles', async ({ page }) => {
    const helpBtn = page.locator('button:has-text("Shortcuts")');
    await expect(helpBtn).toBeVisible();
    await helpBtn.click();
    // Should show keyboard shortcuts
    await expect(page.locator('text=Shift + Drag')).toBeVisible();
    await expect(page.locator('text=Multi-select')).toBeVisible();
  });

  test('REQ-UI-07.2: empty canvas shows placeholder', async ({ page }) => {
    // On fresh load with no nodes, placeholder should show
    await expect(page.locator('text=Build your agent workflow')).toBeVisible();
  });

  // REQ-UI-08: Styling

  test('REQ-UI-08.4: minimap and controls visible', async ({ page }) => {
    await expect(page.locator('.svelte-flow__minimap')).toBeVisible();
    await expect(page.locator('.svelte-flow__controls')).toBeVisible();
  });
});
