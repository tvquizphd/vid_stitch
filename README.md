### Introduction

This repo's `vid_stitch.py` file allows interlacing of video and audio clips from Descript exports.


### Inputs to the script

To use this script you'll need two things.

- An fcpxml file with the edit timings, specifying the source files of each clip
- An srt file with the subtitle timings, specifying the durations and gaps of each caption

Descript can export both needed files.

- To export an fcpxml file, use "file/export/Timeline export/Final Cut Pro"
- To export an srt file, use "file/export/File export/Subtitles"

### Installing

Create the "vid_stitch" conda environment from scratch.

```
conda env create --file environment.yml
```

Or update whenever the environment changes:

```
conda env update --file environment.yml --prune
```

Then run `conda activate vid_stitch`.

### Running the script

You'll need to edit the `__main__` section of `vid_stitch.py`:

- Edit the `fname` with the  name of your fcpxml/srt files
- Edit the list of `authors` with both name and regex pattern
- Edit the list of `new_assets` with per-author file mappings
  - `old` and `path` should match the clip used in descript and new path, respectively


The actual video files are not needed to run `python vid_stitch.py`.

### Using the results

- Download the Olive\*\* video editor, and click "file/Open Project"
- Find the `otio` output of `vid_stitch.py`
- Manually set the video display settings
- Manually match the chosen video file names
- Edit, playback, and export the movie!!!

\*\*You'll need the experimental Olive v0.2.0 to support the otio format.
