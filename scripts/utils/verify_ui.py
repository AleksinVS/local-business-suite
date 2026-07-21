import asyncio
from playwright.async_api import async_playwright

async def verify_ui():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={'width': 1280, 'height': 720})
        page = await context.new_page()
        
        # 1. Login
        print("Logging in...")
        await page.goto("http://127.0.0.1:8000/accounts/login/")
        await page.fill('input[name="username"]', 'admin')
        await page.fill('input[name="password"]', 'admin12345')
        await page.click('button[type="submit"]')
        
        # 2. Navigate to board
        print("Navigating to board...")
        await page.goto("http://127.0.0.1:8000/workorders/")
        await page.wait_for_selector('.toolbar')
        
        # 3. Take screenshot
        screenshot_path = "ui_verification_board.png"
        await page.screenshot(path=screenshot_path)
        print(f"Screenshot saved to {screenshot_path}")
        
        # 4. Check order of elements in .filters
        # We expect: Search (1st), Board (2nd)
        elements = await page.query_selector_all('.filters .input-group')
        results = []
        for el in elements:
            label = await el.query_selector('label')
            if label:
                text = await label.inner_text()
                results.append(text.strip())
        
        print(f"Found filter labels: {results}")
        
        if len(results) >= 2:
            if results[0] == "Поиск" and results[1] == "Доска":
                print("SUCCESS: Order is correct (Search 1st, Board 2nd).")
            else:
                print(f"FAILURE: Incorrect order. Expected [Поиск, Доска], got {results[:2]}")
        else:
            print(f"FAILURE: Not enough elements found. Found: {results}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(verify_ui())
