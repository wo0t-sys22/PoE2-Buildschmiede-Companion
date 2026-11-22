"""Play local MP4s in a Tk preview with an optional FFmpeg installation."""

import queue
import subprocess
from threading import Event, Thread
import tkinter as tk


class ClipPreview(tk.Label):
    FPS = 30

    def __init__(self, parent, executable, path, width, background):
        super().__init__(parent, bg=background, bd=0, highlightthickness=0)
        width = max(2, width // 2 * 2)
        height = max(2, round(width * 9 / 16 / 2) * 2)
        self.header = f"P6\n{width} {height}\n255\n".encode("ascii")
        self.image = tk.PhotoImage(master=self, width=width, height=height)
        self.configure(image=self.image)
        self.frames = queue.Queue(maxsize=2)
        self.stopped = Event()
        self.timer = None
        filters = (f"fps={self.FPS},scale={width}:{height}:force_original_aspect_ratio=decrease,"
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1")
        try:
            self.process = subprocess.Popen(
                [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-stream_loop", "-1",
                 "-i", str(path), "-an", "-sn", "-dn", "-vf", filters,
                 "-threads:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            self.destroy()
            raise
        self.bind("<Unmap>", self.stop)
        self.bind("<Destroy>", self.stop)
        Thread(target=self._read, args=(width * height * 3,), name="boss-clip-preview", daemon=True).start()
        self.timer = self.after(0, self._next)

    def _read(self, size):
        with self.process.stdout as stream:
            while not self.stopped.is_set():
                pixels = stream.read(size)
                if len(pixels) != size:
                    break
                while not self.stopped.is_set():
                    try:
                        self.frames.put(pixels, timeout=0.1)
                        break
                    except queue.Full:
                        pass
        self.process.wait()

    def _next(self):
        self.timer = None
        try:
            pixels = self.frames.get_nowait()
        except queue.Empty:
            if self.process.poll() is not None:
                return
            delay = 10
        else:
            self.image.configure(data=self.header + pixels, format="ppm")
            delay = round(1000 / self.FPS)
        self.timer = self.after(delay, self._next)

    def stop(self, event=None):
        if self.stopped.is_set():
            return
        self.stopped.set()
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        if self.process.poll() is None:
            self.process.terminate()
