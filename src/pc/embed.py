"""Embedding (vai `embedder`, mặc định BAAI/bge-m3). Cache theo sha1(text) ở `.cache/emb/<model>.npz`.

Hai cách tính vector còn thiếu:
- `local`: sentence-transformers trên máy (pip install -e ".[embed]"). bge-m3 nặng (~2 GB); máy yếu có thể đổi
  `models.embedder.model` sang model nhỏ hơn, ví dụ intfloat/multilingual-e5-small.
- `gpu`: máy chủ GPU qua SSH. Mật khẩu đọc từ env `GPU_PW`; host, port, user, python ở `config.local.yaml: gpu`.
Vector đã chuẩn hoá L2, lưu float16. Chạy lại không tính lại nếu đã có cache.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

import numpy as np

MAX_CHARS = 4000  # cắt text dài trước khi embed (đủ cho truy xuất, giữ batch nhỏ trên 12 GB)

REMOTE_SCRIPT = r'''
import json, sys, numpy as np, torch
from sentence_transformers import SentenceTransformer
src, dst, model = sys.argv[1], sys.argv[2], sys.argv[3]
texts = [json.loads(l)["t"] for l in open(src, encoding="utf-8")]
m = SentenceTransformer(model, device="cuda")
m.half(); m.max_seq_length = 1024
order = sorted(range(len(texts)), key=lambda i: len(texts[i]))  # gom độ dài gần nhau cho nhanh
vecs = m.encode([texts[i] for i in order], batch_size=32, normalize_embeddings=True, show_progress_bar=False,
                convert_to_numpy=True)
out = np.zeros_like(vecs); out[order] = vecs
np.save(dst, out.astype(np.float16))
print("ok", len(texts), torch.cuda.get_device_name(0))
'''


def _h(text: str) -> str:
    return hashlib.sha1(text[:MAX_CHARS].encode("utf-8")).hexdigest()


class Embedder:
    def __init__(self, cache_dir: Path, gpu: dict, model: str = "BAAI/bge-m3"):
        self.path = Path(cache_dir) / (model.replace("/", "__") + ".npz")
        self.gpu, self.model = gpu, model
        self.keys: dict[str, int] = {}
        self.vecs = np.zeros((0, 1024), dtype=np.float16)
        if self.path.exists():
            d = np.load(self.path)
            self.vecs = d["vecs"]
            self.keys = {k: i for i, k in enumerate(d["keys"].tolist())}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ks = sorted(self.keys, key=self.keys.get)
        tmp = self.path.with_suffix(".tmp.npz")
        np.savez(tmp, keys=np.array(ks), vecs=self.vecs)
        tmp.replace(self.path)

    def missing(self, texts: Iterable[str]) -> list[str]:
        seen, out = set(), []
        for t in texts:
            h = _h(t)
            if h not in self.keys and h not in seen:
                seen.add(h)
                out.append(t)
        return out

    def ensure(self, texts: Iterable[str], log=print, mode: str = "gpu") -> int:
        need = self.missing(texts)
        if not need:
            return 0
        if mode == "local":
            log(f"embed: {len(need)} text mới -> {self.model} trên máy")
            vecs = local_encode([t[:MAX_CHARS] for t in need], self.model)
        else:
            if not self.gpu:
                raise RuntimeError("Chưa cấu hình `gpu` (config.local.yaml). Dùng capsule.embed: local hoặc off.")
            log(f"embed: {len(need)} text mới -> GPU {self.gpu['host']}")
            vecs = remote_encode([t[:MAX_CHARS] for t in need], self.gpu, self.model)
        base = len(self.vecs)
        self.vecs = np.concatenate([self.vecs, vecs.astype(np.float16)]) if base else vecs.astype(np.float16)
        for i, t in enumerate(need):
            self.keys[_h(t)] = base + i
        self._save()
        return len(need)

    def get(self, texts: list[str]) -> np.ndarray:
        idx = [self.keys[_h(t)] for t in texts]  # KeyError nếu chưa ensure
        return self.vecs[idx].astype(np.float32)

    def has(self, text: str) -> bool:
        return _h(text) in self.keys


def local_encode(texts: list[str], model: str) -> np.ndarray:
    from sentence_transformers import SentenceTransformer  # ImportError nếu chưa cài extra [embed]
    m = SentenceTransformer(model)
    return m.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=len(texts) > 500,
                    convert_to_numpy=True).astype(np.float16)


def remote_encode(texts: list[str], gpu: dict, model: str) -> np.ndarray:
    import paramiko

    pw = os.environ.get("GPU_PW")
    if not pw:
        raise RuntimeError("Thiếu env GPU_PW (mật khẩu SSH của GPU server)")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(gpu["host"], port=int(gpu["port"]), username=gpu["user"], password=pw, timeout=30,
              allow_agent=False, look_for_keys=False)
    try:
        wd = gpu.get("workdir", "pc_gpu")
        c.exec_command(f"mkdir -p {wd}")[1].channel.recv_exit_status()
        sftp = c.open_sftp()
        tag = hashlib.sha1("".join(texts[:50]).encode()).hexdigest()[:10]
        with tempfile.TemporaryDirectory() as td:
            src, scr = Path(td) / "in.jsonl", Path(td) / "embed.py"
            src.write_text("".join(json.dumps({"t": t}, ensure_ascii=False) + "\n" for t in texts), encoding="utf-8")
            scr.write_text(REMOTE_SCRIPT, encoding="utf-8")
            sftp.put(str(src), f"{wd}/in_{tag}.jsonl")
            sftp.put(str(scr), f"{wd}/embed.py")
            cmd = (f"cd {wd} && HF_HUB_OFFLINE=1 {gpu['python']} embed.py in_{tag}.jsonl out_{tag}.npy {model}")
            _, out, err = c.exec_command(cmd)
            code = out.channel.recv_exit_status()
            msg = out.read().decode() + err.read().decode()[-2000:]
            if code != 0:
                raise RuntimeError(f"GPU embed lỗi ({code}): {msg}")
            dst = Path(td) / "out.npy"
            sftp.get(f"{wd}/out_{tag}.npy", str(dst))
            c.exec_command(f"rm -f {wd}/in_{tag}.jsonl {wd}/out_{tag}.npy")[1].channel.recv_exit_status()
            vecs = np.load(dst)
        if len(vecs) != len(texts):
            raise RuntimeError("GPU trả về sai số vector")
        return vecs
    finally:
        c.close()


GEN_SCRIPT = r'''
import json, sys, torch
from transformers import AutoModelForCausalLM, AutoTokenizer
src, dst, model = sys.argv[1], sys.argv[2], sys.argv[3]
reqs = [json.loads(l) for l in open(src, encoding="utf-8")]
tok = AutoTokenizer.from_pretrained(model); tok.padding_side = "left"
m = AutoModelForCausalLM.from_pretrained(model, dtype=torch.bfloat16, device_map="cuda").eval()
prompts = [tok.apply_chat_template(r["messages"], tokenize=False, add_generation_prompt=True) for r in reqs]
lens = [len(tok(p).input_ids) for p in prompts]
order = sorted(range(len(reqs)), key=lambda i: lens[i])
BUDGET = int(sys.argv[4]) if len(sys.argv) > 4 else 24000   # token (prompt + sinh) mỗi batch, vừa 12 GB
out = {}
i = 0
with open(dst, "w", encoding="utf-8") as f:
    while i < len(order):
        b = [order[i]]
        while i + len(b) < len(order) and len(b) < 16:
            j = order[i + len(b)]
            mx = max(lens[k] + reqs[k]["max_tokens"] for k in b + [j])
            if mx * (len(b) + 1) > BUDGET:
                break
            b.append(j)
        enc = tok([prompts[k] for k in b], return_tensors="pt", padding=True).to("cuda")
        with torch.no_grad():
            g = m.generate(**enc, max_new_tokens=max(reqs[k]["max_tokens"] for k in b), do_sample=False,
                           pad_token_id=tok.pad_token_id or tok.eos_token_id)
        for row, k in enumerate(b):
            txt = tok.decode(g[row, enc.input_ids.shape[1]:], skip_special_tokens=True)
            f.write(json.dumps({"key": reqs[k]["key"], "text": txt}, ensure_ascii=False) + "\n"); f.flush()
        i += len(b)
        print("done", i, "/", len(order), flush=True)
'''


def remote_generate(reqs: list[dict], gpu: dict, model: str, log=print) -> list[dict]:
    """reqs: [{key, messages, max_tokens}] -> [{key, text}]. Sinh greedy theo batch trên GPU server."""
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(gpu["host"], port=int(gpu["port"]), username=gpu["user"], password=os.environ["GPU_PW"], timeout=30,
              allow_agent=False, look_for_keys=False)
    try:
        wd = gpu.get("workdir", "pc_gpu")
        c.exec_command(f"mkdir -p {wd}")[1].channel.recv_exit_status()
        sftp = c.open_sftp()
        with tempfile.TemporaryDirectory() as td:
            src, scr = Path(td) / "gen_in.jsonl", Path(td) / "gen.py"
            src.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in reqs), encoding="utf-8")
            scr.write_text(GEN_SCRIPT, encoding="utf-8")
            sftp.put(str(src), f"{wd}/gen_in.jsonl")
            sftp.put(str(scr), f"{wd}/gen.py")
            _, out, err = c.exec_command(f"cd {wd} && HF_HUB_OFFLINE=1 {gpu['python']} gen.py gen_in.jsonl gen_out.jsonl "
                                         f"{model} {gpu.get('gen_budget', 24000)}")
            for n, line in enumerate(iter(out.readline, "")):
                if line.startswith("done") and n % 10 == 0:
                    log("gpu gen: " + line.strip())
            code = out.channel.recv_exit_status()
            if code != 0:
                raise RuntimeError(f"GPU generate lỗi ({code}): {err.read().decode()[-2500:]}")
            dst = Path(td) / "gen_out.jsonl"
            sftp.get(f"{wd}/gen_out.jsonl", str(dst))
            return [json.loads(l) for l in dst.read_text(encoding="utf-8").splitlines() if l.strip()]
    finally:
        c.close()


def embedder_from(cfg) -> Embedder:
    return Embedder(cfg.root / ".cache" / "emb", cfg.raw.get("gpu") or {}, cfg.model("embedder")["model"])
