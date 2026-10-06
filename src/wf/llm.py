from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Protocol


class LLM(Protocol):
    def complete(self, prompt: str) -> str: ...


class MockLLM:
    """Deterministic stand-in for tests. Live Qwen is optional."""

    def __init__(self, json_only: bool = False):
        self.json_only = json_only

    def complete(self, prompt: str) -> str:
        if self.json_only or "JSON only" in prompt or '"yes"' in prompt:
            start, end = 0, 0
            m = re.search(r"REGION START (0x[0-9a-fA-F]+) END (0x[0-9a-fA-F]+)", prompt)
            if m:
                start, end = int(m.group(1), 16), int(m.group(2), 16)
            return json.dumps(
                {
                    "yes": True,
                    "role": "pair",
                    "forcing": {"state": "occupancy", "value": 0, "how": "example label only"},
                    "window": "transient",
                    "substrate": "unknown",
                    "confidence": 0.5,
                    "span": [start, end],
                }
            )
        return (
            "void decompile(int *wr_in, int *wr_out) {\n"
            "    wr_out[0] = wr_in[0];\n"
            "}\n"
        )


def _cuda_ok() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


class LocalHF:
    """Qwen via transformers. CUDA if it works, else CPU (device_map=cpu)."""

    def __init__(self, model: str, json_only: bool = False):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.json_only = json_only
        self.tok = AutoTokenizer.from_pretrained(model, trust_remote_code=True)
        self.use_cuda = _cuda_ok()
        # Qwen3-8B weights are bf16. CPU bf16 is the 16GiB path; fp32 would be ~32GiB.
        dtype = torch.bfloat16
        kwargs = {
            "trust_remote_code": True,
            "low_cpu_mem_usage": True,
            "device_map": "auto" if self.use_cuda else "cpu",
        }
        try:
            self.model = AutoModelForCausalLM.from_pretrained(model, dtype=dtype, **kwargs)
        except TypeError:
            self.model = AutoModelForCausalLM.from_pretrained(model, torch_dtype=dtype, **kwargs)
        self.model.eval()

    def _device(self):
        try:
            return next(self.model.parameters()).device
        except StopIteration:
            import torch

            return torch.device("cuda" if self.use_cuda else "cpu")

    def complete(self, prompt: str) -> str:
        import torch

        messages = [{"role": "user", "content": prompt}]
        if hasattr(self.tok, "apply_chat_template"):
            try:
                text = self.tok.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                    enable_thinking=False,
                )
            except TypeError:
                text = self.tok.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
        else:
            text = prompt
        inputs = self.tok(text, return_tensors="pt")
        dev = self._device()
        inputs = {k: v.to(dev) for k, v in inputs.items()}
        jsonish = self.json_only or "JSON only" in prompt
        default = 192 if jsonish else 384
        max_new = int(os.environ.get("WF_MAX_NEW_TOKENS") or default)
        pad = self.tok.eos_token_id
        with torch.inference_mode():
            out = self.model.generate(
                **inputs,
                max_new_tokens=max_new,
                do_sample=False,
                pad_token_id=pad,
            )
        gen = out[0][inputs["input_ids"].shape[-1] :]
        return self.tok.decode(gen, skip_special_tokens=True)


_HF: dict[str, LocalHF] = {}


def make_llm(spec: dict) -> LLM:
    provider = (spec or {}).get("provider", "mock")
    if os.environ.get("WF_LLM") == "mock":
        provider = "mock"
    json_only = bool((spec or {}).get("json_only", False))
    model = (spec or {}).get("model", "models/Qwen3-8B")
    if provider == "mock":
        return MockLLM(json_only=json_only)
    if provider == "local_hf":
        root = Path(__file__).resolve().parents[2]
        path = Path(model)
        if not path.is_absolute():
            path = root / path
        key = str(path)
        if key not in _HF:
            _HF[key] = LocalHF(key, json_only=json_only)
        llm = _HF[key]
        llm.json_only = json_only
        return llm
    raise ValueError(f"unknown llm provider {provider}")
