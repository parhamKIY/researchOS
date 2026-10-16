import type { ModelCatalog, SystemAdapter } from "../lib/system-llm";

export function ProviderModelSelect({ adapter, catalog, value, onChange }: {
  adapter: SystemAdapter; catalog: ModelCatalog | null; value: string; onChange: (value: string) => void;
}) {
  return <label>Model<select name="model_name" value={adapter === "mock" ? "fixture-model" : value}
    onChange={(event) => onChange(event.target.value)} required
    disabled={adapter !== "mock" && !catalog?.items.length}>
    {adapter === "mock" ? <option value="fixture-model">Mock · local fixture</option> : <>
      <option value="">{catalog ? "Select a model" : "Load available models first"}</option>
      {catalog?.items.map((item) => <option key={item.id} value={item.id}>
        {item.display_name === item.id ? item.id : `${item.display_name} · ${item.id}`}
      </option>)}
    </>}
  </select></label>;
}
