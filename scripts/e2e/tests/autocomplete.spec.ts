import path from "node:path";

import { expect, test } from "@playwright/test";

const shellUrl = "http://autocomplete-shell.test/";
const scriptPath = path.resolve(process.cwd(), "static/src/js/autocomplete.js");

function entityMarkup(id = "entity", context = "") {
  return `
    <div id="${id}" data-autocomplete data-autocomplete-mode="entity"
         data-autocomplete-required="true" data-autocomplete-url="/options/"
         ${context ? `data-autocomplete-context='${context}'` : ""}>
      <input type="hidden" data-autocomplete-value>
      <input type="search" data-autocomplete-input required>
      <div id="${id}-options" data-autocomplete-options hidden></div>
    </div>`;
}

async function mount(page, body: string, responder?: (query: string) => Promise<Array<Record<string, string>>>) {
  await page.route(`${shellUrl}**`, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/options/") {
      const query = url.searchParams.get("q") || "";
      const results = responder
        ? await responder(query)
        : [
            {value: "1", label: "Альфа"},
            {value: "2", label: "Бета"},
          ];
      try {
        await route.fulfill({json: {mode: "entity", results}});
      } catch (_error) {
        // AbortController may cancel a deliberately delayed test response.
      }
      return;
    }
    await route.fulfill({
      contentType: "text/html; charset=utf-8",
      body: `<!doctype html><html><body>${body}</body></html>`,
    });
  });
  await page.goto(shellUrl);
  await page.addScriptTag({path: scriptPath});
}

test.describe("@ui shared autocomplete", () => {
  test("rebinds when HTMX retains the root but replaces its children", async ({page}) => {
    const queries: string[] = [];
    await mount(page, entityMarkup("retained"), async (query) => {
      queries.push(query);
      return [{value: query || "empty", label: query ? `Новый ${query}` : "Пустой"}];
    });

    await page.evaluate(() => {
      const root = document.querySelector("#retained") as HTMLElement;
      (window as any).__oldAutocompleteInput = root.querySelector("[data-autocomplete-input]");
      root.innerHTML = `
        <input type="hidden" data-autocomplete-value>
        <input type="search" data-autocomplete-input required>
        <div id="retained-options-new" data-autocomplete-options hidden></div>`;
      document.dispatchEvent(new CustomEvent("htmx:afterSwap", {detail: {target: root}}));
    });

    const newInput = page.locator("#retained [data-autocomplete-input]");
    await newInput.fill("поле");
    await expect(page.locator("#retained [role=option]")).toHaveText("Новый поле");
    const countBeforeDetachedInput = queries.length;
    await page.evaluate(() => {
      const oldInput = (window as any).__oldAutocompleteInput as HTMLInputElement;
      oldInput.value = "устаревший узел";
      oldInput.dispatchEvent(new Event("input", {bubbles: true}));
    });
    await page.waitForTimeout(250);

    expect(queries).toHaveLength(countBeforeDetachedInput);
    await expect(newInput).toHaveAttribute("aria-controls", "retained-options-new");
  });

  test("cancels stale work on input and context changes", async ({page}) => {
    await mount(
      page,
      `<input id="department" value="1">${entityMarkup("ordered", "{&quot;department&quot;:&quot;#department&quot;}")}`,
      async (query) => {
        if (query === "медленно") await new Promise((resolve) => setTimeout(resolve, 450));
        return [{value: query, label: query === "медленно" ? "Старый ответ" : `Ответ ${query}`}];
      }
    );

    const input = page.locator("#ordered [data-autocomplete-input]");
    await input.fill("первый");
    await expect(page.locator("#ordered [role=option]")).toHaveText("Ответ первый");
    await input.press("ArrowDown");
    await expect(input).toHaveAttribute("aria-activedescendant", /ordered-options-option-0/);

    await input.fill("медленно");
    await expect(input).not.toHaveAttribute("aria-activedescendant", /.+/);
    await expect(page.locator("#ordered [data-autocomplete-options]")).toBeHidden();
    await page.waitForTimeout(240);
    await input.fill("новый");
    await expect(page.locator("#ordered [role=option]")).toHaveText("Ответ новый");
    await page.waitForTimeout(500);
    await expect(page.locator("#ordered [role=option]")).toHaveText("Ответ новый");

    await page.evaluate(() => {
      const root = document.querySelector("#ordered") as HTMLElement;
      (window as any).LocalBusinessAutocomplete.setSelection(root, {value: "7", label: "Выбран"});
    });
    await input.focus();
    await page.locator("#department").fill("");
    await expect(page.locator("#ordered [data-autocomplete-value]")).toHaveValue("");
    await expect(page.locator("#ordered [data-autocomplete-options]")).toBeHidden();
    await page.waitForTimeout(500);
    await expect(page.locator("#ordered [data-autocomplete-options]")).toBeHidden();
  });

  test("requires a selected entity but accepts free suggestion text", async ({page}) => {
    await mount(
      page,
      `${entityMarkup("strict")}
       <div id="suggestion" data-autocomplete data-autocomplete-mode="suggestion" data-autocomplete-url="/options/">
         <input type="hidden" data-autocomplete-value>
         <input type="search" data-autocomplete-input>
         <div id="suggestion-options" data-autocomplete-options hidden></div>
       </div>`
    );

    await page.locator("#strict [data-autocomplete-input]").fill("Свободный текст");
    await page.locator("#suggestion [data-autocomplete-input]").fill("SER-42");
    const validity = await page.evaluate(() => ({
      entity: (document.querySelector("#strict [data-autocomplete-input]") as HTMLInputElement).checkValidity(),
      suggestion: (document.querySelector("#suggestion [data-autocomplete-input]") as HTMLInputElement).checkValidity(),
    }));

    expect(validity).toEqual({entity: false, suggestion: true});
    await expect(page.locator("#strict [data-autocomplete-value]")).toHaveValue("");
    await expect(page.locator("#suggestion [data-autocomplete-value]")).toHaveValue("SER-42");
  });

  test("supports arrows, Tab, Enter and Escape", async ({page}) => {
    await mount(page, `${entityMarkup("keyboard")}<button id="after">После</button>`);
    const input = page.locator("#keyboard [data-autocomplete-input]");
    const value = page.locator("#keyboard [data-autocomplete-value]");
    const options = page.locator("#keyboard [data-autocomplete-options]");

    await input.press("ArrowDown");
    await expect(options).toBeVisible();
    await input.press("ArrowDown");
    await input.press("Tab");
    await expect(value).toHaveValue("1");
    await expect(input).toHaveValue("Альфа");
    await expect(page.locator("#after")).toBeFocused();

    await input.focus();
    await expect(page.locator("#keyboard [role=option]")).toHaveCount(2);
    await expect(options).toBeVisible();
    await input.press("ArrowDown");
    await expect(input).toHaveAttribute("aria-activedescendant", "keyboard-options-option-0");
    await input.press("ArrowDown");
    await expect(input).toHaveAttribute("aria-activedescendant", "keyboard-options-option-1");
    await input.press("Enter");
    await expect(value).toHaveValue("2");
    await expect(input).toHaveValue("Бета");
    await expect(options).toBeHidden();

    await input.press("ArrowDown");
    await expect(options).toBeVisible();
    await input.press("Escape");
    await expect(options).toBeHidden();
    await expect(input).not.toHaveAttribute("aria-activedescendant", /.+/);
  });
});
