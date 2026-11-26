# Define, train, and load a local text model with PyTorch. Generation turns input tokens into output tokens.
"""Local GPT model, tokenizer, and training loop."""

import json
import re
import os
import math
from pathlib import Path
from collections import Counter

import torch
import torch.nn as nn
import torch.nn.functional as F


# ---------------- Configuration ----------------

CFG = dict(
    vocab=1024,
    ctx=256,
    dim=384,
    heads=6,
    layers=6,
    batch=16,
    accum=2,
    lr=3e-4,
    steps=5000,
    warmup=200,
    eval_every=250,
)

DEV = (
    "cuda" if torch.cuda.is_available()
    else ("mps" if torch.backends.mps.is_available() else "cpu")
)


# ---------------- Byte-level BPE tokenizer ----------------

class BPE:
    def __init__(self):
        self.merges = {}
        self.vocab = {i: bytes([i]) for i in range(256)}

    @staticmethod
    def _merge(ids, pair, new_id):
        out = []
        i = 0
        while i < len(ids):
            if i + 1 < len(ids) and (ids[i], ids[i + 1]) == pair:
                out.append(new_id)
                i += 2
            else:
                out.append(ids[i])
                i += 1
        return out

    def train(self, text, vocab_size, min_tokens=0):
        ids = list(text.encode("utf-8"))
        for new_id in range(256, vocab_size):
            if len(ids) <= min_tokens:
                break
            pairs = Counter(zip(ids, ids[1:]))
            if not pairs:
                break
            pair = max(pairs, key=pairs.get)
            self.merges[pair] = new_id
            self.vocab[new_id] = self.vocab[pair[0]] + self.vocab[pair[1]]
            ids = self._merge(ids, pair, new_id)
        return ids

    def encode(self, text):
        if text is None:
            return []
        text = str(text)
        ids = list(text.encode("utf-8"))
        while len(ids) >= 2:
            pair = min(
                zip(ids, ids[1:]),
                key=lambda p: self.merges.get(p, float("inf")),
            )
            if pair not in self.merges:
                break
            ids = self._merge(ids, pair, self.merges[pair])
        return ids

    def decode(self, ids):
        if ids is None:
            return ""
        raw = b"".join(self.vocab[int(i)] for i in ids if int(i) in self.vocab)
        return raw.decode("utf-8", errors="replace")


# ---------------- Transformer components ----------------

class RMSNorm(nn.Module):
    def __init__(self, dim, eps=1e-6):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(dim))
        self.eps = eps

    def forward(self, x):
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps) * self.weight


def rope_cache(seq_len, head_dim, base=10000.0):
    frequencies = 1.0 / (
        base ** (torch.arange(0, head_dim, 2).float() / head_dim)
    )
    angles = torch.outer(torch.arange(seq_len).float(), frequencies)
    return angles.cos(), angles.sin()


def apply_rope(x, cos, sin):
    # x shape: batch, heads, sequence, head_dim
    x_even = x[..., 0::2]
    x_odd = x[..., 1::2]
    return torch.stack(
        [
            x_even * cos - x_odd * sin,
            x_even * sin + x_odd * cos,
        ],
        dim=-1,
    ).flatten(-2)


class Attention(nn.Module):
    def __init__(self, dim, heads):
        super().__init__()
        if dim % heads:
            raise ValueError("dim must be divisible by heads")
        self.heads = heads
        self.qkv = nn.Linear(dim, 3 * dim, bias=False)
        self.out = nn.Linear(dim, dim, bias=False)

    def forward(self, x, cos, sin, cache=None):
        batch, seq_len, dim = x.shape
        head_dim = dim // self.heads

        q, k, v = (
            self.qkv(x)
            .view(batch, seq_len, 3, self.heads, head_dim)
            .permute(2, 0, 3, 1, 4)
        )

        offset = cache["k"].size(2) if cache is not None and "k" in cache else 0
        q = apply_rope(q, cos[offset:offset + seq_len], sin[offset:offset + seq_len])
        k = apply_rope(k, cos[offset:offset + seq_len], sin[offset:offset + seq_len])

        if cache is not None:
            if "k" in cache:
                k = torch.cat([cache["k"], k], dim=2)
                v = torch.cat([cache["v"], v], dim=2)
            cache["k"], cache["v"] = k, v

        source_len = k.size(2)
        scores = (q @ k.transpose(-2, -1)) / math.sqrt(head_dim)

        # For a cached one-token query, all cached/current keys are visible.
        # For a multi-token prefill, preserve the causal mask.
        mask = torch.triu(
            torch.ones(seq_len, source_len, device=x.device, dtype=torch.bool),
            diagonal=source_len - seq_len + 1,
        )
        scores = scores.masked_fill(mask, float("-inf"))
        weights = scores.softmax(dim=-1)
        result = (weights @ v).transpose(1, 2).reshape(batch, seq_len, dim)
        return self.out(result)


