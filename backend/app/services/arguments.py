from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ArgumentCatalog
from app.schemas import AppSettings, CatalogArgumentInput


BUILTIN_ARGUMENTS: list[tuple[list[str], str, str, str]] = [
    (["-h", "--help", "--usage"], "", "显示帮助后退出，不用于常驻服务", "diagnostics"),
    (["-cl", "--cache-list"], "", "显示本地模型缓存清单后退出", "diagnostics"),
    (["-c", "--ctx-size"], "N", "上下文容量，0 表示读取模型元数据", "context"),
    (["-n", "--predict", "--n-predict"], "N", "服务默认最大输出 token 数", "context"),
    (["-b", "--batch-size"], "N", "逻辑最大 batch size，主要影响 Prefill", "performance"),
    (["-ub", "--ubatch-size"], "N", "物理 micro-batch size", "performance"),
    (["-t", "--threads"], "N", "生成阶段 CPU 线程数", "cpu"),
    (["-tb", "--threads-batch"], "N", "Prompt/batch 阶段 CPU 线程数", "cpu"),
    (["-C", "--cpu-mask"], "MASK", "生成线程 CPU affinity mask", "cpu"),
    (["-Cr", "--cpu-range"], "LO-HI", "生成线程 CPU 范围", "cpu"),
    (["-Cb", "--cpu-mask-batch"], "MASK", "Prompt/batch 线程 CPU affinity mask", "cpu"),
    (["-Crb", "--cpu-range-batch"], "LO-HI", "Prompt/batch 线程 CPU 范围", "cpu"),
    (["-lcs", "--lookup-cache-static"], "PATH", "lookup decoding 静态缓存文件", "performance"),
    (["-lcd", "--lookup-cache-dynamic"], "PATH", "lookup decoding 动态缓存文件", "performance"),
    (["-ctxcp", "--ctx-checkpoints", "--swa-checkpoints"], "N", "每个 slot 的最大 context checkpoint 数", "context"),
    (["-cms", "--checkpoint-min-step"], "N", "context checkpoint 的最小 token 间隔", "context"),
    (["-cram", "--cache-ram"], "MIB", "RAM prompt cache 上限", "kv-cache"),
    (["-kvu", "--kv-unified"], "", "所有序列使用统一 KV buffer", "kv-cache"),
    (["-ngl", "--gpu-layers", "--n-gpu-layers"], "N|auto|all", "放入显存的模型层数", "gpu"),
    (["-dev", "--device"], "DEVICES", "用于 offload 的设备列表", "gpu"),
    (["-sm", "--split-mode"], "none|layer|row|tensor", "多 GPU 切分模式", "gpu"),
    (["-ts", "--tensor-split"], "N0,N1,...", "各 GPU 的切分比例", "gpu"),
    (["-mg", "--main-gpu"], "INDEX", "主 GPU 序号", "gpu"),
    (["-ot", "--override-tensor"], "PATTERN=TYPE", "覆盖匹配 tensor 的 buffer 类型", "gpu"),
    (["-cmoe", "--cpu-moe"], "", "将全部 MoE 权重保留在 CPU", "cpu"),
    (["-ncmoe", "--n-cpu-moe"], "N", "将前 N 层 MoE 权重保留在 CPU", "cpu"),
    (["-fit", "--fit"], "", "自动适配设备可用内存", "gpu"),
    (["-fitt", "--fit-target"], "N0,N1,...", "各设备自动适配时保留的内存目标", "gpu"),
    (["-fitc", "--fit-ctx"], "N", "自动适配可设置的最小 context", "gpu"),
    (["-fa", "--flash-attn"], "on|off|auto", "Flash Attention 模式", "performance"),
    (["-kvo", "--kv-offload"], "", "启用 KV cache offload", "kv-cache"),
    (["-nkvo", "--no-kv-offload"], "", "禁用 KV cache offload", "kv-cache"),
    (["-nr", "--no-repack"], "", "禁用权重 repack", "memory"),
    (["-ctk", "--cache-type-k"], "TYPE", "K cache 数据类型", "kv-cache"),
    (["-ctv", "--cache-type-v"], "TYPE", "V cache 数据类型", "kv-cache"),
    (["-dt", "--defrag-thold"], "N", "KV cache 碎片整理阈值（已弃用）", "kv-cache"),
    (["-dio", "--direct-io"], "", "使用 direct I/O（已弃用，优先使用 load-mode）", "memory"),
    (["-ndio", "--no-direct-io"], "", "禁用 direct I/O（已弃用）", "memory"),
    (["-lm", "--load-mode"], "MODE", "模型加载模式", "memory"),
    (["-np", "--parallel"], "N", "server slot / 并行序列数", "server"),
    (["-cb", "--cont-batching"], "", "启用连续 batching", "server"),
    (["-nocb", "--no-cont-batching"], "", "禁用连续 batching", "server"),
    (["-p", "--prompt"], "TEXT", "服务默认 prompt", "sampling"),
    (["-f", "--file"], "PATH", "从文本文件读取默认 prompt", "sampling"),
    (["-bf", "--binary-file"], "PATH", "从二进制文件读取默认 prompt", "sampling"),
    (["-e", "--escape"], "", "处理 prompt 中的转义序列", "sampling"),
    (["-r", "--reverse-prompt"], "TEXT", "反向提示/停止文本", "sampling"),
    (["-sp", "--special"], "", "在输出中显示 special token", "sampling"),
    (["-s", "--seed"], "N", "随机种子", "sampling"),
    (["-l", "--logit-bias"], "TOKEN(+/-)BIAS", "修改指定 token 的 logits", "sampling"),
    (["-j", "--json-schema"], "SCHEMA", "使用 JSON Schema 约束输出", "sampling"),
    (["-jf", "--json-schema-file"], "PATH", "从文件读取 JSON Schema", "sampling"),
    (["-bs", "--backend-sampling"], "", "启用实验性后端采样", "sampling"),
    (["--cache-prompt"], "", "启用 Prompt cache", "kv-cache"),
    (["--no-cache-prompt"], "", "禁用 Prompt cache", "kv-cache"),
    (["--cache-reuse"], "N", "Prompt cache 最小复用块", "kv-cache"),
    (["--metrics"], "", "启用 Prometheus metrics", "server"),
    (["--slots"], "", "启用 slot 监控端点", "server"),
    (["--perf"], "", "启用 libllama 性能计时", "diagnostics"),
    (["--warmup"], "", "服务启动时预热", "performance"),
    (["--no-warmup"], "", "关闭启动预热", "performance"),
    (["-a", "--alias"], "NAME", "API 返回和路由使用的模型别名", "model"),
    (["-m", "--model"], "PATH", "本地 GGUF 模型文件", "model"),
    (["-mu", "--model-url"], "URL", "从 URL 获取模型", "model"),
    (["-dr", "--docker-repo"], "REPO", "Docker Hub 模型标识", "model"),
    (["-hf", "-hfr", "--hf-repo"], "REPO[:QUANT]", "Hugging Face 模型仓库", "model"),
    (["-hff", "--hf-file"], "FILE", "Hugging Face 仓库中的模型文件", "model"),
    (["-hft", "--hf-token"], "TOKEN", "Hugging Face 访问令牌", "security"),
    (["--host"], "HOST", "监听地址", "server"),
    (["--port"], "PORT", "监听端口", "server"),
    (["-to", "--timeout"], "SECONDS", "HTTP 读写超时", "server"),
    (["-ag", "--agent"], "", "启用实验性 agent 模式", "server"),
    (["-no-ag", "--no-agent"], "", "禁用实验性 agent 模式", "server"),
    (["--api-key"], "KEYS", "API key，支持逗号分隔", "security"),
    (["--api-key-file"], "PATH", "API key 文件", "security"),
    (["--jinja"], "", "启用 Jinja chat template", "chat"),
    (["--chat-template"], "TEMPLATE", "自定义 chat template", "chat"),
    (["--chat-template-file"], "PATH", "自定义 chat template 文件", "chat"),
    (["-rea", "--reasoning"], "on|off|auto", "Reasoning 模式", "chat"),
    (["--reasoning-format"], "FORMAT", "Reasoning 返回格式", "chat"),
    (["-sps", "--slot-prompt-similarity"], "N", "请求 prompt 与已有 slot 的相似度阈值", "server"),
    (["--lora"], "PATHS", "加载一个或多个 LoRA", "adapters"),
    (["--lora-scaled"], "PATH:SCALE", "加载带缩放 LoRA", "adapters"),
    (["--mmproj-auto"], "", "自动使用多模态 projector", "multimodal"),
    (["--no-mmproj"], "", "禁用多模态 projector", "multimodal"),
    (["--rpc"], "HOSTS", "RPC server 列表", "gpu"),
    (["--load-mode"], "MODE", "模型加载模式", "memory"),
    (["--numa"], "MODE", "NUMA 优化模式", "cpu"),
    (["--mlock"], "", "锁定模型内存，已弃用，优先 load-mode", "memory"),
    (["--mmap"], "", "使用 mmap，已弃用，优先 load-mode", "memory"),
    (["--check-tensors"], "", "加载时检查 tensor", "diagnostics"),
    (["--log-file"], "PATH", "日志文件", "logging"),
    (["--log-timestamps"], "", "日志添加时间戳", "logging"),
    (["-v", "--verbose", "--log-verbose"], "", "启用详细日志", "logging"),
    (["-lv", "--verbosity", "--log-verbosity"], "N", "日志级别 0-5", "logging"),
    (["-hfd", "-hfrd", "--spec-draft-hf", "--hf-repo-draft"], "REPO[:QUANT]", "Draft 模型的 Hugging Face 仓库", "speculative"),
    (["-md", "--spec-draft-model", "--model-draft"], "PATH", "推测解码 draft 模型", "speculative"),
    (["-td", "--spec-draft-threads", "--threads-draft"], "N", "Draft 生成阶段 CPU 线程数", "speculative"),
    (["-tbd", "--spec-draft-threads-batch", "--threads-batch-draft"], "N", "Draft batch 阶段 CPU 线程数", "speculative"),
    (["-Cd", "--spec-draft-cpu-mask", "--cpu-mask-draft"], "MASK", "Draft 生成线程 CPU affinity mask", "speculative"),
    (["-Crd", "--spec-draft-cpu-range", "--cpu-range-draft"], "LO-HI", "Draft 生成线程 CPU 范围", "speculative"),
    (["-Cbd", "--spec-draft-cpu-mask-batch", "--cpu-mask-batch-draft"], "MASK", "Draft batch 线程 CPU affinity mask", "speculative"),
    (["-ctkd", "--spec-draft-type-k", "--cache-type-k-draft"], "TYPE", "Draft 模型 K cache 数据类型", "speculative"),
    (["-ctvd", "--spec-draft-type-v", "--cache-type-v-draft"], "TYPE", "Draft 模型 V cache 数据类型", "speculative"),
    (["-otd", "--spec-draft-override-tensor", "--override-tensor-draft"], "PATTERN=TYPE", "覆盖 Draft tensor 的 buffer 类型", "speculative"),
    (["-cmoed", "--spec-draft-cpu-moe", "--cpu-moe-draft"], "", "将 Draft MoE 权重保留在 CPU", "speculative"),
    (["-ncmoed", "--spec-draft-n-cpu-moe", "--spec-draft-ncmoe", "--n-cpu-moe-draft"], "N", "将 Draft 前 N 层 MoE 权重保留在 CPU", "speculative"),
    (["-devd", "--spec-draft-device", "--device-draft"], "DEVICES", "Draft 模型 offload 设备列表", "speculative"),
    (["-ngld", "--spec-draft-ngl", "--gpu-layers-draft", "--n-gpu-layers-draft"], "N|auto|all", "Draft 模型放入显存的层数", "speculative"),
    (["--spec-draft-n-max"], "N", "每轮最大 draft token", "speculative"),
    (["--spec-draft-p-min"], "P", "最小推测接受概率", "speculative"),
]


