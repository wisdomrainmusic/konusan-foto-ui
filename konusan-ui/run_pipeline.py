# konusan-ui/run_pipeline.py
import os
import sys
import time
import glob
import subprocess
from pathlib import Path

try:
    from body_motion import BodyMotionConfig, apply_body_motion
except Exception:
    BodyMotionConfig = None
    apply_body_motion = None

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


def _ffmpeg_pad_audio(input_audio: Path, output_wav: Path):
    """
    Mux için WAV'e dönüştürür.
    (WAV çıkartıyoruz ki mux stabil olsun.)
    """
    cmd = [
        str(FFMPEG_EXE),
        "-y",
        "-i", str(input_audio),
        "-acodec", "pcm_s16le",
        "-ar", "48000",
        "-ac", "2",
        str(output_wav),
    ]
    subprocess.check_call(cmd)


def _ffmpeg_mux_best_audio(
    input_video: Path,
    input_audio_wav: Path,
    output_mp4: Path,
    start_pad_ms: int = 150,
    tail_sec: float = 0.20,
):
    """
    Video stream: copy
    Audio: aac 48kHz 192kbps (kalite fix)
    """
    filter_complex = (
        f"[1:a]adelay={start_pad_ms}|{start_pad_ms}[aud];"
        f"anullsrc=r=48000:cl=stereo:d={tail_sec:.2f}[sil];"
        "[aud][sil]concat=n=2:v=0:a=1[aout]"
    )
    cmd = [
        str(FFMPEG_EXE),
        "-y",
        "-i", str(input_video),
        "-i", str(input_audio_wav),
        "-filter_complex", filter_complex,
        "-map", "0:v:0",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-movflags", "+faststart",
        "-shortest",
        str(output_mp4),
    ]
    subprocess.check_call(cmd)


def run_job(image_path: str, audio_path: str, log_cb=None, body_motion_enabled: bool = False) -> Path:
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
        log_cb("Audio fix: start pad 150ms + tail pad 0.20s")

    _ffmpeg_pad_audio(aud, tmp_padded)
    _ffmpeg_mux_best_audio(newest, tmp_padded, fixed, start_pad_ms=150, tail_sec=0.20)

    # tmp temizle
    try:
        tmp_padded.unlink(missing_ok=True)
    except Exception:
        pass

    if body_motion_enabled:
        if log_cb:
            log_cb("Body Motion: enabled (micro shoulder sway)")
        if apply_body_motion and BodyMotionConfig:
            bm_video = OUT_DIR / f"_tmp_bm_video_{stamp}.mp4"
            bm_muxed = OUT_DIR / f"_tmp_bm_muxed_{stamp}.mp4"
            cfg = BodyMotionConfig(enabled=True)
            bm_ok = apply_body_motion(str(fixed), str(bm_video), cfg, log=log_cb or print)
            if bm_ok:
                cmd = [
                    str(FFMPEG_EXE),
                    "-y",
                    "-i", str(bm_video),
                    "-i", str(fixed),
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-crf", "18",
                    "-c:a", "copy",
                    "-movflags", "+faststart",
                    str(bm_muxed),
                ]
                try:
                    subprocess.check_call(cmd)
                    bm_muxed.replace(fixed)
                except Exception:
                    if log_cb:
                        log_cb("Body Motion skipped: ffmpeg mux failed")
                finally:
                    try:
                        bm_video.unlink(missing_ok=True)
                    except Exception:
                        pass
                    try:
                        bm_muxed.unlink(missing_ok=True)
                    except Exception:
                        pass
            else:
                try:
                    bm_video.unlink(missing_ok=True)
                except Exception:
                    pass
        else:
            if log_cb:
                log_cb("Body Motion skipped: OpenCV not available")

    if log_cb:
        log_cb(f"[DONE] Final video: {fixed}")

    return fixed
