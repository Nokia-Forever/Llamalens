# llama.cpp `llama-server` 的 systemd 服务参数参考

> 基线：2026-08-06 从 [llama.cpp 上游 `master` 的 `common/arg.cpp`](https://github.com/ggml-org/llama.cpp/blob/c8e03ce8122b7af76f836d53efde6df1ce5ec437/common/arg.cpp) 核对，提交 `c8e03ce8122b7af76f836d53efde6df1ce5ec437`。该版本的参数解析器中，`llama-server` 可接受约 234 组参数（包含少用、实验性和历史兼容项）。
>
> **版本规则**：llama.cpp 参数、默认值和编译后端会频繁变化。部署时的唯一最终依据永远是服务器上实际二进制的 `llama-server --help` 与 `llama-server --version`；本文件是完整的设计/填写参考，不能用来推断你尚未提供的服务器实际值。

## 1. 先区分三类“参数”

一个 `llama-server.service` 同时有三层配置，不能混淆：

| 层 | 写在哪里 | 作用 |
|---|---|---|
| systemd unit 指令 | `[Unit]`、`[Service]`、`[Install]` | 进程何时启动、以谁运行、崩溃是否重启、日志/资源/安全限制 |
| `llama-server` 启动参数 | `ExecStart=` 或环境文件 | 模型、上下文、GPU offload、批量、HTTP API 等 |
| 环境变量 | `Environment=` / `EnvironmentFile=` | 给某些同名 llama 参数赋值，或提供 CUDA/HF 等运行环境 |

`systemd` 不会理解 `--ctx-size`、`--gpu-layers`；它只负责启动 `llama-server`。反过来，`llama-server` 也不认识 `Restart=on-failure`。

## 2. 推荐的可管理结构

不要把参数散落在 `ExecStart=`。把 unit 保持固定，把会反复变化的模型与性能参数放在环境文件；之后控制台只替换环境文件即可。

目录建议：

```text
/etc/systemd/system/llama-server.service          # 固定 unit
/etc/llama-server/active.env                      # 当前激活 Profile
/etc/llama-server/profiles/*.env                  # 每个模型/参数档案
/srv/llama.cpp/build/bin/llama-server             # 实际二进制（按实际位置替换）
/srv/models/*.gguf                                # 模型目录（按实际位置替换）
```

### 2.1 一份可直接改造的 unit 示例

下面每一行都是**示例值，不是你的服务器实际配置**。路径、用户、端口、GPU 相关项必须按机器替换。

这是一份手工维护 service 的通用参考。LlamaLens 按 [实施设计](implementation-design.md) 落地时，会让 `ExecStart` 固定调用 runner，并由 Profile 的“参数目录 + 自定义参数尾部”构造实际 `llama-server` argv；这样不必为每次模型/参数切换修改 unit。

```ini
# /etc/systemd/system/llama-server.service
[Unit]
Description=llama.cpp HTTP inference server
Documentation=https://github.com/ggml-org/llama.cpp
Wants=network-online.target
After=network-online.target

[Service]
Type=exec
User=llama
Group=llama
WorkingDirectory=/srv/llama.cpp
EnvironmentFile=-/etc/llama-server/active.env

# 直接使用环境变量；${VAR} 表示一个参数值，LLAMA_SERVER_ARGS 则展开为多个参数。
ExecStart=/srv/llama.cpp/build/bin/llama-server --model ${LLAMA_MODEL} --host ${LLAMA_HOST} --port ${LLAMA_PORT} $LLAMA_SERVER_ARGS

Restart=on-failure
RestartSec=5s
TimeoutStartSec=10min
TimeoutStopSec=30s
KillSignal=SIGINT
LimitNOFILE=65536
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths=/var/lib/llama-server /var/log/llama-server

[Install]
WantedBy=multi-user.target
```

### 2.2 unit 中每个已填写项的含义

| 指令 / 示例填写 | 含义、何时改 |
|---|---|
| `Description=...` | `systemctl status` 中显示的说明，无运行时影响。 |
| `Documentation=...` | unit 的文档链接，无运行时影响。 |
| `Wants=network-online.target` | 希望网络已就绪；失败不阻止服务启动。 |
| `After=network-online.target` | 启动顺序在网络就绪之后；不代表监听公网必须使用。 |
| `Type=exec` | 由 systemd 直接执行二进制；适合不 fork 到后台的 `llama-server`。不要使用 `forking`。 |
| `User=llama`、`Group=llama` | 以专用非 root 用户运行；该用户必须能读二进制、GGUF、LoRA、日志目录和 GPU 设备。 |
| `WorkingDirectory=/srv/llama.cpp` | 相对路径的基准目录；建议仍全部使用绝对路径。 |
| `EnvironmentFile=-/etc/llama-server/active.env` | 读取当前 Profile；前缀 `-` 表示文件暂不存在时不立刻失败。生产环境首次启用前应确保该文件存在。 |
| `ExecStart=...` | 真正执行的命令。`llama-server` 必须是前台进程，不能末尾加 `&`。 |
| `Restart=on-failure` | 非零退出、崩溃、被 watchdog 终止时重启；正常 `systemctl stop` 不会重启。 |
| `RestartSec=5s` | 每次失败后等待 5 秒；避免 OOM 时疯狂重启。 |
| `TimeoutStartSec=10min` | 大模型加载较慢时允许的启动上限；模型很大/网络下载时可增加。 |
| `TimeoutStopSec=30s` | 正常停止的等待上限；之后 systemd 会强制终止。 |
| `KillSignal=SIGINT` | 先让 llama.cpp 收到 Ctrl+C 等价信号、优雅退出。 |
| `LimitNOFILE=65536` | 提高打开文件描述符上限；并发连接、日志、多个模型/adapter 时更稳。 |
| `NoNewPrivileges=true` | 禁止进程及其子进程通过 setuid 等方式新增权限。 |
| `PrivateTmp=true` | 使用隔离的 `/tmp`，降低与其它服务互相干扰。 |
| `ProtectHome=true` | 阻止读取 `/home`、`/root`、`/run/user`；模型不要放那里，或改为 `read-only`/关闭并评估风险。 |
| `ProtectSystem=full` | 将 `/usr`、`/boot`、`/etc` 保护为只读；环境/Profile 应由运维进程修改，不由 llama-server 修改。 |
| `ReadWritePaths=...` | 在保护模式下明确允许写的持久状态、日志目录；若没有写日志/slot cache，可删除。 |
| `WantedBy=multi-user.target` | `systemctl enable` 后随正常多用户启动目标启动。 |

安全项会影响 GPU 驱动、远程模型下载、`--media-path`、`--slot-save-path` 和日志写入。先以 `systemd-analyze security llama-server.service` 检查，再按真实访问路径逐项放行，不能盲目复制。

### 2.3 当前 Profile 环境文件示例

```bash
# /etc/llama-server/active.env
# 这些值仅是 1× NVIDIA GPU、Qwen 类 GGUF 的可编辑示例，不代表通用最优值。
LLAMA_MODEL=/srv/models/Qwen3-32B-Q4_K_M.gguf
LLAMA_HOST=127.0.0.1
LLAMA_PORT=8080
LLAMA_SERVER_ARGS="--ctx-size 8192 --gpu-layers all --device CUDA0 --threads 16 --threads-batch 16 --batch-size 2048 --ubatch-size 512 --parallel 1 --flash-attn auto --kv-offload --cache-type-k q8_0 --cache-type-v q8_0 --cont-batching --cache-prompt --metrics --slots --perf"
```

示例的意图：只监听本机（由 Nginx/反向代理对外暴露）；模型、上下文、offload 和 batch 是可测评的 Profile 字段；`--perf` 让服务产生内部性能计时，`--metrics` / `--slots` 是控制台采集状态的候选端点。`CUDA0` 必须以实际 `--list-devices` 输出为准，不能假定每个编译版本的设备名称相同。

## 3. 测评时必须记录、并优先暴露在 UI 的参数

这些参数直接改变 Prefill、Decode tok/s、TTFT、显存或并发行为；每一轮 benchmark 都应存储它们的完整值。

| 参数（环境变量） | 填写形式 | 对测评的主要影响 |
|---|---|---|
| `-m, --model` (`LLAMA_ARG_MODEL`) | `/绝对路径/model.gguf` | 模型架构、大小、量化是最根本变量。一次测试只选择一个模型来源：本地模型、`--hf-repo`、`--model-url` 不能混淆。 |
| `-c, --ctx-size` (`LLAMA_ARG_CTX_SIZE`) | `8192`；`0` 为模型元数据值 | 上下文/KV 容量；会明显影响 KV 显存和长 prompt Prefill。 |
| `-b, --batch-size` (`LLAMA_ARG_BATCH`) | 逻辑 batch，如 `2048` | Prefill 吞吐常随其提升而提高，直到显存/计算瓶颈；不要把它当输出 batch。 |
| `-ub, --ubatch-size` (`LLAMA_ARG_UBATCH`) | 物理 micro-batch，如 `512` | 控制一次底层计算分块；影响显存、GPU 利用率和 Prefill。必须与 `-b` 一起记录。 |
| `-ngl, --gpu-layers` (`LLAMA_ARG_N_GPU_LAYERS`) | 数字、`auto`、`all` | 放入 VRAM 的层数；通常最显著地影响 Decode。`all` 不保证能装下。 |
| `-dev, --device` (`LLAMA_ARG_DEVICE`) | 逗号分隔设备列表 | 指定 offload 设备；先运行 `--list-devices` 获取正确标识。 |
| `-kvo, --kv-offload` (`LLAMA_ARG_KV_OFFLOAD`) | 开关 | 将 KV cache offload 到设备；长上下文时影响巨大。反向开关是 `-nkvo, --no-kv-offload`。 |
| `-ctk/-ctv, --cache-type-k/v` | 如 `f16`、`q8_0`（可用值以本机 help 为准） | K/V KV cache 精度、显存和质量折中；两个值要分别记录。 |
| `-fa, --flash-attn` (`LLAMA_ARG_FLASH_ATTN`) | `on` / `off` / `auto` | 注意力实现选择；长 Prefill 和显存经常受影响，后端不支持时不可强开。 |
| `-t, --threads` (`LLAMA_ARG_THREADS`) | `16` | Decode 阶段 CPU 线程数；即使 GPU offload，也可能影响采样/未 offload 层。 |
| `-tb, --threads-batch` | `16` | Prompt/batch 阶段 CPU 线程数；CPU 或部分 offload 测试尤为关键。 |
| `-np, --parallel` (`LLAMA_ARG_N_PARALLEL`) | `1`、`4`、`8` | server slot 数；改变并发吞吐、KV 分摊与单请求延迟。单流基准应固定为 `1`。 |
| `-cb, --cont-batching` (`LLAMA_ARG_CONT_BATCHING`) | 开关 | 连续/动态 batching；并发基准必须记录，不能和关闭时直接混比。 |
| `--cache-prompt` (`LLAMA_ARG_CACHE_PROMPT`) | 开关 | prompt cache 会让重复输入的 Prefill 非常快；纯模型基准应关闭或每轮使用不同 prompt，缓存命中基准应单列。 |
| `--cache-reuse` | token 数 | 允许 KV shifting 的最小重用块；影响多轮/长会话基准。 |
| `-sm/--split-mode`、`-ts/--tensor-split`、`-mg/--main-gpu` | 多 GPU 模式、比例、序号 | 多卡时的权重/KV 分布；GPU 型号、驱动、总线拓扑也必须随结果存档。 |
| `--rope-*`、`--yarn-*` | 见完整附录 | 改写上下文扩展策略，比较质量或长文本速度时必须记录。 |

**基准纪律**：固定模型文件 hash、llama.cpp 版本/编译后端、GPU driver、`nvidia-smi` 状态、输入/输出 token 数、并发、热身次数、prompt cache 是否命中。否则两次 `tok/s` 不具有可比性。

## 4. 全量 `llama-server` 参数附录

下表按功能分组。别名以 `/` 合并；`ENV:` 后是上游为该参数显式提供的环境变量。无 `ENV` 不等于不能用，只表示应直接放在 `LLAMA_SERVER_ARGS`/`ExecStart`。`开关`通常表示无值即可启用；带 `on|off|auto` 的参数必须显式给值。

### 4.1 诊断、CPU 与上下文/KV

| 参数 | 含义 |
|---|---|
| `-h/--help/--usage`；`--version`；`-cl/--cache-list`；`--completion-bash` | 显示帮助、构建版本、模型缓存清单、Bash 补全后退出；不用于常驻服务。 |
| `-t/--threads` ENV:`LLAMA_ARG_THREADS`；`-tb/--threads-batch` | 生成 / prompt-batch 使用的 CPU 线程数。 |
| `-C/--cpu-mask`；`-Cr/--cpu-range`；`--cpu-strict`；`--prio`；`--poll` | 生成线程的 CPU 亲和、严格放置、优先级（-1~3）及轮询等待等级。 |
| `-Cb/--cpu-mask-batch`；`-Crb/--cpu-range-batch`；`--cpu-strict-batch`；`--prio-batch`；`--poll-batch` | batch/prompt 线程对应的 CPU 放置与优先级；默认继承生成侧。 |
| `-lcs/--lookup-cache-static`；`-lcd/--lookup-cache-dynamic` | lookup decoding 的静态/动态缓存文件；前者不随生成更新，后者会更新。 |
| `-c/--ctx-size` ENV:`LLAMA_ARG_CTX_SIZE` | prompt context token 容量；`0` 取模型元数据。 |
| `-n/--predict/--n-predict` ENV:`LLAMA_ARG_N_PREDICT` | 默认预测 token 上限；server API 请求常会覆盖它。`-1` 为无限（不要在无人监管的公网服务使用）。 |
| `-b/--batch-size` ENV:`LLAMA_ARG_BATCH`；`-ub/--ubatch-size` ENV:`LLAMA_ARG_UBATCH` | 逻辑最大 batch / 物理最大 micro-batch。 |
| `--keep` | context shift 时保留初始 prompt token 数；`-1` 表示全部保留。 |
| `--swa-full` ENV:`LLAMA_ARG_SWA_FULL` | 使用全尺寸 SWA cache。 |
| `-ctxcp/--ctx-checkpoints/--swa-checkpoints` ENV:`LLAMA_ARG_CTX_CHECKPOINTS`；`-cms/--checkpoint-min-step` ENV:`LLAMA_ARG_CHECKPOINT_MIN_SPACING_NT` | 每 slot 最大 context checkpoint 数 / checkpoint 的最小 token 间隔。 |
| `-cram/--cache-ram` ENV:`LLAMA_ARG_CACHE_RAM`；`-kvu/--kv-unified` ENV:`LLAMA_ARG_KV_UNIFIED`；`--cache-idle-slots` ENV:`LLAMA_ARG_CACHE_IDLE_SLOTS` | RAM prompt-cache 上限（MiB，`-1`不限、`0`关闭）/ 全序列统一 KV buffer / 保存空闲 slot 缓存（需 cache-ram）。 |
| `--context-shift` ENV:`LLAMA_ARG_CONTEXT_SHIFT` | 无限文本生成时是否 context shift。 |
| `-fa/--flash-attn` ENV:`LLAMA_ARG_FLASH_ATTN` | Flash Attention：`on`、`off`、`auto`。 |
| `--perf` ENV:`LLAMA_ARG_PERF` | 打开 libllama 内部 performance timing；测评应启用并记录版本。 |

### 4.2 Prompt、采样与输出约束

| 参数 | 含义 |
|---|---|
| `-p/--prompt`；`-f/--file`；`-bf/--binary-file` | 默认 prompt、文本 prompt 文件、二进制 prompt 文件；API server 常不应把测试 prompt 写死在服务 Profile。 |
| `-e/--escape`；`-r/--reverse-prompt`；`-sp/--special`；`--warmup`；`--spm-infill` | prompt 转义、反向提示停止词、输出 special token、空跑预热、SPM infill 顺序。 |
| `--samplers`；`-s/--seed`；`--sampler-seq/--sampling-seq` | 采样器完整顺序、随机种子、简写的采样顺序。 |
| `--ignore-eos`；`--temp/--temperature`；`--top-k` ENV:`LLAMA_ARG_TOP_K`；`--top-p`；`--min-p`；`--top-nsigma/--top-n-sigma` | 忽略 EOS、温度、top-k/top-p/min-p/top-n-sigma 采样。 |
| `--xtc-probability`；`--xtc-threshold`；`--typical/--typical-p` | XTC 概率/阈值、locally typical sampling。 |
| `--repeat-last-n`；`--repeat-penalty`；`--presence-penalty`；`--frequency-penalty` | 重复惩罚使用的历史窗口和三种惩罚系数。 |
| `--dry-multiplier`；`--dry-base`；`--dry-allowed-length`；`--dry-penalty-last-n`；`--dry-sequence-breaker` | DRY（Don't Repeat Yourself）采样的强度、底数、允许长度、回看窗口与断序列。 |
| `--adaptive-target`；`--adaptive-decay`；`--dynatemp-range`；`--dynatemp-exp` | adaptive-p 目标/衰减、动态温度范围/指数。 |
| `--mirostat`；`--mirostat-lr`；`--mirostat-ent` | Mirostat 模式（0/1/2）、学习率 eta、目标熵 tau；启用时 top-k/top-p/typical 会被忽略。 |
| `-l/--logit-bias` | 修改特定 token 的 logits，格式如 `TOKEN_ID+1` 或 `TOKEN_ID-1`。 |
| `--grammar`；`--grammar-file`；`-j/--json-schema`；`-jf/--json-schema-file` | 用 GBNF 或 JSON Schema 约束输出格式；会影响 Decode 性能，应在结果中记录。 |
| `-bs/--backend-sampling` ENV:`LLAMA_ARG_BACKEND_SAMPLING` | 实验性后端采样。 |

### 4.3 RoPE、KV、内存与 GPU/offload

| 参数 | 含义 |
|---|---|
| `--pooling` ENV:`LLAMA_ARG_POOLING`；`--embd-normalize` | embedding pooling 类型 / embedding 归一化（-1 none、0 int16 max-abs、1 taxicab、2 euclidean、>2 p-norm）。仅 embedding 模型场景。 |
| `--rope-scaling` ENV:`LLAMA_ARG_ROPE_SCALING_TYPE`；`--rope-scale` ENV:`LLAMA_ARG_ROPE_SCALE`；`--rope-freq-base` ENV:`LLAMA_ARG_ROPE_FREQ_BASE`；`--rope-freq-scale` ENV:`LLAMA_ARG_ROPE_FREQ_SCALE` | RoPE scaling 类型、扩展倍率、NTK base、频率缩放；默认可来自模型元数据。 |
| `--yarn-orig-ctx` ENV:`LLAMA_ARG_YARN_ORIG_CTX`；`--yarn-ext-factor`；`--yarn-attn-factor`；`--yarn-beta-slow`；`--yarn-beta-fast` | YaRN 原始训练 context 与四个扩展/注意力校正参数。 |
| `-kvo/--kv-offload` ENV:`LLAMA_ARG_KV_OFFLOAD`；`-nkvo/--no-kv-offload` | 是否 offload KV cache；两者为一对正反选项。 |
| `--repack` ENV:`LLAMA_ARG_REPACK`；`-nr/--no-repack`；`--no-host` ENV:`LLAMA_ARG_NO_HOST` | 权重重打包开关 / 允许额外 buffer、绕过 host buffer 的高级内存配置。 |
| `-ctk/--cache-type-k` ENV:`LLAMA_ARG_CACHE_TYPE_K`；`-ctv/--cache-type-v` ENV:`LLAMA_ARG_CACHE_TYPE_V` | K / V 的 KV cache 数据类型；可接受类型必须看本机 `--help`。 |
| `-dt/--defrag-thold` ENV:`LLAMA_ARG_DEFRAG_THOLD` | KV cache 碎片整理阈值；上游标为已弃用。 |
| `-np/--parallel` ENV:`LLAMA_ARG_N_PARALLEL`；`-cb/--cont-batching` ENV:`LLAMA_ARG_CONT_BATCHING` | server slot/并行序列数（同一别名在不同 help 组说明中出现）/ 连续 batching。 |
| `--mmproj-auto` / `--no-mmproj` / `--no-mmproj-auto` ENV:`LLAMA_ARG_MMPROJ_AUTO`；`--mtmd-batch-max-tokens` ENV:`LLAMA_ARG_MTMD_BATCH_MAX_TOKENS` | 自动使用可用的多模态 projector / 显式关闭它 / 每 batch 最大图像 token 数。 |
| `--rpc` ENV:`LLAMA_ARG_RPC` | 远端 RPC server 列表，逗号分隔 `host:port`。 |
| `--mlock`、`--mmap`、`-dio/--direct-io` | 已弃用，改用 `-lm/--load-mode`。 |
| `-lm/--load-mode` ENV:`LLAMA_ARG_LOAD_MODE` | 加载模式：`none`、`mmap`、`mlock`、`mmap+mlock`、`dio`。 |
| `--numa` ENV:`LLAMA_ARG_NUMA` | NUMA：`distribute`、`isolate`、`numactl`；更改前后要清 page cache 并单独测。 |
| `-dev/--device` ENV:`LLAMA_ARG_DEVICE`；`--list-devices` | offload 设备列表 / 打印设备列表并退出。 |
| `-ot/--override-tensor` ENV:`LLAMA_ARG_OVERRIDE_TENSOR` | 用 tensor 名称模式覆盖 buffer 类型。 |
| `-cmoe/--cpu-moe` ENV:`LLAMA_ARG_CPU_MOE`；`-ncmoe/--n-cpu-moe` ENV:`LLAMA_ARG_N_CPU_MOE` | 将所有 / 前 N 层 MoE 权重留在 CPU。 |
| `-ngl/--gpu-layers/--n-gpu-layers` ENV:`LLAMA_ARG_N_GPU_LAYERS` | VRAM 中放置的模型层数：精确数、`auto`、`all`。 |
| `-sm/--split-mode` ENV:`LLAMA_ARG_SPLIT_MODE` | 多 GPU：`none`（单卡）、`layer`（默认流水）、`row`（按行）、`tensor`（实验性）。 |
| `-ts/--tensor-split` ENV:`LLAMA_ARG_TENSOR_SPLIT`；`-mg/--main-gpu` ENV:`LLAMA_ARG_MAIN_GPU` | 各 GPU 的比例，如 `3,1` / 单卡模式的模型 GPU，或 row 模式的中间结果/KV GPU。 |
| `-fit/--fit` ENV:`LLAMA_ARG_FIT`；`-fitt/--fit-target`；`-fitc/--fit-ctx` | 自动适配设备内存、各设备保留目标、允许自动设置的最小 context。 |
| `--check-tensors`；`--override-kv`；`--op-offload` | 检查无效 tensor 值、覆盖 GGUF 元数据、是否将 host tensor 操作 offload；均为高级诊断/兼容选项。 |

### 4.4 Adapter、模型来源和 HTTP 服务

| 参数 | 含义 |
|---|---|
| `--lora`；`--lora-scaled`；`--lora-init-without-apply` | 加载 LoRA（可逗号分隔）/ 带缩放的 `FNAME:SCALE` / 只加载、不立即应用，后续用 API 管理。 |
| `--control-vector`；`--control-vector-scaled`；`--control-vector-layer-range` | Control Vector、带缩放版本、应用层范围（起止均包含）。 |
| `-a/--alias` ENV:`LLAMA_ARG_ALIAS`；`--tags` ENV:`LLAMA_ARG_TAGS` | API 侧模型别名（逗号分隔）/ 信息性 tag，不参与路由。 |
| `-m/--model` ENV:`LLAMA_ARG_MODEL` | 本地模型文件绝对路径。 |
| `-mu/--model-url` ENV:`LLAMA_ARG_MODEL_URL`；`-dr/--docker-repo` ENV:`LLAMA_ARG_DOCKER_REPO` | 下载 URL / Docker Hub 模型标识。自动下载会改变启动时长和网络依赖，不适合严谨离线测评。 |
| `-hf/-hfr/--hf-repo` ENV:`LLAMA_ARG_HF_REPO`；`-hff/--hf-file` ENV:`LLAMA_ARG_HF_FILE`；`-hft/--hf-token` ENV:`HF_TOKEN` | Hugging Face 仓库、指定文件、令牌。`--hf-file` 覆盖仓库量化选择；令牌不要明文写入 unit。 |
| `--offline` ENV:`LLAMA_ARG_OFFLINE` | 强制使用缓存、禁止网络访问。 |
| `--host` ENV:`LLAMA_ARG_HOST`；`--port` ENV:`LLAMA_ARG_PORT`；`--reuse-port` | 监听 IP/Unix socket（`.sock` 结尾）、端口、允许多个 socket 绑定同一端口。公网监听至少配 API key 和反向代理。 |
| `--path` ENV:`LLAMA_ARG_STATIC_PATH`；`--api-prefix` ENV:`LLAMA_ARG_API_PREFIX` | 静态 UI 目录 / API 路径前缀（无尾 `/`）。 |
| `--cors-origins`、`--cors-methods`、`--cors-headers`、`--cors-credentials` | CORS origins、方法、header、凭证。启用 credentials 时不要泛配 `*`；`localhost` 是上游支持的特殊值。 |
| `--ui-config/--webui-config`；`--ui-config-file/--webui-config-file`；`--ui/--webui` | 内嵌 Web UI 的默认 JSON/JSON 文件/开关。 |
| `--ui-mcp-proxy/--webui-mcp-proxy`；`--tools`；`--mcp-servers-config`；`--mcp-servers-json`；`-ag/--agent` | **实验性、高风险**：MCP CORS proxy、内置读写/执行工具、MCP 配置、全 agent 模式。不可在不可信网络环境开启。 |
| `--embedding/--embeddings`；`--rerank/--reranking` | 限制为 embedding API / 启用 reranking endpoint；只用于专用模型。 |
| `--api-key` ENV:`LLAMA_API_KEY`；`--api-key-file` ENV:`LLAMA_ARG_API_KEY_FILE` | API key（可逗号多值）/ 每行一个 key 的文件。优先文件，权限设为服务用户可读且 `0600`。 |
| `--ssl-key-file`；`--ssl-cert-file` | PEM 私钥和证书。多数部署更推荐 Nginx/Caddy 终止 TLS。 |
| `--chat-template-kwargs` | 给 Jinja 模板 JSON 参数；上游提示 reasoning 请用专用 `--reasoning`。 |
| `-to/--timeout`；`--sse-ping-interval`；`--threads-http` | HTTP 读写超时秒数、SSE ping 周期（`-1`关闭）、处理 HTTP 请求线程数。 |
| `--cache-prompt`；`--cache-reuse` | prompt cache 开关、从 cache 复用/KV shifting 的最小 chunk。 |
| `--metrics` ENV:`LLAMA_ARG_ENDPOINT_METRICS`；`--props`；`--slots` | Prometheus metrics、`POST /props` 全局属性修改、slot 监控 endpoint。`--props` 不应对不可信调用方公开。 |
| `--slot-save-path`；`--media-path` | 保存 slot KV cache 的目录 / 可用 `file://` 相对路径访问的本地媒体目录；均须对应 systemd 读写权限。 |
| `--models-dir`；`--models-preset`；`--models-max`；`--models-autoload` | router server 的模型目录、INI preset、同时加载最大模型数（0 无限制）、自动加载开关；单模型测评通常不用。 |

### 4.5 Chat、reasoning、日志和低频服务行为

| 参数 | 含义 |
|---|---|
| `--jinja` ENV:`LLAMA_ARG_JINJA` | 是否使用 Jinja chat template 引擎。 |
| `--reasoning-format` ENV:`LLAMA_ARG_THINK` | reasoning tag 的返回格式：`none`、`deepseek`、`deepseek-legacy` 或自动。 |
| `-rea/--reasoning` ENV:`LLAMA_ARG_REASONING`；`--reasoning-budget`；`--reasoning-budget-message`；`--reasoning-preserve` | 思考模式 `on/off/auto`、思考 token 预算（-1 不限、0 立即结束）、预算耗尽前插入的消息、历史中保留 reasoning。 |
| `--chat-template`；`--chat-template-file` | 自定义 Jinja template 字符串 / 文件。默认读 GGUF 元数据；会改变 tokenization，因此基准必须固定。 |
| `--skip-chat-parsing`；`--prefill-assistant` | 强制纯 content parser / assistant 末消息是否预填；会改变 prompt 与 TTFT。 |
| `-sps/--slot-prompt-similarity` | 请求 prompt 与 slot 的相似度阈值；`0` 关闭。 |
| `--sleep-idle-seconds` | 闲置多少秒后 server sleep；`-1` 关闭。测评时关闭，以免冷启动污染结果。 |
| `--log-disable`；`--log-file` ENV:`LLAMA_ARG_LOG_FILE`；`--log-prompts-dir` | 禁用日志、写入日志文件、将 prompt 写入目录（仅调试；敏感数据风险）。 |
| `--log-colors`；`-v/--verbose/--log-verbose`；`-lv/--verbosity/--log-verbosity`；`--log-prefix`；`--log-timestamps` | 色彩模式、无限 verbosity、阈值 0~5、日志前缀、时间戳。systemd journal 下通常 `--log-colors off` 更干净。 |

### 4.6 推测解码（Draft / N-gram）完整项

这些参数在未启用推测解码时不应随便填写；它们可能提高 Decode tok/s，也会引入 draft 模型显存、接受率和质量/延迟变量。

| 参数 | 含义 |
|---|---|
| `--spec-draft-hf/-hfd/-hfrd/--hf-repo-draft` | Draft 模型的 Hugging Face 仓库。 |
| `--spec-draft-model/-md/--model-draft` | 本地 Draft 模型文件。 |
| `--spec-draft-threads/-td/--threads-draft`；`--spec-draft-threads-batch/-tbd/--threads-batch-draft` | Draft 生成 / batch 线程数。 |
| `--spec-draft-cpu-mask/-Cd/--cpu-mask-draft`；`--spec-draft-cpu-range/-Crd/--cpu-range-draft`；`--spec-draft-cpu-strict/--cpu-strict-draft`；`--spec-draft-prio/--prio-draft`；`--spec-draft-poll/--poll-draft` | Draft 生成侧的 CPU 亲和、范围、严格放置、优先级、poll。 |
| `--spec-draft-cpu-mask-batch/-Cbd/--cpu-mask-batch-draft`；`--spec-draft-cpu-strict-batch/--cpu-strict-batch-draft`；`--spec-draft-prio-batch/--prio-batch-draft`；`--spec-draft-poll-batch/--poll-batch-draft` | Draft batch 侧对应配置。 |
| `--spec-draft-type-k/-ctkd/--cache-type-k-draft`；`--spec-draft-type-v/-ctvd/--cache-type-v-draft` | Draft 模型 K/V KV cache 类型。 |
| `--spec-draft-override-tensor/-otd/--override-tensor-draft` | Draft tensor buffer 类型覆盖。 |
| `--spec-draft-cpu-moe/-cmoed/--cpu-moe-draft`；`--spec-draft-n-cpu-moe/--spec-draft-ncmoe/-ncmoed/--n-cpu-moe-draft` | Draft MoE 全部 / 前 N 层留 CPU。 |
| `--spec-draft-device/-devd/--device-draft`；`--spec-draft-ngl/-ngld/--gpu-layers-draft/--n-gpu-layers-draft` | Draft offload 设备与 GPU layer 数。 |
| `--spec-draft-n-max`；`--spec-draft-n-min` | 一轮最多 / 最少 draft token 数。 |
| `--spec-draft-p-split/--draft-p-split`；`--spec-draft-p-min/--draft-p-min` | 推测解码 split 概率 / 最小 greedy 概率。 |
| `--spec-draft-backend-sampling` | 将 draft sampling offload 到后端（实验性）。 |
| `--spec-type` | 逗号分隔的推测解码类型列表。 |
| `--spec-ngram-mod-n-min`；`--spec-ngram-mod-n-max`；`--spec-ngram-mod-n-match` | ngram-mod 最小/最大 draft token、lookup 长度。 |
| `--spec-ngram-simple-size-n`；`--spec-ngram-simple-size-m`；`--spec-ngram-simple-min-hits` | ngram-simple lookup n-gram、draft m-gram、最小命中。 |
| `--spec-ngram-map-k-size-n`；`--spec-ngram-map-k-size-m`；`--spec-ngram-map-k-min-hits` | ngram-map-k 的 N/M/最小命中。 |
| `--spec-ngram-map-k4v-size-n`；`--spec-ngram-map-k4v-size-m`；`--spec-ngram-map-k4v-min-hits` | ngram-map-k4v 的 N/M/最小命中。 |
| `--draft/--draft-n/--draft-max`；`--draft-min/--draft-n-min`；`--spec-ngram-size-n`；`--spec-ngram-size-m`；`--spec-ngram-min-hits` | **已移除的兼容参数**；分别改用表中的 `--spec-draft-*` 或 `--spec-ngram-*` 新项，Profile UI 应标红且禁止新建使用。 |

### 4.7 不应加入 `llama-server` Profile 的伪相关项

上游通用参数解析器中还存在 `-lr-min/--learning-rate-min` 等为 fine-tuning 场景保留、却没有明确 example 标签的项。它们并不是 server 推理配置：即使某版本的解析器没有立刻报错，也不要写入服务 Profile。控制台应以实际 `llama-server --help` 输出建立白名单，而不是把 `common/arg.cpp` 的每一个解析分支都暴露成 UI 字段。

### 4.8 正反开关的完整反向别名

上表为可读性把正向开关列为主项；以下是同一上游版本中独立可写、但语义为关闭/反向的别名，列在这里以避免 Profile 校验漏掉它们：

```text
--no-kv-unified                 # --kv-unified 的反向项
--no-cache-idle-slots           # --cache-idle-slots 的反向项
--no-context-shift              # --context-shift 的反向项
--no-perf                       # --perf 的反向项
--no-escape                     # --escape 的反向项
--no-warmup                     # --warmup 的反向项
-nkvo / --no-kv-offload         # --kv-offload 的反向项
-nr / --no-repack               # --repack 的反向项
-nocb / --no-cont-batching      # --cont-batching 的反向项
--no-mmproj / --no-mmproj-auto  # --mmproj-auto 的反向项
--no-mmap                       # --mmap 的反向项（该组选项已弃用）
-ndio / --no-direct-io          # --direct-io 的反向项（该组选项已弃用）
--no-op-offload                 # --op-offload 的反向项
--no-cors-credentials           # --cors-credentials 的反向项
--no-ui-mcp-proxy / --no-webui-mcp-proxy
--no-agent / -no-ag
--no-ui / --no-webui
--no-cache-prompt
--no-slots
--no-models-autoload
--no-jinja
--no-reasoning-preserve
--no-skip-chat-parsing
--no-prefill-assistant
--no-log-prefix
--no-log-timestamps
--no-spec-draft-backend-sampling
```

## 5. 环境变量优先级和填写规则

上游为许多选项提供 `LLAMA_ARG_*` 环境变量（表中已逐项列出）。常用映射如下：

```bash
LLAMA_ARG_MODEL=/srv/models/model.gguf
LLAMA_ARG_CTX_SIZE=8192
LLAMA_ARG_N_GPU_LAYERS=all
LLAMA_ARG_DEVICE=CUDA0
LLAMA_ARG_THREADS=16
LLAMA_ARG_BATCH=2048
LLAMA_ARG_UBATCH=512
LLAMA_ARG_N_PARALLEL=1
LLAMA_ARG_FLASH_ATTN=auto
LLAMA_ARG_KV_OFFLOAD=1
LLAMA_ARG_CACHE_TYPE_K=q8_0
LLAMA_ARG_CACHE_TYPE_V=q8_0
LLAMA_ARG_HOST=127.0.0.1
LLAMA_ARG_PORT=8080
LLAMA_API_KEY_FILE=/etc/llama-server/api-keys
```

实际采用环境变量或命令行都可以，但同一参数只能选一种方式，避免值冲突。为了 Profile 生成器的可审计性，推荐：模型/端口/基础路径用明确环境变量；性能参数统一生成到 `LLAMA_SERVER_ARGS`；密钥只用只读 secrets 文件。

## 6. 上线前的本机核验命令

以下命令只读检查，不修改当前服务。替换二进制和 service 名称：

```bash
/srv/llama.cpp/build/bin/llama-server --version
/srv/llama.cpp/build/bin/llama-server --help | less
/srv/llama.cpp/build/bin/llama-server --list-devices
systemctl cat llama-server.service
systemctl show llama-server.service -p ExecStart -p Environment -p EnvironmentFiles -p User -p Group
systemd-analyze verify /etc/systemd/system/llama-server.service
systemd-analyze security llama-server.service
```

配置完成后才执行：

```bash
sudo systemctl daemon-reload
sudo systemctl restart llama-server.service
sudo systemctl status llama-server.service --no-pager
journalctl -u llama-server.service -b -n 200 --no-pager
```

## 7. 后续控制台应如何使用这份文档

1. 把第 3 节的字段做成 Profile 的一等字段，剩余所有 `llama-server` 选项进入“高级参数”键值表。
2. 保存 Profile 时存储**完整展开后的命令、环境、二进制 `--version`、模型文件 hash、设备清单**，而不只保存表单值。
3. 启动前运行 `llama-server --help`/版本兼容性校验；发现参数不存在、已经移除或与后端不兼容时拒绝重启。
4. Benchmark 记录 `--perf` timing、HTTP 输出 timing、实际输入/输出 token 数、缓存命中状态；不可只记录一个总 tok/s。

## 8. 参考来源

- [llama.cpp 上游参数源码（固定提交）](https://github.com/ggml-org/llama.cpp/blob/c8e03ce8122b7af76f836d53efde6df1ce5ec437/common/arg.cpp)
- [llama.cpp 项目主页](https://github.com/ggml-org/llama.cpp)
- [systemd.service 手册](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)
- [systemd.exec 手册](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
