import { test, expect } from '../../Extra/Source/node_modules/@playwright/test/index.mjs';

test('minimal homepage has a single colon entrance and no download links', async ({page}) => {
  const errors=[]; page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('heading',{name:'A little more room to explore.'})).toBeVisible();
  await expect(page.locator('a[href="/site/notes/"]')).toHaveCount(1);
  await expect(page.locator('.quiet-colon')).toHaveText(':');
  await expect(page.getByRole('link',{name:/download/i})).toHaveCount(0);
  await expect(page.locator('.hero-photo img')).toBeVisible();
  await page.getByRole('button',{name:'Switch to dark mode'}).click();
  await page.reload(); await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
  await page.locator('.quiet-colon').click();
  await expect(page.getByRole('heading',{name:'Off the clock.'})).toBeVisible();
  await expect(page.locator('.game-card')).toHaveCount(24);
  expect(errors).toEqual([]);
});
test('homepage has no try-it search demo', async ({page}) => {
  const requests=[];
  await page.route('**/api/search',route=>{requests.push(true);return route.fulfill({json:{results:[]}});});
  await page.goto('/');
  await expect(page.getByRole('link',{name:/try it/i})).toHaveCount(0);
  await expect(page.locator('#search-form')).toHaveCount(0);
  await expect(page.locator('#query')).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'Real search. Not a website demo.'})).toBeVisible();
  expect(requests).toEqual([]);
});
test('Geometry Rush starts, 4 enables autoplay, and the button returns control', async ({page}) => {
  const errors=[]; page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/site/notes/'); await page.getByRole('button',{name:/Geometry Rush/}).click();
  const canvas=page.locator('#game-canvas');
  const box=await canvas.boundingBox();
  await page.mouse.click(box.x+box.width*(75/760),box.y+box.height*(145/460));
  await expect(page.locator('#auto-play')).toBeEnabled();
  await page.keyboard.press('4'); await expect(page.locator('#auto-play')).toHaveAttribute('aria-pressed','true');
  await page.locator('#auto-play').click(); await expect(page.locator('#auto-play')).toHaveAttribute('aria-pressed','false');
  await page.locator('#exit-game').click(); await expect(page.locator('#library')).toBeVisible(); expect(errors).toEqual([]);
});
test('AI key stays out of persistent storage and request URLs; replies render safely', async ({page}) => {
  let request;
  await page.route('https://generativelanguage.googleapis.com/**',route=>{request=route.request();return route.fulfill({json:{candidates:[{content:{parts:[{text:'<img src=x onerror=alert(1)>\n```js\nconst x = 1;\n```'}]}}]}});});
  await page.goto('/site/notes/'); await page.getByRole('tab',{name:/Think/}).click();
  await page.locator('#api-key').fill('test-key-not-real'); await page.getByRole('button',{name:'Connect',exact:true}).click();
  await page.locator('#message').fill('Hello world'); await page.getByRole('button',{name:'Send ↗'}).click();
  await expect(page.locator('.message.ai')).toContainText('<img src=x'); await expect(page.locator('.message.ai img')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Copy code'})).toBeVisible();
  expect(request.url()).not.toContain('test-key'); expect(request.headers()['x-goog-api-key']).toBe('test-key-not-real');
  expect(await page.evaluate(()=>JSON.stringify(localStorage))).not.toContain('test-key');
  expect(await page.evaluate(()=>JSON.stringify(sessionStorage))).not.toContain('test-key');
  await page.getByRole('button',{name:'Clear chat'}).click(); await expect(page.locator('.message')).toHaveCount(0);
});
test('AI handles keyless sends, optional tab storage, and provider errors', async ({page}) => {
  await page.route('https://generativelanguage.googleapis.com/**',route=>route.fulfill({status:429,json:{error:{message:'limited'}}}));
  await page.goto('/site/notes/'); await page.getByRole('tab',{name:/Think/}).click();
  await page.locator('#message').fill('hello with spaces'); await page.getByRole('button',{name:'Send ↗'}).click();
  await expect(page.locator('#chat-status')).toContainText('Connect your own');
  await page.locator('#api-key').fill('test-key'); await page.locator('#remember-key').check(); await page.getByRole('button',{name:'Connect',exact:true}).click();
  expect(await page.evaluate(()=>sessionStorage.getItem('sreon-tab-key'))).toBe('test-key');
  await page.getByRole('button',{name:'Send ↗'}).click(); await expect(page.locator('#chat-status')).toContainText('Provider limit');
  await expect(page.locator('#message')).toHaveValue('hello with spaces');
  await page.getByRole('button',{name:'Forget key'}).click(); expect(await page.evaluate(()=>sessionStorage.getItem('sreon-tab-key'))).toBeNull();
});
test('phone layout stays within the screen on the homepage and both hidden tabs', async ({page}) => {
  await page.setViewportSize({width:390,height:844});
  for(const path of ['/','/site/notes/']) {
    await page.goto(path); expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  }
  await page.getByRole('tab',{name:/Think/}).click(); expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('all 24 relocated modules can start without script or canvas errors', async ({page}) => {
  const errors=[]; page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/site/notes/');
  for(let index=0;index<24;index++) {
    await page.locator('.game-card').nth(index).click();
    await expect(page.locator('#game-canvas')).toBeVisible();
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await page.locator('#exit-game').click();
  }
  expect(errors).toEqual([]);
});

test('endless mode starts from an accessible button and retains all three forms', async ({page}) => {
  await page.goto('/site/notes/'); await page.getByRole('button',{name:/Geometry Rush/}).click();
  await page.getByRole('button',{name:'∞ Endless'}).click();
  await expect(page.locator('#auto-play')).toBeEnabled();
  await page.keyboard.press('4');
  await expect(page.locator('#auto-play')).toHaveAttribute('aria-pressed','true');
  const modes = await page.evaluate(() => {
    const seen = new Set();
    for(let frame=0;frame<2000;frame++) { GAME_GD.update(running,1/60); seen.add(running.mode); }
    return {modes:[...seen].sort(),endless:running.endless,stage:running.stage,dead:running.dead};
  });
  expect(modes).toEqual({modes:['cube','ship','wave'],endless:true,stage:1,dead:false});
});

test('all three photographs load and discovery cards do not search', async ({page}) => {
  const requests=[];
  await page.route('**/api/search',route=>{requests.push(true);return route.fulfill({json:{results:[]}});});
  await page.goto('/');
  await page.locator('.discovery-grid').scrollIntoViewIfNeeded();
  for(const image of await page.locator('.discovery-image img').all()) await expect.poll(()=>image.evaluate(img=>img.complete && img.naturalWidth>0)).toBe(true);
  await expect(page.getByRole('heading',{name:'Take the scenic route.'})).toBeVisible();
  expect(requests).toEqual([]);
});
