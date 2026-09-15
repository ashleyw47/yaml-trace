# yamltrace

You have a base config and a pile of environment overrides layered on top
of it — `base.yaml`, then `staging.yaml`, then `prod.yaml`, each one
overriding a handful of keys from the last. Eventually someone asks "why
is the pool size 20 in prod?" and the honest answer is you have to open
three files and mentally merge them.

`yamltrace` answers that question directly: given a dotted key path and
the files in override order, it tells you the effective value and which
file actually set it, plus every earlier file that tried to set the same
key and got overridden.

It does one thing. It does not merge configs, validate schemas, or diff
files.

## Install

No dependencies to install, just the tool itself:

```
pip install -e .
```

That gives you a `yamltrace` command. You can also run it without
installing via `python -m yamltrace.cli`.

## Usage

Given `base.yaml`:

```yaml
database:
  host: localhost
  port: 5432
  pool:
    min: 1
    max: 5
logging:
  level: info
```

and `prod.yaml`:

```yaml
database:
  host: prod-db.internal
  pool:
    max: 20
```

```
$ yamltrace database.pool.max base.yaml prod.yaml
database.pool.max = 20
  from: prod.yaml (line 4)
  shadows:
    base.yaml (line 6): 5
```

With `--json`:

```
$ yamltrace database.pool.max base.yaml prod.yaml --json
{
  "path": "database.pool.max",
  "found": true,
  "value": 20,
  "type": "int",
  "source": {
    "file": "prod.yaml",
    "line": 4
  },
  "shadowed": [
    {
      "file": "base.yaml",
      "line": 6,
      "value": 5
    }
  ]
}
```

A key that no file sets exits with status 1 and, in JSON mode, prints
`{"path": "...", "found": false}`.

List entries are addressed by index: `servers.0.host`.

## What it actually parses

There's no YAML library in the standard library, and pulling in PyYAML
felt like overkill for a tool that just needs to read config files, so
`yamltrace` ships its own small parser. It handles what config files
actually use in practice:

- nested block mappings
- block sequences, including the common `- key: value` shorthand
- plain, single-quoted, and double-quoted scalars
- single-line flow collections, `[1, 2]` and `{a: 1, b: 2}`, including
  nested ones like `{a: [1, 2]}`
- `#` comments (outside of quoted strings)

It does not handle anchors/aliases, tags, multi-document files, or flow
collections that span multiple lines. If a file uses those, parsing
will either fail loudly or misread the value — it won't silently
guess. That covers the overwhelming majority of hand-written app
config, which is the use case this tool is for.

## License

MIT, see LICENSE.
