"""Turn the recorded demo (demo/raw.webm + demo/markers.json, from frontend/e2e/demo-video.spec.ts) into:
  demo/ai-interview-coach-demo.mp4  H.264 + faststart: uploads cleanly to LinkedIn and GitHub
  demo/ai-interview-coach-demo.gif  ~20 s highlight (interview + report) for the README
  demo/poster.png                   thumbnail from the title slide

Usage (from backend/, needs `pip install imageio-ffmpeg`):  python -m scripts.make_demo_video
"""

import json
import subprocess
import sys

import imageio_ffmpeg

from app.config import ROOT_DIR

DEMO = ROOT_DIR / "demo"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def run(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def main() -> None:
    raw = DEMO / "raw.webm"
    if not raw.exists():
        sys.exit(f"{raw} not found: record it first with REAL_DEMO=1 npx playwright test e2e/demo-video.spec.ts")
    m = json.loads((DEMO / "markers.json").read_text(encoding="utf-8"))

    mp4 = DEMO / "ai-interview-coach-demo.mp4"
    run("-i", str(raw), "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-r", "30", str(mp4))

    run("-ss", str(m["title"] + 2), "-i", str(raw), "-frames:v", "1", str(DEMO / "poster.png"))

    # README GIF: the first stretch of the interview, then the report; 960 px wide, 10 fps, shared palette
    start, length = m["interview"], min(20.0, m["slides"] - m["interview"])
    gif = DEMO / "ai-interview-coach-demo.gif"
    palette = DEMO / "palette.png"
    filters = "fps=10,scale=960:-1:flags=lanczos"
    run("-ss", str(start), "-t", str(length), "-i", str(raw), "-vf", f"{filters},palettegen=stats_mode=diff", str(palette))
    run("-ss", str(start), "-t", str(length), "-i", str(raw), "-i", str(palette),
        "-lavfi", f"{filters}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4", str(gif))
    palette.unlink()

    for f in (mp4, gif, DEMO / "poster.png"):
        print(f"{f.name}: {f.stat().st_size / 1e6:.1f} MB")
    print(f"Video length: {m['end']:.0f} s")


if __name__ == "__main__":
    main()
