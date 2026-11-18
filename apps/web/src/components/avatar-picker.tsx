import { AgentAvatar } from './agent-avatar';
import { agentAppearance, type AgentAppearance } from './agent-appearance';
import { COLORS, SHAPES } from '@/vendor/bloub/skins';
import { Button } from './ui/button';
import { Field, FieldGroup, FieldLabel } from './ui/field';
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover';
import { ToggleGroup, ToggleGroupItem } from './ui/toggle-group';

export function AvatarPicker({
  name,
  value,
  onChange,
  disabled = false,
}: {
  name: string;
  value?: AgentAppearance;
  onChange: (value: AgentAppearance) => void;
  disabled?: boolean;
}) {
  const appearance = agentAppearance(name, value);
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          className="size-16 shrink-0 p-1"
          aria-label="Choose avatar"
          disabled={disabled}
        >
          <AgentAvatar name={name} appearance={appearance} className="size-14" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" aria-label="Avatar appearance">
        <FieldGroup>
          <Field>
            <FieldLabel>Shape</FieldLabel>
            <ToggleGroup
              type="single"
              value={appearance.shape}
              onValueChange={(shape) => shape && onChange({ shape, color: appearance.color })}
              className="grid w-full grid-cols-4"
            >
              {SHAPES.map(({ id }) => (
                <ToggleGroupItem key={id} value={id} aria-label={`Shape ${id}`} className="size-12">
                  <AgentAvatar
                    name={name}
                    appearance={{ ...appearance, shape: id }}
                    className="size-9"
                  />
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </Field>
          <Field>
            <FieldLabel>Color</FieldLabel>
            <ToggleGroup
              type="single"
              value={appearance.color}
              onValueChange={(color) => color && onChange({ shape: appearance.shape, color })}
              className="grid w-full grid-cols-6"
            >
              {COLORS.map(({ id, hex }) => (
                <ToggleGroupItem key={id} value={id} aria-label={`Color ${id}`} className="size-8">
                  <span className="size-5 rounded-full border" style={{ background: hex }} />
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </Field>
        </FieldGroup>
      </PopoverContent>
    </Popover>
  );
}
