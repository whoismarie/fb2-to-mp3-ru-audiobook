# fb2-to-mp3-ru-audiobook: Russian audiobooks with Silero TTS

Turn an FB2 e-book into an audiobook: **one MP3 file per chapter**, read by a natural-sounding Russian voice. Everything runs locally on your computer. No cloud services and no API keys are needed.

It uses [Silero TTS](https://github.com/snakers4/silero-models) (model `v5_5_ru`), which places **word stress automatically**, including on words that are spelled the same but stressed differently, and restores **ё**. Many other speech generators get both wrong in Russian.

## Setup

### 1. Install Python

Install [Python 3.10 or newer](https://www.python.org/downloads/). In the installer, tick **"Add python.exe to PATH"**.

### 2. Install ffmpeg

The script uses ffmpeg to create the MP3 files. Open Command Prompt and run:

```
winget install Gyan.FFmpeg
```

Close and reopen Command Prompt, then check that it works:

```
ffmpeg -version
```

### 3. Download project

Click **Code → Download ZIP** on this page and unzip it, for example to `C:\silero-audiobook`. If you use git, you can `git clone` it instead.

### 4. Install Python packages

```
cd C:\silero-audiobook
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
```

The first command installs PyTorch, about 200 MB. The CPU version is fast enough for audiobooks.

> **Optional, for NVIDIA graphics cards:** install the GPU version of PyTorch instead. Use the command from the [PyTorch install page](https://pytorch.org/get-started/locally/) (pick *Pip*, *Python* and a *CUDA* version). It's about 2.5 GB, but it's several times faster. The script uses the GPU automatically when one is available.

### 5. First run

The first time you run the script, it downloads the Silero model (about 140 MB) into your user folder. After that it works offline.

## Usage

### Drag and drop

Drag an `.fb2` file onto **`convert.bat`**. A window opens and shows progress. When it finishes, the MP3s are in a new folder **next to the book**, named `Author - Title`.

### Command line

```
python fb2_to_mp3.py "D:\Books\book.fb2" --list       # show detected chapters without making audio
python fb2_to_mp3.py "D:\Books\book.fb2" --only 1     # convert chapter 1 to check the voice
python fb2_to_mp3.py "D:\Books\book.fb2"              # convert the whole book
```

It's worth running `--list` first. FB2 files from different sources are structured differently, so check that the chapters look right before converting a long book.

| Option | Meaning | Default |
|---|---|---|
| `--voice NAME` | Voice to use (see below) | `eugene` |
| `--out FOLDER` | Where to save the MP3s | A folder next to the book |
| `--only 1-3,7` | Convert only these chapters | All chapters |
| `--list` | Show the chapters and exit | |
| `--bitrate 64k` | MP3 quality. Use 64k for smaller files and 128k for better quality | `96k` |
| `--cpu` | Don't use the GPU, even if there is one | |

## Choosing voice

The script uses **eugene** by default, a calm male voice that works well for long listening. Silero has five Russian voices:

| Voice | Gender |
|---|---|
| `eugene` | male (default) |
| `aidar` | male |
| `baya` | female |
| `kseniya` | female |
| `xenia` | female |

To compare the voices, convert one chapter with each and listen:

```
python fb2_to_mp3.py book.fb2 --only 1 --voice aidar --out test_aidar
python fb2_to_mp3.py book.fb2 --only 1 --voice eugene --out test_eugene
```

**To change the default voice:**
- For one run, add `--voice aidar` to the command.
- For every run, open `fb2_to_mp3.py` and change `default="eugene"` on the `--voice` line.
- For drag and drop only, open `convert.bat` in Notepad and add the option to the `python` line: `python "%~dp0fb2_to_mp3.py" %* --voice aidar`.

## Known limitations

- **Numbers are always read in their basic form.** «В 1812 году» becomes «в одна тысяча восемьсот двенадцать году». This is fine for most fiction, but number-heavy books will sound awkward.
- **Latin words are transliterated letter by letter**, so occasional names work but English phrases sound rough («iPhone» → «ифоне»).
- **FB2 only.** To convert EPUB or other formats, convert them to FB2 first, for example with [Calibre](https://calibre-ebook.com/).

## Licenses

- **The script** in this repository is covered by the license in the [LICENSE](LICENSE) file.
- **The Silero models** are licensed separately by their authors under [CC BY-NC-SA 4.0](https://github.com/snakers4/silero-models/blob/master/LICENSE), which allows **non-commercial use only**. Audiobooks you make are fine for personal listening; selling or publishing them commercially requires a commercial license from Silero.
- Only convert books you have the right to use.

## Credits

- The script was written by **Claude** (Anthropic's AI assistant) in Claude Code.
- Speech synthesis: [Silero Models](https://github.com/snakers4/silero-models) by snakers4.
- Number-to-word conversion: [num2words](https://github.com/savoirfairelinux/num2words).
