# ChronoFace

Windows desktop application that sorts a folder of photos by the estimated age of a specific person appearing in them.

Sort large, unordered photo collections by a specific person's estimated age — youngest to oldest — for presentations, slideshows, albums, and other chronological workflows.

## Privacy

**All photo analysis is performed locally on this computer. No photos or facial data are uploaded.**

## Status

MVP complete through review + export, plus **Settings → model packs**:

- Local analysis (metadata, faces, age, ranking)
- **Review & Correct** timeline (drag order, manual age, face reassignment, exclude)
- **Export to Folder** numbered age-ordered copies + CSV
- **Settings** to choose OpenCV Fast or InsightFace buffalo/antelope packs
- Windows portable build script (`scripts/build_windows.py`)

## Requirements

- Windows 10/11 (macOS later)
- Python 3.11+ (tested with 3.13)

## Setup (Windows)

```bat
git clone https://github.com/OptimaLPro/ChronoFace.git
cd ChronoFace
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Git Bash:

```bash
git clone https://github.com/OptimaLPro/ChronoFace.git
cd ChronoFace
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

> InsightFace packs (buffalo_l recommended) are for **personal / non-commercial** use.
> Open **Settings → Models** to compare speed vs quality, then **Downloads** to fetch packs.

## Run

```bat
python app.py
```

## Models (Settings)

| Pack | Speed | Quality | Notes |
|------|-------|---------|-------|
| OpenCV Fast (YuNet + SFace) | Fastest | Good | Easiest; tiny download |
| InsightFace buffalo_s | Fast | Better | Balanced |
| InsightFace buffalo_l ★ | Medium | Best | Recommended personal default |
| InsightFace antelopev2 | Slow | Maximum | Largest / strongest |

After changing models, run **Analyze Photos** again (embeddings are not compatible across packs).

## Review & export

1. Click **Review & Correct**
2. Drag thumbnails to fix order (filter must be “All photos” to save full order)
3. Select a photo → set manual age / reassign face / approve / exclude / mark not target
4. Click **Export to Folder** for numbered copies in youngest-to-oldest order

## Windows portable build

```bat
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/build_windows.py
```

Then run `dist\ChronoFace\ChronoFace.exe`.

## Development phases

| Phase | Focus |
|-------|--------|
| 1 | Foundation, UI setup, SQLite |
| 2 | Metadata pipeline, hashing, thumbnails |
| 3 | Face detection / recognition |
| 4 | Age estimation |
| 5 | Ranking / grouping |
| 6 | Manual review timeline |
| 7 | Numbered export + CSV |
| 8 | Windows packaging script |
| 9 | Settings + swappable model packs (current) |


## Architecture notes

- UI (PySide6) stays separate from vision, metadata, sorting, and export logic.
- Vision models sit behind abstract interfaces so weights can be swapped when licensing allows.
- Original photos are never modified; exports are copies into the chosen output folder.

## License note

Before bundling any pretrained face/age model, verify code license, model-weight license, commercial use, and redistribution rights separately.