def seed_builtin_catalog(db: Session) -> None:
    existing = {row.key: row for row in db.scalars(select(ArgumentCatalog)).all()}
    for aliases, hint, description, category in BUILTIN_ARGUMENTS:
        key = aliases[-1]
        row = existing.get(key)
        if row is None:
            row = ArgumentCatalog(key=key, source="builtin")
            db.add(row)
            existing[key] = row
        if row.source != "builtin":
            continue
        row.aliases_json = json.dumps(aliases)
        row.value_hint = hint
        row.description = description
        row.category = category
        row.supported = True
    db.commit()


def _category_for(flag: str, description: str) -> str:
    haystack = f"{flag} {description}".lower()
    rules = [
        ("speculative", ("spec-", "draft", "ngram")),
        ("gpu", ("gpu", "device", "tensor-split", "offload", "rpc")),
        ("kv-cache", ("cache", "ctx", "context", "swa")),
        ("sampling", ("temp", "top-", "min-p", "sampler", "penalty", "mirostat", "grammar")),
        ("server", ("host", "port", "cors", "http", "api", "slot", "metrics", "webui", "models-")),
        ("chat", ("chat", "jinja", "reasoning", "think")),
        ("cpu", ("thread", "cpu", "numa", "prio", "poll")),
        ("logging", ("log", "verbose")),
        ("model", ("model", "hf-", "docker", "lora", "control-vector")),
    ]
    for category, needles in rules:
        if any(needle in haystack for needle in needles):
            return category
    return "other"


