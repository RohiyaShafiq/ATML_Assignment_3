"""CPU unit tests (random tiny Qwen3). Run: python -m pytest tests -q   (or python tests/test_core.py)"""
import math
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import adapters as AD                      # noqa: E402
from common import build_tiny_model, SEED  # noqa: E402
from train import ce_sum, collate, synthetic_data  # noqa: E402


def _randomize(model):
    g = torch.Generator().manual_seed(1)
    for _, m in AD.iter_lora(model):
        m.B.data = torch.randn(m.B.shape, generator=g) * 0.05
        m.A.data = torch.randn(m.A.shape, generator=g) * 0.05


def test_lora_zero_init_equals_base():
    base = build_tiny_model().eval(); x = torch.randint(1, 100, (2, 10))
    ref = base(x).logits
    AD.inject_adapters(base, 4, 8, 0.0, SEED)
    assert torch.allclose(base(x).logits, ref, atol=1e-6)


def test_same_init_for_lora16_and_oplora():
    a, b = build_tiny_model(), build_tiny_model()
    bases = AD.compute_bases(b, 8)
    AD.inject_adapters(a, 16, 32, 0.0, SEED); AD.inject_adapters(b, 16, 32, 0.0, SEED, bases)
    sa, sb = AD.adapter_state(a), AD.adapter_state(b)
    assert all(torch.equal(sa[n]["A"], sb[n]["A"]) for n in sa)


def test_oplora_constraints_and_merge_equivalence():
    m = build_tiny_model().eval(); bases = AD.compute_bases(m, 8)
    AD.inject_adapters(m, 16, 32, 0.0, SEED, bases); _randomize(m)
    proj, chk = AD.export_projected(m)
    assert chk["max_rel_UkT_dW"] < 1e-5 and chk["max_rel_dW_Vk"] < 1e-5
    x = torch.randint(1, 100, (2, 10)); unmerged = m(x).logits
    fresh = build_tiny_model().eval()
    AD.merge_adapters_(fresh, proj, 32 / 16)
    assert torch.allclose(unmerged, fresh(x).logits, atol=1e-4)


def test_plain_lora_merge_equivalence():
    m = build_tiny_model().eval(); AD.inject_adapters(m, 4, 8, 0.0, SEED); _randomize(m)
    x = torch.randint(1, 100, (2, 10)); un = m(x).logits
    fresh = build_tiny_model().eval(); AD.merge_adapters_(fresh, AD.adapter_state(m), 2.0)
    assert torch.allclose(un, fresh(x).logits, atol=1e-4)


def test_loss_masks_prompt_and_padding():
    data = synthetic_data(4); ids, mask, lab = collate(data, [0, 1], 0)
    for j in range(2):
        p = data["prompt_len"][j]; L = len(data["input_ids"][j])
        assert (lab[j, :p] == -100).all() and (lab[j, L:] == -100).all() and (lab[j, p:L] != -100).all()
    logits = torch.randn(2, ids.shape[1], 128)
    n = int((lab[:, 1:] != -100).sum())
    assert math.isfinite(ce_sum(logits, lab).item() / n)


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); print("ok", k)
