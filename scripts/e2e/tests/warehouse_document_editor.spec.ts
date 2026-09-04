import path from "node:path";

import { expect, test } from "@playwright/test";

test("warehouse editor reindexes autocomplete contexts for cloned rows", async ({page}) => {
  await page.setContent(`
    <section data-warehouse-document-editor>
      <form><input name="lines-TOTAL_FORMS" value="1">
        <button type="button" data-add-document-line>Add</button>
        <table><tbody data-document-lines-body>
          <tr data-document-line-row>
            <td><div data-autocomplete data-autocomplete-context='{"item":"[name=\\"lines-0-item\\"]"}'><input name="lines-0-item" data-autocomplete-input><div id="lines-0-item-options" data-autocomplete-options></div></div></td>
            <td><input name="lines-0-sequence" type="hidden"></td>
            <td><button type="button" data-remove-document-line>Remove</button></td>
          </tr>
        </tbody></table>
      </form>
    </section>`);
  await page.addScriptTag({path: path.resolve(process.cwd(), "static/src/warehouse/document_editor.js")});
  await page.getByRole("button", {name: "Add"}).click();
  const contexts = await page.locator("[data-document-line-row]").evaluateAll((rows) =>
    rows.map((row) => row.querySelector("[data-autocomplete-context]")?.getAttribute("data-autocomplete-context"))
  );
  expect(contexts).toEqual([
    '{"item":"[name=\\"lines-0-item\\"]"}',
    '{"item":"[name=\\"lines-1-item\\"]"}',
  ]);
  await expect(page.locator("[data-autocomplete-options]")).toHaveCount(2);
  // A cloned row must start with an empty, closed result list. The shared
  // autocomplete opens it only after the focused field issues a query.
  await expect(page.locator("#lines-1-item-options")).toBeHidden();
});
