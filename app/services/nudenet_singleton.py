"""Singleton-обёртка над ONNX-моделью NudeNet для NSFW-классификации.

Загружаем модель один раз (через `get_nudenet_detector()` с `lru_cache`).
Если файла нет или он битый — `is_available=False`, все вызовы `score()`
возвращают `None`. Это позволяет сервису модерации мягко уйти в
`manual_review` ( — антипаттерн: падать на отсутствии модели).

Замечание про формат вывода: классическая NudeNet-модель — детектор с
выходом `[B, N, 6]` (x1, y1, x2, y2, conf, class) или классификатор
`[B, num_classes]`. Точный мэппинг классов зависит от конкретного файла,
который положит админ. В этом модуле реализован generic-handler:
вытаскиваем максимальный confidence по «NSFW-подозрительным» столбцам
и возвращаем sigmoid-нормированное значение. Админ при необходимости
адаптирует мэппинг здесь, под свою модель.
"""

from __future__ import annotations

import io
import os
from functools import lru_cache

from loguru import logger

from app.config import settings

# Индексы NSFW-классов для классических NudeNet-моделей (exposed-* категории).
# Если используется другая модель — поправь этот список.
_NSFW_CLASS_INDICES: tuple[int, ...] = (0, 1, 2)


class NudeNetDetector:
    """Тонкая обёртка над `onnxruntime.InferenceSession`.

    Параметры:
        model_path: путь к .onnx-файлу. Если файла нет — детектор остаётся
            «недоступным» (`is_available=False`), `score()` всегда возвращает None.

    Реальный мэппинг классов зависит от конкретной модели; админ должен
    указать корректный путь и при необходимости адаптировать класс-мэппинг
    в этом модуле (см. `_NSFW_CLASS_INDICES`).
    """

    def __init__(self, model_path: str) -> None:
        self._model_path = model_path
        self._session = None  # type: ignore[var-annotated]
        self._input_name: str | None = None
        self._input_shape: tuple[int, ...] | None = None

        if not model_path or not os.path.isfile(model_path):
            logger.warning(
                "NudeNet model file not found at {!r} — detector disabled "
                "(soft fallback to manual_review).",
                model_path,
            )
            return

        try:
            # Импорт внутри метода: onnxruntime тяжёлый, грузим только когда
            # реально собрались инициализировать модель.
            import onnxruntime as ort

            self._session = ort.InferenceSession(
                model_path,
                providers=["CPUExecutionProvider"],
            )
            inp = self._session.get_inputs()[0]
            self._input_name = inp.name
            # Заменяем динамические измерения (None / str) на 1 — батч,
            # и на 320 (дефолт NudeNet) для spatial-осей.
            shape = tuple(
                dim if isinstance(dim, int) and dim > 0 else (1 if i == 0 else 320)
                for i, dim in enumerate(inp.shape)
            )
            self._input_shape = shape
            logger.info(
                "NudeNet ONNX model loaded: path={} input={} shape={}",
                model_path,
                self._input_name,
                shape,
            )
        except Exception as exc:
            logger.error("Failed to load NudeNet model from {}: {}", model_path, exc)
            self._session = None

    @property
    def is_available(self) -> bool:
        return self._session is not None

    def score(self, image_bytes: bytes) -> float | None:
        """Вернуть NSFW-вероятность 0..1 или None при недоступности/ошибке."""
        if self._session is None or self._input_name is None or self._input_shape is None:
            return None
        try:
            import numpy as np
            from PIL import Image

            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            # NCHW-формат: [B, C, H, W]; берём H/W из shape[-2:].
            target_h = int(self._input_shape[-2]) if len(self._input_shape) >= 2 else 320
            target_w = int(self._input_shape[-1]) if len(self._input_shape) >= 1 else 320
            if target_h <= 0:
                target_h = 320
            if target_w <= 0:
                target_w = 320
            img = img.resize((target_w, target_h))

            arr = np.asarray(img, dtype=np.float32) / 255.0  # H, W, C
            arr = np.transpose(arr, (2, 0, 1))  # C, H, W
            arr = np.expand_dims(arr, axis=0)  # 1, C, H, W

            outputs = self._session.run(None, {self._input_name: arr})
            if not outputs:
                return None
            out = np.asarray(outputs[0])

            return _extract_nsfw_score(out)
        except Exception as exc:
            logger.error("NudeNet inference failed: {}", exc)
            return None


def _extract_nsfw_score(out) -> float | None:  # type: ignore[no-untyped-def]
    """Generic-постобработка выхода NudeNet.

    - Если выход 3D `[B, N, 6]` (детектор bbox+conf+class) — берём максимум
      по confidence-столбцу детекций, у которых class ∈ _NSFW_CLASS_INDICES.
      Fallback: max по всему выходу.
    - Если выход 2D `[B, num_classes]` (классификатор) — берём max по
      индексам _NSFW_CLASS_INDICES (в пределах num_classes).
    - В остальных случаях — `min(max(out), 1.0)`.

    Результат клиппуется в [0.0, 1.0].
    """
    try:
        import numpy as np
    except Exception:
        return None

    arr = np.asarray(out)
    if arr.size == 0:
        return None

    score: float | None = None

    if arr.ndim == 3 and arr.shape[-1] >= 6:
        # [B, N, 6]: cols 0..3 — bbox, 4 — conf, 5 — class id.
        flat = arr.reshape(-1, arr.shape[-1])
        classes = flat[:, 5].astype(int)
        confs = flat[:, 4].astype(float)
        mask = np.isin(classes, np.asarray(_NSFW_CLASS_INDICES, dtype=int))
        if mask.any():
            score = float(confs[mask].max())
        else:
            score = float(confs.max()) if confs.size else float(flat.max())
    elif arr.ndim == 2:
        # [B, num_classes]
        num_classes = arr.shape[1]
        idxs = [i for i in _NSFW_CLASS_INDICES if i < num_classes]
        if idxs:
            score = float(arr[:, idxs].max())
        else:
            score = float(arr.max())
    else:
        score = float(arr.max())

    if score is None:
        return None
    # Клипуем в [0, 1] — некоторые модели возвращают логиты/чуть выше единицы.
    if score < 0.0:
        score = 0.0
    if score > 1.0:
        score = 1.0
    return score


@lru_cache(maxsize=1)
def get_nudenet_detector() -> NudeNetDetector:
    """Singleton-фабрика. Модель грузится при первом вызове, не на импорте."""
    return NudeNetDetector(settings.nudenet_model_path)