class SwiGLU(nn.Module):
    def __init__(self, dim):
        super().__init__()
        hidden_dim = max(64, int(8 * dim / 3 / 64) * 64)
        self.gate = nn.Linear(dim, hidden_dim, bias=False)
        self.value = nn.Linear(dim, hidden_dim, bias=False)
        self.proj = nn.Linear(hidden_dim, dim, bias=False)

    def forward(self, x):
        return self.proj(F.silu(self.gate(x)) * self.value(x))


class Block(nn.Module):
    def __init__(self, dim, heads):
        super().__init__()
        self.norm1 = RMSNorm(dim)
        self.norm2 = RMSNorm(dim)
        self.attn = Attention(dim, heads)
        self.mlp = SwiGLU(dim)

    def forward(self, x, cos, sin, cache=None):
        x = x + self.attn(self.norm1(x), cos, sin, cache)
        return x + self.mlp(self.norm2(x))


class GPT(nn.Module):
    def __init__(self, vocab, ctx, dim, heads, layers, **_):
        super().__init__()
        self.ctx = ctx
        self.emb = nn.Embedding(vocab, dim)
        self.blocks = nn.ModuleList(Block(dim, heads) for _ in range(layers))
        self.norm = RMSNorm(dim)
        self.head = nn.Linear(dim, vocab, bias=False)
        self.head.weight = self.emb.weight  # tied input/output embeddings

        cos, sin = rope_cache(ctx, dim // heads)
        self.register_buffer("cos", cos, persistent=False)
        self.register_buffer("sin", sin, persistent=False)
        self.apply(self._init_weights)

    @staticmethod
    def _init_weights(module):
        if isinstance(module, (nn.Linear, nn.Embedding)):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(self, idx, targets=None, caches=None):
        x = self.emb(idx)
        for i, block in enumerate(self.blocks):
            cache = None if caches is None else caches[i]
            x = block(x, self.cos, self.sin, cache)
        logits = self.head(self.norm(x))
        loss = None
        if targets is not None:
            loss = F.cross_entropy(
                logits.reshape(-1, logits.size(-1)),
                targets.reshape(-1),
            )
        return logits, loss

    @torch.no_grad()
    def generate(self, idx, max_new_tokens, temp=0.8, top_k=50, stop=None):
        self.eval()
        caches = [{} for _ in self.blocks]
        inp = idx[:, -self.ctx:]

        for _ in range(max_new_tokens):
            cached_len = caches[0]["k"].size(2) if caches[0] else 0
            if cached_len + inp.size(1) > self.ctx:
                # Rebuild cache from a recent window when context is full.
                caches = [{} for _ in self.blocks]
                inp = idx[:, -self.ctx:]

            logits, _ = self(inp, caches=caches)
            logits = logits[:, -1, :] / max(float(temp), 1e-5)

            if top_k and 0 < top_k < logits.size(-1):
                values, _ = torch.topk(logits, top_k)
                logits = logits.masked_fill(logits < values[:, -1:], float("-inf"))

            next_token = torch.multinomial(logits.softmax(dim=-1), num_samples=1)
            idx = torch.cat([idx, next_token], dim=1)
            inp = next_token

            if stop is not None and next_token.numel() == 1 and next_token.item() == stop:
                break

        return idx


# ---------------- Training ----------------

def lr_at(step, config):
    if step < config["warmup"]:
        return config["lr"] * (step + 1) / max(1, config["warmup"])
    progress = (step - config["warmup"]) / max(
        1, config["steps"] - config["warmup"]
    )
    return config["lr"] * (
        0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * progress))
    )


