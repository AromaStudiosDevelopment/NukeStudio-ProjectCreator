# hrox-generator

Generate Hiero / Nuke Studio `.hrox` (hieroXML) projects from structured JSON timelines.

## Features

- Validates a canonical JSON schema covering project, tracks, and clips
- Uses `ffprobe` to measure clip durations (with fallback estimation)
- Builds `hieroXML` trees including `Media`, `Project`, `Sequence`, and `trackItemCollection`
- CLI (`hroxgen`) with options for ffprobe path, relative paths, strict missing-file handling, and JSON reporting
- Library API: `hrox_generator.generate_hrox` for embedding in other tools
- Basic unit tests (pytest)

## Quick start

```bash
python -m pip install -e .[dev]
python -m pytest
hroxgen --input schema.json --output GeneratedProject.hrox
```

Use `hroxgen --help` for the full list of options.
