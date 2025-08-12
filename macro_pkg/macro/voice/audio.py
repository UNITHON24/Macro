from __future__ import annotations
import time
import queue
import sounddevice as sd
import webrtcvad
from .config import Config

class AudioStreamer:
    def __init__(self, cfg: Config, frame_q: "queue.Queue[bytes]"):
        self.cfg = cfg
        self.q = frame_q
        self.stream = None
        self.vad = webrtcvad.Vad(cfg.vad_level)
        self.running = False
        self.last_speech_time = time.monotonic()

        self.frame_samples = self.cfg.sample_rate * self.cfg.frame_ms // 1000

    @staticmethod
    def rms_int16(b: bytes) -> float:
        import array
        a = array.array('h', b)
        if not a: return 0.0
        s = sum(x*x for x in a)
        return (s/len(a))**0.5

    def _cb(self, indata, frames, time_info, status):
        b = bytes(indata)
        is_speech = False
        if len(b) == self.frame_samples * 2:
            try:
                if self.vad.is_speech(b, self.cfg.sample_rate) and self.rms_int16(b) >= self.cfg.rms_min_speech:
                    is_speech = True
            except Exception:
                pass
        if is_speech:
            self.last_speech_time = time.monotonic()
        if self.running:
            try: self.q.put_nowait(b)
            except queue.Full: pass

    def start(self):
        if self.running: return
        self.running = True
        self.last_speech_time = time.monotonic()
        self.stream = sd.RawInputStream(
            samplerate=self.cfg.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.frame_samples,
            callback=self._cb
        )
        self.stream.start()

    def stop(self):
        self.running = False
        try:
            if self.stream:
                self.stream.stop()
                self.stream.close()
        finally:
            self.stream = None
        # drain
        try:
            while True: self.q.get_nowait()
        except Exception:
            pass

    def silence_timed_out(self) -> bool:
        return (time.monotonic() - self.last_speech_time) > self.cfg.silence_timeout_sec
