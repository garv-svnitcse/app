const puppeteer = require('puppeteer');
(async () => {
  const browser = await puppeteer.launch({headless: true});
  const page = await browser.newPage();
  page.on('console', msg => console.log('PAGE LOG:', msg.text()));
  page.on('pageerror', error => console.log('PAGE ERROR:', error.message));
  await page.goto('http://localhost:3001/login');
  await page.type('input[type="email"]', 'test@wavygo.in');
  await page.type('input[type="password"]', 'password123');
  await page.click('button[type="submit"]');
  await page.waitForNavigation();
  await page.goto('http://localhost:3001/employees');
  await page.waitForTimeout(2000);
  await browser.close();
})();
