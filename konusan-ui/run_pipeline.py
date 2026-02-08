# konusan-ui/run_pipeline.py
import os
import sys
import time
import glob
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]  # C:\konusan-foto-portable-clean
PYTHON_EXE = ROOT / "python" / "python.exe"
SADTALKER_DIR = ROOT / "SadTalker"
SADTALKER_INFER = SADTALKER_DIR / "inference.py"
FFMPEG_EXE = ROOT / "ffmpeg" / "ffmpeg.exe"

OUT_DIR = ROOT / "output_ui"


def _ensure_paths():
    if not PYTHON_EXE.exists():
        raise FileNotFoundError(f"python.exe not found: {PYTHON_EXE}")
    if not SADTALKER_INFER.exists():
        raise FileNotFoundError(f"SadTalker inference.py not found: {SADTALKER_INFER}")
    if not FFMPEG_EXE.exists():
        raise FileNotFoundError(f"ffmpeg.exe not found: {FFMPEG_EXE}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def _newest_mp4(search_root: Path) -> Path | None:
    mp4s = glob.glob(str(search_root / "**" / "*.mp4"), recursive=True)
    # SadTalker bazen ara mp4 üretir; yine de en yenisini alıyoruz
    if not mp4s:
        return None
    mp4s.sort(key=lambda p: os.path.getmtime(p))
    return Path(mp4s[-1])


def _run_sadtalker(image_path: Path, audio_path: Path, result_dir: Path, still=True, preprocess="full"):
    """
    SadTalker'ı portable python ile koşar.
    src import problemi yaşamamak için runpy ile inference.py'yi __main__ olarak çalıştırıyoruz
    ve sys.path içine SadTalker kökünü ekliyoruz.
    """
    # SadTalker argümanları
    args = [
        "--driven_audio", str(audio_path),
        "--source_image", str(image_path),
        "--result_dir", str(result_dir),
        "--preprocess", preprocess,
    ]
    if still:
        args.append("--still")

    # ffmpeg PATH
    env = os.environ.copy()
    env["PATH"] = str(FFMPEG_EXE.parent) + ";" + env.get("PATH", "")

    # Python -c komutu: sys.path insert + sys.argv set + runpy
    code = (
        "import sys, runpy;"
        f"sys.path.insert(0, r'{SADTALKER_DIR.as_posix()}');"
        f"sys.argv=['inference.py']+{args!r};"
        f"runpy.run_path(r'{SADTALKER_INFER.as_posix()}', run_name='__main__')"
    )

    cmd = [str(PYTHON_EXE), "-c", code]
    # Çalışma dizini SadTalker olmalı
    proc = subprocess.Popen(
        cmd,
        cwd=str(SADTALKER_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    return proc


def _ffmpeg_pad_audio(input_audio: Path, output_wav: Path, pad_ms: int = 150):
    """
    İlk kelimeyi yememesi için başa ~150ms sessizlik ekler.
    (WAV çıkartıyoruz ki mux stabil olsun.)
    """
    cmd = [
        str(FFMPEG_EXE),
        "-y",
        "-i", str(input_audio),
        "-af", f"adelay={pad_ms}|{pad_ms}",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "1",
        str(output_wav),
    ]
    subprocess.check_call(cmd)


def _ffmpeg_mux_best_audio(input_video: Path, input_audio_wav: Path, output_mp4: Path):
    """
    Video stream: copy
    Audio: aac 48kHz 192kbps (kalite fix)
    """
    cmd = [
        str(FFMPEG_EXE),
        "-y",
        "-i", str(input_video),
        "-i", str(input_audio_wav),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-movflags", "+faststart",
        "-shortest",
        str(output_mp4),
    ]
    subprocess.check_call(cmd)


def run_job(image_path: str, audio_path: str, log_cb=None) -> Path:
    """
    UI burayı çağıracak. Bittiğinde FINAL_fixed.mp4 döner.
    """
    _ensure_paths()

    img = Path(image_path)
    aud = Path(audio_path)
    if not img.exists():
        raise FileNotFoundError(f"Image not found: {img}")
    if not aud.exists():
        raise FileNotFoundError(f"Audio not found: {aud}")

    # SadTalker kendi içinde tarihli klasör açıyor; biz result_dir'i sabit veriyoruz.
    result_dir = ROOT / "test" / "out"
    result_dir.mkdir(parents=True, exist_ok=True)

    if log_cb:
        log_cb(f"[INFO] Running SadTalker...\n  IMG={img}\n  AUD={aud}\n  OUT={result_dir}\n")

    proc = _run_sadtalker(img, aud, result_dir, still=True, preprocess="full")

    # canlı log
    while True:
        line = proc.stdout.readline() if proc.stdout else ""
        if line:
            if log_cb:
                log_cb(line.rstrip("\n"))
        if proc.poll() is not None:
            # kalan çıktıyı boşalt
            if proc.stdout:
                rest = proc.stdout.read()
                if rest and log_cb:
                    for ln in rest.splitlines():
                        log_cb(ln)
            break

    # SadTalker mp4'ü bul
    newest = _newest_mp4(result_dir)
    if newest is None or not newest.exists():
        raise RuntimeError("SadTalker output mp4 not found in result_dir.")

    if log_cb:
        log_cb(f"[OK] SadTalker produced: {newest}")

    # Audio kalite + ilk kelime fix
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    fixed = OUT_DIR / f"FINAL_fixed_{stamp}.mp4"

    tmp_padded = OUT_DIR / f"_tmp_padded_{stamp}.wav"
    if log_cb:
        log_cb("[INFO] Fixing audio (pad + re-encode)...")

    _ffmpeg_pad_audio(aud, tmp_padded, pad_ms=150)
    _ffmpeg_mux_best_audio(newest, tmp_padded, fixed)

    # tmp temizle
    try:
        tmp_padded.unlink(missing_ok=True)
    except Exception:
        pass

    if log_cb:
        log_cb(f"[DONE] Final video: {fixed}")

    return fixed