def load_training_text(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8")
    if not path.is_dir():
        raise FileNotFoundError(f"Training input not found: {path}")

    sources = sorted(
        source for source in path.rglob("*")
        if source.is_file() and source.suffix.lower() in {".txt", ".md", ".yaml", ".yml"}
    )
    return "\n\n".join(source.read_text(encoding="utf-8").strip() for source in sources)


def train(path, output_directory):
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    config = CFG.copy()
    text = load_training_text(Path(path))
    if not text.strip():
        raise ValueError("Training input contains no text.")

    tokenizer = BPE()
    print("Training tokenizer (pure Python; large files may take time)...")
    tokenizer_text = text[:300_000]
    minimum_tokens = min(
        len(tokenizer_text.encode("utf-8")),
        config["ctx"] * 2 + 2,
    )
    tokenizer.train(tokenizer_text, config["vocab"], minimum_tokens)
    # Ensure the model vocabulary matches the IDs actually produced by BPE.
    actual_vocab = max(tokenizer.vocab.keys()) + 1
    config["vocab"] = max(256, actual_vocab)

    data_ids = tokenizer.encode(text)
    if len(data_ids) < config["ctx"] + 2:
        config["ctx"] = min(config["ctx"], max(8, (len(data_ids) - 2) // 2))

    if len(data_ids) <= config["ctx"] + 1:
        raise ValueError(
            f"Not enough tokens ({len(data_ids)}) for context length {config['ctx']}. "
            "Add more training text or reduce CFG['ctx']."
        )

    if len(data_ids) < config["ctx"] * 4:
        config["ctx"] = min(config["ctx"], max(16, len(data_ids) // 4))
        config.update(
            dim=96,
            heads=4,
            layers=2,
            batch=4,
            accum=1,
            steps=100,
            warmup=10,
            eval_every=25,
        )
        print(
            "Small corpus detected; using a compact model "
            f"(context={config['ctx']}, steps={config['steps']})."
        )

    data = torch.tensor(data_ids, dtype=torch.long)
    split = max(1, int(0.95 * len(data)))
    train_data, val_data = data[:split], data[split:]
    if len(val_data) <= config["ctx"] + 1:
        val_data = train_data

    print(f"{len(data):,} tokens | device={DEV} | vocab={config['vocab']}")
    model = GPT(**config).to(DEV)
    print(f"{sum(p.numel() for p in model.parameters()) / 1e6:.2f}M parameters")

    decay = [p for p in model.parameters() if p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.dim() < 2]
    optimizer = torch.optim.AdamW(
        [
            {"params": decay, "weight_decay": 0.1},
            {"params": no_decay, "weight_decay": 0.0},
        ],
        lr=config["lr"],
        betas=(0.9, 0.95),
    )

    def get_batch(source):
        max_start = len(source) - config["ctx"] - 1
        if max_start <= 0:
            source = train_data
            max_start = len(source) - config["ctx"] - 1
        starts = torch.randint(max_start + 1, (config["batch"],))
        x = torch.stack([source[i:i + config["ctx"]] for i in starts])
        y = torch.stack([source[i + 1:i + config["ctx"] + 1] for i in starts])
        return x.to(DEV), y.to(DEV)

    @torch.no_grad()
    def evaluate():
        model.eval()
        losses = []
        for _ in range(10):
            x, y = get_batch(val_data)
            _, loss = model(x, y)
            losses.append(loss.item())
        model.train()
        return sum(losses) / len(losses)

    use_bf16 = DEV == "cuda" and torch.cuda.is_bf16_supported()
    for step in range(config["steps"]):
        for group in optimizer.param_groups:
            group["lr"] = lr_at(step, config)
        optimizer.zero_grad(set_to_none=True)

        last_loss = None
        for _ in range(config["accum"]):
            x, y = get_batch(train_data)
            with torch.autocast(
                device_type="cuda",
                dtype=torch.bfloat16,
                enabled=use_bf16,
            ):
                _, loss = model(x, y)
            (loss / config["accum"]).backward()
            last_loss = loss

        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()

        if step % config["eval_every"] == 0 or step == config["steps"] - 1:
            val_loss = evaluate()
            print(
                f"step {step:5d} | train {last_loss.item():.3f} | "
                f"val {val_loss:.3f}"
            )
            torch.save({"model": model.state_dict(), "cfg": config}, output_directory / "model.pt")
            with (output_directory / "tokenizer.json").open("w", encoding="utf-8") as f:
                json.dump([[left, right, new_id] for (left, right), new_id in tokenizer.merges.items()], f)

    print("Training complete. Saved model.pt and tokenizer.json.")


# ---------------- Loading ----------------

def load_tok(path):
    with open(path, encoding="utf-8") as f:
        merges = {(left, right): new_id for left, right, new_id in json.load(f)}
    tokenizer = BPE()
    tokenizer.merges = merges
    for (left, right), new_id in sorted(merges.items(), key=lambda item: item[1]):
        tokenizer.vocab[new_id] = tokenizer.vocab[left] + tokenizer.vocab[right]
    return tokenizer


def load_model(path):
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Model checkpoint '{path}' not found. Run: python {os.path.basename(__file__)} train data.txt"
        )
    checkpoint = torch.load(path, map_location=DEV, weights_only=True)
    model = GPT(**checkpoint["cfg"]).to(DEV)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    return model


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Train the local document model")
    parser.add_argument("training_text", type=Path, help="Text file or directory of text, Markdown, and YAML files")
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    train(args.training_text, args.output_directory)
