package sdk

import (
	"bytes"
	"fmt"
	"os"
	"strings"

	"go.yaml.in/yaml/v4"
)

type Config struct{ root yaml.Node }

func LoadConfig() (*Config, error) {
	path := os.Getenv("OPENLET_CONFIG")
	if path == "" {
		return nil, fmt.Errorf("OPENLET_CONFIG is required")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	c := new(Config)
	if err = yaml.Unmarshal(raw, &c.root); err != nil {
		return nil, err
	}
	if len(c.root.Content) != 1 || c.root.Content[0].Kind != yaml.MappingNode {
		return nil, fmt.Errorf("configuration must be a YAML mapping")
	}
	return c, nil
}

// Section validates only its owner's fields; other roles need no secrets here.
func (c *Config) Section(path string, target any) error {
	return c.section(path, target, false)
}

func (c *Config) OptionalSection(path string, target any) error {
	return c.section(path, target, true)
}

func (c *Config) section(path string, target any, optional bool) error {
	n := c.root.Content[0]
	for _, key := range strings.Split(path, ".") {
		var found *yaml.Node
		for i := 0; i+1 < len(n.Content); i += 2 {
			if n.Content[i].Value == key {
				found = n.Content[i+1]
				break
			}
		}
		if found == nil {
			if optional {
				return nil
			}
			return fmt.Errorf("missing config section %s", path)
		}
		n = found
	}
	b, err := yaml.Marshal(n)
	if err != nil {
		return err
	}
	d := yaml.NewDecoder(bytes.NewReader(b))
	d.KnownFields(true)
	if err = d.Decode(target); err != nil {
		return fmt.Errorf("%s: %w", path, err)
	}
	return nil
}

func Secret(path, value string) (string, error) {
	if !strings.HasPrefix(value, "${") || !strings.HasSuffix(value, "}") {
		return "", fmt.Errorf("%s must reference ${ENV_VARIABLE}", path)
	}
	key := value[2 : len(value)-1]
	value = os.Getenv(key)
	if value == "" {
		return "", fmt.Errorf("%s: required environment variable %s is empty", path, key)
	}
	return value, nil
}
