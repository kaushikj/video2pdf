# video2pdfslides

## Description
This project converts a lecture or presentation video into a deck of slide screenshots and can then merge those screenshots into a PDF.

The current version keeps the original spirit of the project:
- detect when motion settles,
- capture a representative frame,
- optionally convert the captured images into a PDF.

It also adds a more practical tuning layer for videos with animations:
- sequential frame sampling instead of timestamp seeking,
- more stable motion reset logic,
- basic screenshot deduplication,
- an optional `monotonic build` mode for slide content that only grows over time.

YouTube demo from the original project:
https://www.youtube.com/watch?v=Q0BIPYLoSBs

## Setup
Install dependencies:

```bash
pip install -r requirements.txt
```

## Basic usage

Default mode:

```bash
python video2pdfslides.py <video_path>
```

This will:
1. Extract slide screenshots into `./output/<video_name>/`
2. Pause so you can manually check and delete duplicates if needed
3. Ask whether to continue and create the PDF

If you want to create the PDF directly without interactive confirmation:

```bash
python video2pdfslides.py <video_path> --auto-continue
```

## Two working modes

### 1. Default mode: keep each stable change
This is the current default behavior.

Use this when:
- you want to preserve every meaningful slide state,
- you want intermediate builds to remain visible,
- the deck contains step-by-step reveals that you may want to keep.

Example:

```bash
python video2pdfslides.py c5v4.mp4 --auto-continue
```

### 2. Monotonic build mode: keep only the last frame of a purely growing sequence
Enable:

```bash
python video2pdfslides.py c5v4.mp4 --auto-continue --collapse-monotonic-build
```

Use this when:
- slide content appears gradually,
- items are added one by one,
- you want to suppress frames where content only grows and does not meaningfully disappear.

Important:
- this mode is conservative by design,
- if the animation includes fading, slight layout movement, or content redraw, it may still keep extra frames,
- in that case, tune the monotonic parameters described below.

## Recommended commands

### Recommended default command
Good starting point for typical lecture videos:

```bash
python video2pdfslides.py c5v4.mp4 --auto-continue
```

### Recommended command for fewer missed slides
Use this if the script is missing short pauses or fast slide transitions:

```bash
python video2pdfslides.py c5v4.mp4 --auto-continue --sample-rate 8 --min-still-percent 0.5 --reset-motion-percent 0.6
```

### Recommended command for gradually increasing content
Use this if slides are built step-by-step and you want fewer intermediate captures:

```bash
python video2pdfslides.py c5v4.mp4 --auto-continue --collapse-monotonic-build --monotonic-min-containment 0.90 --monotonic-min-add-percent 0.05 --monotonic-max-remove-percent 0.20
```

### More aggressive monotonic collapsing
Use this if the previous command still keeps too many “content keeps increasing” frames:

```bash
python video2pdfslides.py c5v4.mp4 --auto-continue --collapse-monotonic-build --monotonic-min-containment 0.85 --monotonic-min-add-percent 0.03 --monotonic-max-remove-percent 0.35
```

## Parameters

### Motion / sampling parameters

- `--sample-rate`
  Number of frames per second to analyze.
  Higher values reduce missed slides but increase runtime.
  Default: `6`

- `--warmup-seconds`
  Initial seconds to skip before detection starts.
  Default: `1.0`

- `--history-seconds`
  Background model history measured in sampled seconds.
  Smaller values adapt faster to changing videos.
  Default: `6.0`

- `--var-threshold`
  OpenCV MOG2 variance threshold.
  Default: `16`

- `--detect-shadows`
  Enable MOG2 shadow detection.
  Usually unnecessary for slide videos.

### Stable / motion decision parameters

- `--min-still-percent`
  If the foreground motion percentage drops below this, the frame is considered stable.
  Larger values make the detector more willing to capture a slide.
  Default: `0.35`

- `--reset-motion-percent`
  If the foreground motion percentage rises above this, a new motion segment is recognized.
  Lower values make it easier to reset and capture the next slide.
  Default: `0.9`

- `--min-still-frames`
  Number of consecutive sampled stable frames required before a screenshot is saved.
  Default: `2`

- `--reset-frames`
  Number of consecutive sampled motion frames required before the detector allows another capture.
  Default: `2`

### Deduplication parameters

- `--dedupe-percent`
  Minimum frame difference percentage versus the last saved screenshot.
  If the new candidate is too similar, it is skipped.
  Default: `0.5`

- `--dedupe-pixel-threshold`
  Pixel threshold used when computing screenshot difference for deduplication.
  Default: `18`

### Monotonic build parameters

- `--collapse-monotonic-build`
  Enable replacing the previously saved frame when the new frame appears to be a monotonic build-up of it.

- `--monotonic-min-containment`
  How much of the previously saved content must still be present in the new frame.
  Default: `0.97`

- `--monotonic-min-add-percent`
  Minimum newly added content percentage required before replacing the old screenshot.
  Default: `0.15`

- `--monotonic-max-remove-percent`
  Maximum removed content percentage allowed while still treating the sequence as monotonic growth.
  Default: `0.03`

## Practical tuning advice

If the script misses slides:
- increase `--sample-rate`
- increase `--min-still-percent`
- decrease `--reset-motion-percent`

If the script captures too many duplicates:
- increase `--dedupe-percent`
- increase `--min-still-frames`

If the script keeps too many “content gradually increasing” frames even with monotonic mode on:
- decrease `--monotonic-min-containment`
- decrease `--monotonic-min-add-percent`
- increase `--monotonic-max-remove-percent`

If monotonic mode becomes too aggressive and merges different slides:
- increase `--monotonic-min-containment`
- increase `--monotonic-min-add-percent`
- decrease `--monotonic-max-remove-percent`

## Examples

Two sample videos are available in `./input`:

- `python video2pdfslides.py "./input/Test Video 1.mp4"`
- `python video2pdfslides.py "./input/Test Video 2.mp4"`

## Notes

This is still a heuristic tool, not a semantic slide parser.
For videos with heavy animation, fade effects, cursor movement, or embedded video, some manual verification may still be necessary.

## Developer contact info
kaushik jeyaraman: kaushikjjj@gmail.com
