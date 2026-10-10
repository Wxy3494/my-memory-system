# 被测版本的只读核验

截图版本v1.0、公开commit、本地v4/v5及内部schema是不同身份，必须核对后才可映射。当前公开GitHub读取到的commit是142f0ddcdd2ccc06b044c47f2777a99d3b3707e9；没有据此认定线上必为旧版。

先在平台已有版本详情核对绑定Add/Search地址和commit，只查看，不保存、重绑定或启动评测。服务器上的API容器名用下面命令读取，不能凭历史文档猜：

```bash
docker ps --format '{{.ID}} {{.Names}} {{.Image}}'
```

选定真实API容器后，`docker inspect --format '{{.Id}} {{.Image}} {{.Config.Image}}' <实际容器>` 只显示身份和镜像，不打印环境变量。源码/非敏感配置可用如下只读内容通过 `docker exec -i <实际容器> python -` 执行；没有Add、Search或模型探测，不修改文件：

```python
import hashlib, json
from pathlib import Path
from app.memory.config import MemoryConfig
from app.memory.store import PostgresStore
c = MemoryConfig.from_env()
paths = sorted(Path('app/memory').glob('*.py')) + sorted(Path('migrations').glob('*.sql'))
with PostgresStore(c).connection() as conn:
    row = conn.execute('SELECT version FROM memory.schema_version WHERE singleton').fetchone()
    schema = row['version'] if isinstance(row, dict) else row[0]
print(json.dumps({
    'source_hashes': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
    'schema': schema, 'model': c.model, 'dimension': c.dimension,
    'retrieval': c.retrieval, 'window': getattr(c, 'neighbor_window', 0),
    'seed_limit': getattr(c, 'seed_limit', None), 'bytes': getattr(c, 'evidence_bytes', None),
    'contextual': getattr(c, 'contextual', False),
    'pipeline_signature': c.signature
}))
```

新版另有鉴权只读 `GET /v1/memories/version` 和 `scripts/capture_memory_runtime.py`。旧镜像可能没有它们，404或代理拒绝不能单独证明运行版本。普通health仅表明存活，pipeline_signature只覆盖Embedding/分块构型，不能代表全部检索实现。密钥不用显示或传入聊天。

当前浏览器控制运行时初始化失败，未读取平台登录后的绑定或私有逐题结果；版本映射继续待核验。本文件是准备好的检查方式，不是已在服务器执行的记录。`deploy/accept-memory-server.sh` 包含真实Add/模型调用，不能当作本文件的无付费只读命令运行。

私有失败导出可位于项目之外的安全下载目录，或者忽略目录`.private-eval/`。`scripts/diagnose_memory_trace.py`只接受规范化字段，不猜生产合同；结果强制落在新的`.private-eval/`子目录，打包工具显式排除该目录及platform-private路径。不要上传原始题、金标或答案到公开GitHub/ZIP。
