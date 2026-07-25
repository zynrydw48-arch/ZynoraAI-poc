"""Build-time script (not shipped app code): downloads exactly the models
NYXUS AI actually uses into a clean, dedicated cache directory for
PyInstaller to bundle -- deliberately NOT the dev machine's real
~/.cache/huggingface or ~/.cache/torch, which have accumulated ~2.5GB of
stale models from earlier PoC experimentation (plain all-MiniLM-L6-v2,
paraphrase-multilingual-MiniLM-L12-v2, a duplicate BLIP snapshot) that must
not bloat the installer.

Run once before each build:
    .venv\\Scripts\\python packaging\\prepare_offline_cache.py
"""

import os
import sys
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent
MODEL_CACHE_DIR = PACKAGING_DIR / "model_cache"

# Must be set before importing anything that touches torch/transformers/
# sentence_transformers, since they read these once at import/first-use time.
os.environ["HF_HOME"] = str(MODEL_CACHE_DIR)
os.environ["TORCH_HOME"] = str(MODEL_CACHE_DIR)

sys.path.insert(0, str(PACKAGING_DIR.parent))

from memoryos.embeddings.sentence_transformer_provider import DEFAULT_MODEL_NAME as EMBEDDING_MODEL_NAME
from memoryos.vision.caption import DEFAULT_MODEL_NAME as CAPTION_MODEL_NAME


def main() -> None:
    MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading into clean cache: {MODEL_CACHE_DIR}")

    print(f"1/3 embedding model: {EMBEDDING_MODEL_NAME}")
    from sentence_transformers import SentenceTransformer

    SentenceTransformer(EMBEDDING_MODEL_NAME)

    print(f"2/3 captioning model: {CAPTION_MODEL_NAME}")
    from transformers import BlipForConditionalGeneration, BlipProcessor

    BlipProcessor.from_pretrained(CAPTION_MODEL_NAME)
    BlipForConditionalGeneration.from_pretrained(CAPTION_MODEL_NAME)

    print("3/3 object-tagging model: MobileNetV2 (torchvision default weights)")
    from torchvision import models

    models.mobilenet_v2(weights=models.MobileNet_V2_Weights.DEFAULT)

    print("Done. Cache contents:")
    for path in sorted(MODEL_CACHE_DIR.rglob("*")):
        if path.is_file():
            size_mb = path.stat().st_size / (1024 * 1024)
            if size_mb > 1:
                print(f"  {size_mb:8.1f} MB  {path.relative_to(MODEL_CACHE_DIR)}")


if __name__ == "__main__":
    main()
