"""Generate a portable, offline planning and recording guide."""
from importlib.resources import files
from pathlib import Path
import webbrowser


def open_guide(destination: Path | None = None) -> Path:
    """Create without overwriting existing work; opening a browser is best effort."""
    html = files("explain_video").joinpath("guide.html").read_text(encoding="utf-8")
    base = (destination or Path("recording-guide.html")).absolute()
    number = 1
    while True:
        target = base if number == 1 else base.with_name(f"{base.stem}-{number}{base.suffix}")
        try:
            with target.open("x", encoding="utf-8") as stream:
                stream.write(html)
            break
        except FileExistsError:
            number += 1
    print(f"Recording guide: {target}")
    print(f"Open in your browser: {target.as_uri()}")
    print('After recording, run: ./run "path/to/video.mp4"')
    try:
        webbrowser.open(target.as_uri())
    except webbrowser.Error:
        pass
    return target
