"""Convert an FB2 book into one MP3 per chapter using Silero TTS (Russian).

Usage:
    python fb2_to_mp3.py book.fb2                 # whole book
    python fb2_to_mp3.py book.fb2 --list          # show detected chapters, no audio
    python fb2_to_mp3.py book.fb2 --only 1-3,7    # just some chapters
    python fb2_to_mp3.py book.fb2 --voice aidar --out D:\\Audiobooks\\Book

Re-running skips chapters whose MP3 already exists, so it can be stopped and resumed.
"""
import argparse
import re
import subprocess
import sys
import time
import warnings
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import torch
from num2words import num2words

HUB_DIR = Path.home() / ".cache" / "torch" / "hub" / "snakers4_silero-models_master"
MODEL = "v5_5_ru"
SAMPLE_RATE = 48000
MAX_CHUNK = 800  # Silero fails above ~1000 characters per call
PAUSE_SENTENCE = 0.15
PAUSE_PARAGRAPH = 0.5
PAUSE_TITLE = 1.2

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- FB2 parsing

def local(tag):
    return tag.rsplit("}", 1)[-1]


def load_fb2(path):
    if zipfile.is_zipfile(path):  # .fb2.zip
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".fb2"))
            data = z.read(name)
    else:
        data = path.read_bytes()
    return ET.fromstring(data)  # honours the encoding in the XML header (often windows-1251)


def inline_text(el):
    """Text of a paragraph, without footnote reference numbers."""
    parts = [el.text or ""]
    for ch in el:
        if not (local(ch.tag) == "a" and ch.get("type") == "note"):
            parts.append(inline_text(ch))
        parts.append(ch.tail or "")
    return re.sub(r"\s+", " ", "".join(parts)).strip()


LEAF_TAGS = {"p", "v", "subtitle", "text-author", "td", "th"}
SKIP_TAGS = {"section", "image", "empty-line", "binary"}


def blocks(el, kind="p"):
    """Yield (text, kind) for every paragraph in el, not descending into child sections."""
    for ch in el:
        tag = local(ch.tag)
        if tag in SKIP_TAGS:
            continue
        if tag in LEAF_TAGS:
            text = inline_text(ch)
            if text:
                yield text, kind
        else:  # title, epigraph, poem, stanza, cite, table, ...
            yield from blocks(ch, "title" if tag == "title" else kind)


def section_title(sec):
    title = next((c for c in sec if local(c.tag) == "title"), None)
    if title is None:
        return ""
    return ". ".join(t for t, _ in blocks(title)).strip()


def extract_chapters(root):
    """Return [(title, [(text, kind), ...])]. A chapter is a section with no sub-sections;
    text of a container section (e.g. "Часть первая" + epigraph) goes to its first chapter."""
    bodies = [b for b in root if local(b.tag) == "body"]
    main = next((b for b in bodies if b.get("name") not in ("notes", "comments")), bodies[0])
    chapters = []

    def walk(sec, carry):
        subs = [c for c in sec if local(c.tag) == "section"]
        own = list(blocks(sec))
        if not subs:
            title = section_title(sec) or f"Глава {len(chapters) + 1}"
            if carry or own:
                chapters.append((title, carry + own))
            return
        pending = carry + own
        for s in subs:
            walk(s, pending)
            pending = []

    top = [c for c in main if local(c.tag) == "section"]
    if not top:
        return [("Книга", list(blocks(main)))]
    for s in top:
        walk(s, [])
    return chapters


def book_info(root):
    def find(el, *path):
        for name in path:
            el = next((c for c in el if local(c.tag) == name), None) if el is not None else None
        return el

    ti = find(root, "description", "title-info")
    title_el = find(ti, "book-title")
    author_el = find(ti, "author")
    title = inline_text(title_el) if title_el is not None else ""
    author = ""
    if author_el is not None:
        names = [inline_text(c) for c in author_el if local(c.tag) in ("first-name", "last-name")]
        author = " ".join(n for n in names if n)
    return title, author


# ---------------------------------------------------------- text normalization

ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def roman_to_int(s):
    total = 0
    for a, b in zip(s, s[1:] + " "):
        v = ROMAN_VALUES[a]
        total += -v if ROMAN_VALUES.get(b, 0) > v else v
    return total


