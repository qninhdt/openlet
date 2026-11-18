import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Check, ChevronDown, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { ProviderLogo } from './provider-logo';
import { useAgentPreview, type AgentProfile } from './agent-preview';

function providerFor(model: string) {
  if (/claude|anthropic/i.test(model)) return 'Anthropic';
  if (/gemini|google/i.test(model)) return 'Google';
  if (/gpt|openai|^o[134]/i.test(model)) return 'OpenAI';
  return model.includes('/') ? model.split('/')[0] : 'Other';
}

export function AgentModelPicker({
  value,
  onChange,
  disabled = false,
}: {
  value: AgentProfile;
  onChange: (patch: Partial<AgentProfile>) => void;
  disabled?: boolean;
}) {
  const p = useAgentPreview();
  const [provider, setProvider] = useState('');
  const [search, setSearch] = useState('');
  const catalog = useQuery({
    queryKey: ['agent-models', p.actorId, p.workspace.id],
    enabled: p.live.enabled,
    queryFn: () =>
      p.live.api!<{ models: { model_id: string; reasoning_efforts: (string | null)[] }[] }>(
        `/v1/workspaces/${p.workspace.id}/letas/models`,
      ),
  });
  const models = catalog.data?.models ?? [];
  const providers = [...new Set(models.map((model) => providerFor(model.model_id)))];
  const currentProvider = providerFor(value.model);
  const selectedProvider = providers.includes(provider)
    ? provider
    : providers.includes(currentProvider)
      ? currentProvider
      : providers[0];
  const visible = models.filter(
    (model) =>
      providerFor(model.model_id) === selectedProvider &&
      model.model_id.toLowerCase().includes(search.toLowerCase()),
  );
  const efforts =
    models
      .find((model) => model.model_id === value.model)
      ?.reasoning_efforts.filter((effort) => effort !== null) ?? [];
  return (
    <Popover
      onOpenChange={(open) => {
        if (open) {
          setProvider(currentProvider);
          setSearch('');
        }
      }}
    >
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          disabled={disabled}
          aria-label="Choose agent model"
          className="max-w-full justify-start font-normal"
        >
          <ProviderLogo provider={currentProvider} />
          <span className="truncate">{value.model}</span>
          {value.effort && <span className="shrink-0 text-muted-foreground">· {value.effort}</span>}
          <ChevronDown className="shrink-0" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-88 max-w-[calc(100vw-2rem)] overflow-hidden p-0">
        <div className="flex min-h-60">
          {!!providers.length && (
            <ToggleGroup
              type="single"
              value={selectedProvider}
              onValueChange={(name) => name && setProvider(name)}
              aria-label="Model provider"
              className="w-13 shrink-0 flex-col justify-start rounded-none bg-muted/50 p-1.5"
            >
              {providers.map((name) => (
                <ToggleGroupItem
                  key={name}
                  value={name}
                  aria-label={name}
                  title={name}
                  size="icon-sm"
                >
                  <ProviderLogo provider={name} />
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
          <div className="flex min-w-0 flex-1 flex-col gap-2 p-2">
            <InputGroup>
              <InputGroupAddon>
                <Search />
              </InputGroupAddon>
              <InputGroupInput
                aria-label="Search models"
                placeholder="Search models"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </InputGroup>
            <div role="radiogroup" aria-label="Agent model" className="max-h-64 overflow-y-auto">
              <Button
                role="radio"
                aria-checked={value.model === 'Default model'}
                variant="ghost"
                size="sm"
                className="w-full justify-start font-normal"
                onClick={() => onChange({ model: 'Default model', effort: '' })}
              >
                <Check className={value.model === 'Default model' ? '' : 'invisible'} />
                Default model
              </Button>
              {visible.map((model) => (
                <Button
                  key={model.model_id}
                  role="radio"
                  aria-checked={value.model === model.model_id}
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start font-normal"
                  onClick={() => onChange({ model: model.model_id, effort: '' })}
                >
                  <Check className={value.model === model.model_id ? '' : 'invisible'} />
                  <span className="truncate">{model.model_id}</span>
                </Button>
              ))}
              {catalog.isPending && (
                <p role="status" className="p-2 text-sm text-muted-foreground">
                  Loading models…
                </p>
              )}
              {catalog.error && (
                <p role="alert" className="p-2 text-sm text-destructive">
                  {catalog.error.message}
                </p>
              )}
              {!catalog.isPending && !catalog.error && !visible.length && (
                <p className="p-2 text-sm text-muted-foreground">No matching models.</p>
              )}
            </div>
            {!!efforts.length && (
              <div className="mt-auto flex items-center justify-between gap-3 border-t pt-2 text-sm">
                <span>Reasoning</span>
                <Select
                  value={value.effort || 'default'}
                  onValueChange={(effort) =>
                    onChange({ effort: effort === 'default' ? '' : effort })
                  }
                >
                  <SelectTrigger aria-label="Reasoning effort" className="w-32">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value="default">Default</SelectItem>
                      {efforts.map((effort) => (
                        <SelectItem key={effort} value={effort}>
                          {effort}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
