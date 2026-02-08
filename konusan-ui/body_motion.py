from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass
class BodyMotionConfig:
    enabled: bool = False
    amplitude_px: float = 2.0
    freq_hz: float = 0.18
    rotate_deg: float = 0.35
    scale_amt: float = 0.009
    region: str = "lower"
    feather_px: int = 64
    start_ratio: float = 0.32


def _build_alpha_mask(height: int, width: int, cfg: BodyMotionConfig, cv2, np):
    y_start = int(height * cfg.start_ratio)
    alpha = np.zeros((height, width), dtype=np.float32)
    alpha[y_start:height, :] = 1.0

    if cfg.feather_px > 0:
        kernel = max(1, int(cfg.feather_px) * 2 + 1)
        alpha = cv2.GaussianBlur(alpha, (kernel, kernel), 0)

    return np.clip(alpha, 0.0, 1.0)


def apply_body_motion(input_video: str, output_video: str, cfg: BodyMotionConfig, log=print) -> bool:
    if not cfg.enabled:
        return False

    try:
        import cv2
        import numpy as np
    except Exception:
        if log:
            log("Body Motion skipped: OpenCV not available")
        return False

    cap = cv2.VideoCapture(input_video)
    if not cap.isOpened():
        return False

    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    if fps <= 0:
        fps = 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_video, fourcc, fps, (width, height))
    if not writer.isOpened():
        cap.release()
        return False

    if log:
        log(
            "Body Motion ON: amp="
            f"{cfg.amplitude_px}px rot={cfg.rotate_deg}deg scale={cfg.scale_amt}"
        )

    alpha = _build_alpha_mask(height, width, cfg, cv2, np)
    alpha_3 = alpha[:, :, None]
    pivot = (width * 0.5, height * 0.88)

    frame_index = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            t = frame_index / fps
            # BREATH: mostly vertical + tiny lateral
            breath = math.sin(2 * math.pi * cfg.freq_hz * t + 0.8)

            dx = (cfg.amplitude_px * 0.35) * math.sin(
                2 * math.pi * (cfg.freq_hz * 1.9) * t + 0.2
            )
            dy = (cfg.amplitude_px * 1.35) * breath

            angle = cfg.rotate_deg * math.sin(2 * math.pi * (cfg.freq_hz * 0.9) * t + 0.4)
            scale = 1.0 + cfg.scale_amt * (
                0.65 * breath
                + 0.35 * math.sin(2 * math.pi * (cfg.freq_hz * 0.5) * t + 1.3)
            )

            matrix = cv2.getRotationMatrix2D(pivot, angle, scale)
            matrix[0, 2] += dx
            matrix[1, 2] += dy
            shifted = cv2.warpAffine(
                frame,
                matrix,
                (width, height),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT,
            )

            frame_f = frame.astype(np.float32)
            shifted_f = shifted.astype(np.float32)
            blended = shifted_f * alpha_3 + frame_f * (1.0 - alpha_3)
            blended = np.clip(blended, 0, 255).astype(np.uint8)
            writer.write(blended)

            frame_index += 1
    finally:
        cap.release()
        writer.release()

    return True
