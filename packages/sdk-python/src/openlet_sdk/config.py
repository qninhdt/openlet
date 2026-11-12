import os

import yaml


def load():
    with open(os.environ["OPENLET_CONFIG"]) as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError("configuration must be a YAML mapping")
    return value


def secret(value):
    if not isinstance(value, str) or not (value.startswith("${") and value.endswith("}")):
        raise ValueError("secret must reference a whole ${ENV_VARIABLE} scalar")
    key = value[2:-1]
    result = os.environ[key]
    if not result:
        raise ValueError(f"empty required environment variable {key}")
    return result
