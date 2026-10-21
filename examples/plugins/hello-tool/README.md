# Hello Tool

A minimal out-of-process Sage tool plugin.

- Plugin: `hello-tool`
- Version: `0.1.0`
- Template: `tool` (supported)

## Validate in a Sage checkout

```bash
python -m backend.cli.plugin validate /path/to/hello-tool --strict
```

## Run the out-of-process smoke test

```bash
python -m backend.cli.plugin dev /path/to/hello-tool \
  --arguments-file /path/to/hello-tool/examples/request.json
```

Installing or enabling a lifecycle record never executes this code. The runtime starts only through an explicit dev/UI/API action.

## Test without Sage

```bash
python -m pytest
```

Keep declared permissions minimal. A permission declaration is an install-review and audit contract, not an operating-system sandbox.