def parse_help_output(text: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    option_line = re.compile(r"^\s*((?:--?[A-Za-z0-9][A-Za-z0-9-]*(?:,?\s*)?)+)(?:\s+([^\s].*?))?(?:\s{2,}(.+))?$")
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        aliases = re.findall(r"(?<!\w)--?[A-Za-z0-9][A-Za-z0-9-]*", line)
        if aliases and line.lstrip().startswith("-"):
            if current:
                entries.append(current)
            desc_start = max(line.find(alias) + len(alias) for alias in aliases)
            remainder = line[desc_start:].strip(" ,\t")
            value_hint = ""
            description = remainder
            split = re.split(r"\s{2,}", remainder, maxsplit=1)
            if len(split) == 2:
                value_hint, description = split[0].strip(), split[1].strip()
            elif remainder and len(remainder.split()) <= 3 and remainder.upper() == remainder:
                value_hint, description = remainder, ""
            current = {
                "aliases": list(dict.fromkeys(aliases)),
                "value_hint": value_hint,
                "description": description,
            }
        elif current and line.startswith(" "):
            current["description"] = f"{current['description']} {line.strip()}".strip()
    if current:
        entries.append(current)
    return [entry for entry in entries if entry["aliases"]]


def refresh_runtime_catalog(db: Session, settings: AppSettings) -> dict[str, object]:
    try:
        completed = subprocess.run(
            [settings.llama_server_bin, "--help"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "count": 0, "error": str(exc)}
    text = (completed.stdout or "") + "\n" + (completed.stderr or "")
    parsed = parse_help_output(text)
    if not parsed:
        return {"ok": False, "count": 0, "error": "未从 llama-server --help 解析到参数"}

    existing = {row.key: row for row in db.scalars(select(ArgumentCatalog)).all()}
    runtime_keys: set[str] = set()
    for entry in parsed:
        aliases = entry["aliases"]
        assert isinstance(aliases, list)
        long_aliases = [alias for alias in aliases if str(alias).startswith("--")]
        key = str(long_aliases[-1] if long_aliases else aliases[-1])
        runtime_keys.add(key)
        row = existing.get(key)
        if row is None:
            row = ArgumentCatalog(key=key)
            db.add(row)
        row.aliases_json = json.dumps(aliases)
        row.value_hint = str(entry["value_hint"])
        row.description = str(entry["description"])
        row.category = _category_for(key, row.description)
        row.source = "runtime"
        row.supported = True
    for row in existing.values():
        if row.source == "runtime" and row.key not in runtime_keys:
            row.supported = False
    db.commit()
    return {"ok": True, "count": len(parsed), "error": None}


@dataclass
class ArgvBuildResult:
    argv: list[str]
    warnings: list[str]


def _looks_like_flag(token: str) -> bool:
    return re.fullmatch(r"-{1,2}[A-Za-z][A-Za-z0-9-]*", token) is not None


def split_custom_args(text: str) -> list[str]:
    if "\x00" in text:
        raise ValueError("自定义参数不能包含 NUL")
    if len(text) > 65536:
        raise ValueError("自定义参数总长度不能超过 65536 字符")
    result: list[str] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if len(line) > 4096:
            raise ValueError(f"第 {line_no} 行过长")
        try:
            result.extend(shlex.split(line, posix=True))
        except ValueError as exc:
            raise ValueError(f"第 {line_no} 行无法解析: {exc}") from exc
    return result


def build_profile_argv(
    settings: AppSettings,
    model_path: str,
    catalog_args: list[CatalogArgumentInput],
    custom_args_text: str,
    known_flags: set[str] | None = None,
    canonical_flags: dict[str, str] | None = None,
) -> ArgvBuildResult:
    return build_server_argv(
        settings,
        ["--model", model_path],
        catalog_args,
        custom_args_text,
        known_flags,
        canonical_flags,
    )


def build_server_argv(
    settings: AppSettings,
    launch_args: list[str],
    catalog_args: list[CatalogArgumentInput],
    custom_args_text: str,
    known_flags: set[str] | None = None,
    canonical_flags: dict[str, str] | None = None,
) -> ArgvBuildResult:
    argv = [settings.llama_server_bin, *launch_args, "--host", settings.llama_host, "--port", str(settings.llama_port)]
    warnings: list[str] = []
    canonical = canonical_flags or {}
    seen: dict[str, int] = {"--host": 1, "--port": 1}
    for token in launch_args:
        if _looks_like_flag(token):
            identity = canonical.get(token, token)
            seen[identity] = seen.get(identity, 0) + 1
    for item in catalog_args:
        if not _looks_like_flag(item.flag):
            raise ValueError(f"参数 {item.flag!r} 不是合法 flag")
        argv.append(item.flag)
        if item.value != "":
            argv.append(item.value)
        identity = canonical.get(item.flag, item.flag)
        seen[identity] = seen.get(identity, 0) + 1
        if known_flags is not None and item.flag not in known_flags:
            warnings.append(f"本机参数目录未发现 {item.flag}")
    custom = split_custom_args(custom_args_text)
    argv.extend(custom)
    for token in custom:
        if _looks_like_flag(token):
            identity = canonical.get(token, token)
            seen[identity] = seen.get(identity, 0) + 1
            if known_flags is not None and token not in known_flags:
                warnings.append(f"自定义参数 {token} 未出现在本机 --help 中")
    duplicates = sorted(flag for flag, count in seen.items() if count > 1)
    if duplicates:
        warnings.append("检测到重复参数，保留并按最终 argv 顺序交给 llama.cpp: " + ", ".join(duplicates))
    return ArgvBuildResult(argv=argv, warnings=list(dict.fromkeys(warnings)))
