import { useState } from "react";
import { api } from "../api/client";
import type { Credential } from "../api/types";
import {
  Button,
  Done,
  ErrorNote,
  Field,
  Loading,
  PillToggle,
} from "../components/ui";
import { messageOf, useAsync } from "./useAsync";

/**
 * The user's own provider, model and key. The key is write-only: it is sent,
 * and only ever read back as its last four characters. Saving it also makes
 * it the key their AI runs on (ADR 0066), which `onSaved` re-reads.
 */
export function OwnProviderForm({ onSaved }: { onSaved: () => Promise<void> }) {
  const credential = useAsync<Credential | null>(
    () => api.get("/ai-credential"),
    [],
  );
  const providers = useAsync<Record<string, string[]>>(
    () => api.get("/ai-providers"),
    [],
  );

  const [provider, setProvider] = useState("anthropic");
  const [model, setModel] = useState("claude-opus-5");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const models = providers.data?.[provider] ?? [];

  async function save() {
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      await api.put("/ai-credential", {
        provider,
        model,
        api_key: apiKey,
        // Only an OpenAI key may name its own endpoint (ADR 0065).
        base_url:
          provider === "openai" && baseUrl.trim() ? baseUrl.trim() : null,
      });
      setApiKey("");
      setSaved(true);
      await Promise.all([credential.reload(), onSaved()]);
    } catch (caught) {
      setSaveError(messageOf(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="panel">
      <h3>Your provider and key</h3>
      <p className="subcopy" style={{ fontSize: 14, lineHeight: 1.65 }}>
        Use a provider you already pay for. The key is stored encrypted on the
        server and never shown back to you.
      </p>

      {credential.loading ? (
        <Loading what="your settings" />
      ) : credential.data ? (
        <p className="model-pill" style={{ margin: "4px 0 16px" }}>
          Using {credential.data.model} on {credential.data.provider} · key
          ending ····{credential.data.last_four}
        </p>
      ) : (
        <p className="model-pill" style={{ margin: "4px 0 16px" }}>
          No model configured yet — analysis needs one.
        </p>
      )}
      {credential.data?.status === "failed" && (
        <ErrorNote
          error={`This key last failed: ${credential.data.last_error}`}
        />
      )}

      <div style={{ marginBottom: 14 }}>
        <span className="field-label" id="provider-label">
          Provider
        </span>
        <div
          className="row"
          style={{ gap: 8 }}
          role="group"
          aria-labelledby="provider-label"
        >
          {Object.keys(providers.data ?? { anthropic: [] }).map((name) => (
            <PillToggle
              key={name}
              pressed={provider === name}
              onClick={() => {
                setProvider(name);
                const first = providers.data?.[name]?.[0];
                if (first) setModel(first);
              }}
            >
              {name}
            </PillToggle>
          ))}
        </div>
      </div>

      <Field
        label="Model"
        hint="Any model your provider serves. The listed ones are the ones we can price exactly."
      >
        <input
          className="input"
          value={model}
          list="model-suggestions"
          onChange={(event) => setModel(event.target.value)}
        />
      </Field>
      <datalist id="model-suggestions">
        {models.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>

      <Field
        label="API key"
        hint="Stored encrypted. We only ever show the last four characters."
      >
        <input
          className="input"
          type="password"
          value={apiKey}
          autoComplete="off"
          placeholder={credential.data ? "Enter a new key to replace" : "sk-…"}
          onChange={(event) => setApiKey(event.target.value)}
        />
      </Field>

      {provider === "openai" && (
        <Field
          label="Base URL (optional)"
          hint="Leave blank for OpenAI. For an OpenAI-compatible cloud such as Azure OpenAI, Groq or Together, at its public URL."
        >
          <input
            className="input"
            value={baseUrl}
            placeholder="https://api.openai.com/v1"
            onChange={(event) => setBaseUrl(event.target.value)}
          />
        </Field>
      )}

      <ErrorNote error={saveError} />
      {saved && <Done>Saved.</Done>}
      <Button onClick={save} busy={saving} disabled={!apiKey.trim()}>
        Save key
      </Button>
    </div>
  );
}
