/* Browser acceptance and screenshots; requires Playwright in NODE_PATH or installed locally. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.BASE_URL || 'http://127.0.0.1:8765';
const shots = path.join(__dirname, 'screenshots');
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE });
  try {
    const context = await browser.newContext({ viewport: {width:1440,height:1000}, reducedMotion:'reduce', colorScheme:'dark' });
    const page = await context.newPage();
    const errors = [], unsafe = [];
    let screenshots = 0;
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => {if (new URL(r.url()).origin !== base || r.method() !== 'GET') unsafe.push(r.url());});
    const snapshot = async name => {
      await page.waitForLoadState('networkidle');
      screenshots += 1;
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${name}: page overflow`);
      const actual = await page.screenshot({fullPage:true, animations:'disabled'});
      const target = path.join(shots, `${name}.png`);
      if (process.env.UPDATE_SCREENSHOTS === '1') {fs.mkdirSync(shots,{recursive:true}); fs.writeFileSync(target,actual);}
      else assert.deepEqual(actual,fs.readFileSync(target), `${name}: screenshot changed; review before updating`);
    };
    for (const width of [1440,390]) {
      await page.setViewportSize({width,height:1000});
      await page.goto(base + '/runs');
      await page.getByRole('link',{name:'fixture-good_t1',exact:true}).waitFor();
      assert.equal(await page.locator('tbody tr').count(),3);
      await snapshot(`runs-${width}`);
      await page.getByLabel('State',{exact:true}).selectOption('budget_stopped');
      await page.waitForLoadState('networkidle');
      assert.equal(await page.locator('tbody tr').count(),1);
      await snapshot(`runs-filtered-${width}`);
      await page.getByRole('button',{name:'Clear filters'}).click();
      await page.getByRole('link',{name:'fixture-good_t1',exact:true}).click();
      await page.getByRole('heading',{name:'Overview',exact:true}).waitFor();
      await snapshot(`overview-${width}`);
      await page.getByRole('link',{name:'Trace',exact:true}).click();
      await page.locator('[data-event-id]').first().waitFor();
      await snapshot(`trace-${width}`);
      await page.getByRole('link',{name:'Assessments',exact:true}).click();
      await page.getByRole('heading',{name:'Workflow assessment',exact:true}).waitFor();
      await snapshot(`assessments-${width}`);
      const evidence = page.locator('a[data-evidence]').first();
      const eventId = await evidence.getAttribute('data-evidence');
      await evidence.click();
      const selected = page.locator(`[data-event-id="${eventId}"]`);
      await selected.waitFor();
      assert.equal(await selected.getAttribute('data-selected'),'true');
      assert.equal(await selected.getAttribute('open'),'');
      assert.equal(await selected.evaluate(e => document.activeElement === e),true);
      await snapshot(`evidence-${width}`);
      await page.getByRole('link',{name:'Map',exact:true}).click();
      await page.getByRole('heading',{name:'Site map',exact:true}).waitFor();
      await snapshot(`map-empty-${width}`);
      await page.getByRole('link',{name:'Report',exact:true}).click();
      await page.getByRole('heading',{name:'fixture-baseline',exact:true}).waitFor();
      await snapshot(`report-${width}`);
      await page.getByRole('link',{name:'Comparison',exact:true}).click();
      await page.getByRole('heading',{name:'No paired comparisons yet',exact:true}).waitFor();
      await snapshot(`comparison-empty-${width}`);
      await page.getByRole('link',{name:'New Run',exact:true}).click();
      await page.getByLabel('Evaluation name').waitFor();
      await page.getByLabel('Evaluation name').fill('browser-preview');
      assert.match(await page.locator('#spec-preview').inputValue(),/browser-preview/);
      await snapshot(`new-run-${width}`);
    }
    await page.emulateMedia({colorScheme:'light'});
    await page.goto(base+'/runs');
    await page.getByRole('link',{name:'fixture-good_t1',exact:true}).waitFor();
    await snapshot('runs-light-390');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.textContent),'Skip to content');
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('main').evaluate(e => document.activeElement === e),true);
    // Fixtures are T1 imagery, so exercise site and comparison states with explicit test-only data.
    await page.route('**/api/runs/fixture-good_t1/trace', async route => {
      const response = await route.fetch(), body = await response.json();
      body.events.find(e => e.type === 'final_output').output = {sites:[{lat:35.2,lon:-119.1}]};
      await route.fulfill({json:body});
    });
    await page.route('**/api/runs/fixture-good_t1/reference', route => route.fulfill({json:{exact:true,reference:{instance_id:'T3@test',version:'test',aoi:{name:'Test AOI',bbox:[-120,34,-118,36]},output_reference:{sites:[{lat:35.3,lon:-119.2}]}}}}));
    await page.goto(base+'/runs/fixture-good_t1/map');
    await page.locator('svg .predicted-site').waitFor();
    assert.equal(await page.locator('svg .reference-site').count(),1);
    assert.match(await page.getByRole('table',{name:'Site coordinates'}).innerText(),/35.2/);
    await snapshot('map-sites-test-data-390');
    await page.route('**/api/evals/demo-eval', async route => {
      const response = await route.fetch(), body = await response.json();
      body.report.stats.comparisons = [{baseline:'fixture-baseline',variant:'test-variant',metric:'workflow.composite',effect:0.1,ci_low:-0.1,ci_high:0.3,p_value:0.5,p_adjusted:0.5,n_instances:1,higher_is_better:true,verdict:'insufficient evidence',warnings:['Test data only']}];
      await route.fulfill({json:body});
    });
    await page.goto(base+'/comparison?eval=demo-eval');
    await page.getByRole('cell',{name:'test-variant',exact:true}).waitFor();
    await snapshot('comparison-test-data-390');
    await page.route('**/api/runs?*', route => route.fulfill({json:[]}));
    await page.goto(base+'/runs');
    await page.getByRole('heading',{name:'No runs in this store yet'}).waitFor();
    await snapshot('runs-empty-390');
    await page.route('**/api/runs?*', route => route.fulfill({status:503,json:{detail:'Store unavailable'}}));
    await page.reload();
    await page.getByRole('alert').waitFor();
    await snapshot('runs-error-390');
    assert.deepEqual(errors,[]);
    assert.deepEqual(unsafe,[]);
    console.log(`Browser acceptance passed; ${screenshots} screenshots checked.`);
  } finally {await browser.close();}
})().catch(e => {console.error(e);process.exit(1);});