def int_to_roman(n):
    out = ""
    for v, r in [(100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]:
        while n >= v:
            out += r
            n -= v
    return out


def roman_repl(m):
    s = m.group()
    n = roman_to_int(s)
    return num2words(n, lang="ru") if int_to_roman(n) == s else s


TRANSLIT_PAIRS = [("sh", "ш"), ("ch", "ч"), ("zh", "ж"), ("kh", "х"), ("ts", "ц"), ("ya", "я"),
                  ("yu", "ю"), ("th", "т"), ("ph", "ф"), ("oo", "у"), ("ee", "и")]
TRANSLIT_CHARS = dict(zip("abcdefghijklmnopqrstuvwxyz", "абкдефгхийклмнопкрстуввкиз"))
TRANSLIT_CHARS["j"] = "дж"
TRANSLIT_CHARS["x"] = "кс"


def translit(m):
    s = m.group().lower()
    for a, b in TRANSLIT_PAIRS:
        s = s.replace(a, b)
    return "".join(TRANSLIT_CHARS.get(c, c) for c in s)


SYMBOLS = {"%": " процентов", "№": "номер ", "&": " и ", "+": " плюс ", "§": "параграф ",
           "\u00a0": " ", "…": "...", "«": '"', "»": '"', "„": '"', "“": '"', "”": '"'}


def normalize(text):
    """Silero silently drops digits and Latin letters, so spell them out in Cyrillic."""
    for a, b in SYMBOLS.items():
        text = text.replace(a, b)
    text = re.sub(r"\b[IVXLC]{1,7}\b", roman_repl, text)
    text = re.sub(r"\d+", lambda m: " " + num2words(int(m.group()), lang="ru") + " ", text)
    text = re.sub(r"[A-Za-z]+", translit, text)
    return re.sub(r"\s+", " ", text).strip()


def split_chunks(text, limit=MAX_CHUNK):
    """Split into sentence-aligned chunks under the model's length limit."""
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    pieces = []
    for s in sentences:
        while len(s) > limit:  # very long sentence: cut at the last comma/dash/space before the limit
            cut = max(s.rfind(sep, 0, limit) for sep in (", ", "; ", " — ", ": "))
            cut = cut + 1 if cut > limit // 3 else s.rfind(" ", 0, limit)
            pieces.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            pieces.append(s)
    chunks, cur = [], ""
    for p in pieces:
        if cur and len(cur) + len(p) + 1 > limit:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        chunks.append(cur)
    return chunks


# ------------------------------------------------------------------ synthesis

def load_model(device):
    if (HUB_DIR / "hubconf.py").exists():  # offline, from cache
        model, _ = torch.hub.load(str(HUB_DIR), "silero_tts", source="local", language="ru", speaker=MODEL)
    else:
        model, _ = torch.hub.load("snakers4/silero-models", "silero_tts", language="ru",
                                  speaker=MODEL, trust_repo=True)
    model.to(device)
    return model


def silence(seconds):
    return np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)


def synth_chapter(model, voice, paragraphs):
    audio = []
    for text, kind in paragraphs:
        text = normalize(text)
        if not re.search(r"[а-яёА-ЯЁ]", text):  # "* * *" and the like
            audio.append(silence(PAUSE_TITLE))
            continue
        for chunk in split_chunks(text):
            try:
                wav = model.apply_tts(text=chunk, speaker=voice, sample_rate=SAMPLE_RATE)
            except Exception as e:
                print(f"    ! skipped a fragment ({e}): {chunk[:60]}...")
                continue
            audio.append(wav.cpu().numpy().astype(np.float32))
            audio.append(silence(PAUSE_SENTENCE))
        audio.append(silence(PAUSE_TITLE if kind == "title" else PAUSE_PARAGRAPH))
    return np.concatenate(audio) if audio else silence(1)


def write_mp3(audio, path, bitrate, tags):
    tmp = path.with_suffix(".part")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1",
           "-i", "-", "-codec:a", "libmp3lame", "-b:a", bitrate]
    for k, v in tags.items():
        cmd += ["-metadata", f"{k}={v}"]
    cmd += ["-f", "mp3", str(tmp)]
    subprocess.run(cmd, input=audio.tobytes(), check=True)
    tmp.replace(path)


# ------------------------------------------------------------------------ CLI

def parse_only(spec, total):
    if not spec:
        return set(range(1, total + 1))
    chosen = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        chosen.update(range(int(a), int(b or a) + 1))
    return chosen


def safe_name(s, limit=80):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s).strip(" .")
    return s[:limit].rstrip(" .") or "chapter"


def main():
    ap = argparse.ArgumentParser(description="FB2 -> one MP3 per chapter (Silero TTS, Russian)")
    ap.add_argument("book", type=Path, help=".fb2 or .fb2.zip file")
    ap.add_argument("--out", type=Path, help="output folder (default: next to the book)")
    ap.add_argument("--voice", default="eugene", help="aidar, eugene, baya, kseniya, xenia")
    ap.add_argument("--bitrate", default="96k")
    ap.add_argument("--only", help="chapters to render, e.g. 1-3,7")
    ap.add_argument("--list", action="store_true", help="show chapters and exit")
    ap.add_argument("--cpu", action="store_true", help="run on CPU instead of GPU")
    args = ap.parse_args()

    root = load_fb2(args.book)
    chapters = extract_chapters(root)
    title, author = book_info(root)
    title = title or args.book.stem
    width = max(2, len(str(len(chapters))))

    print(f"{author} — {title}: {len(chapters)} chapters")
    if args.list:
        for i, (ch_title, paras) in enumerate(chapters, 1):
            chars = sum(len(t) for t, _ in paras)
            print(f"  {i:>{width}}. {ch_title[:70]}  ({chars:,} chars)")
        return

    out_dir = args.out or args.book.parent / safe_name(f"{author} - {title}" if author else title)
    out_dir.mkdir(parents=True, exist_ok=True)
    selected = parse_only(args.only, len(chapters))

    device = torch.device("cpu" if args.cpu or not torch.cuda.is_available() else "cuda")
    print(f"Loading Silero {MODEL} on {device}...")
    model = load_model(device)

    started = time.time()
    for i, (ch_title, paras) in enumerate(chapters, 1):
        if i not in selected:
            continue
        path = out_dir / f"{i:0{width}d} {safe_name(ch_title)}.mp3"
        if path.exists():
            print(f"[{i}/{len(chapters)}] exists, skipping: {path.name}")
            continue
        t = time.time()
        audio = synth_chapter(model, args.voice, paras)
        write_mp3(audio, path, args.bitrate, {
            "title": ch_title, "album": title, "artist": author,
            "track": f"{i}/{len(chapters)}", "genre": "Audiobook"})
        dur = len(audio) / SAMPLE_RATE
        print(f"[{i}/{len(chapters)}] {path.name}  {dur / 60:.1f} min audio in {time.time() - t:.0f}s")

    print(f"Done in {(time.time() - started) / 60:.1f} min -> {out_dir}")


if __name__ == "__main__":
    main()
