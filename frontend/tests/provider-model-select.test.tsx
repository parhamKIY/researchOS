import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ProviderModelSelect } from "../src/components/provider-model-select";

describe("provider model selection", () => {
  it("blocks selection before discovery and for an empty catalog", () => {
    for (const catalog of [null, { items: [], execution_mode: "live" as const }]) {
      const html = renderToStaticMarkup(createElement(ProviderModelSelect, { adapter: "gemini", catalog, value: "", onChange: () => {} }));
      expect(html).toContain("disabled");
      expect(html).not.toContain("<input");
    }
  });

  it("uses provider IDs as values, escapes labels and preserves the selected choice", () => {
    const html = renderToStaticMarkup(createElement(ProviderModelSelect, {
      adapter: "openai_compatible", value: "vendor/text", onChange: () => {},
      catalog: { execution_mode: "live", items: [{ id: "vendor/text", display_name: "<untrusted>" }] },
    }));
    expect(html).toContain('value="vendor/text" selected');
    expect(html).toContain("&lt;untrusted&gt;");
    expect(html).not.toContain("disabled");
  });

  it("offers a clearly labelled local mock without a provider catalog", () => {
    const html = renderToStaticMarkup(createElement(ProviderModelSelect, { adapter: "mock", catalog: null, value: "", onChange: () => {} }));
    expect(html).toContain("Mock · local fixture");
    expect(html).toContain('value="fixture-model" selected');
    expect(html).not.toContain("disabled");
  });
});
