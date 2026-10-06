# API 镜像使用 Python 3.13 的 Linux 环境。
# 本机是 3.13.12；此镜像使用 3.13.15，已通过 CPU 模型和接口运行验证。
FROM python:3.13.15-slim-bookworm

# 不生成 Python 字节码；日志直接输出，便于查看容器日志。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 后续安装、复制文件和启动命令均以 /app 为工作目录。
WORKDIR /app

# 为向量模型和数值计算依赖准备 Linux 共享库。
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖清单；应用代码变化时，可以复用依赖安装层。
COPY requirements.txt requirements-linux.lock.txt ./

# 固定当前环境的 PyTorch 基础版本，安装官方 CPU 构建。
# 这样 sentence-transformers 可以复用它，保持 CPU 推理路线。
RUN python -m pip install --no-cache-dir --no-deps "torch==2.14.0+cpu" \
    --index-url https://download.pytorch.org/whl/cpu -c requirements-linux.lock.txt

# 安装项目依赖，并检查包之间声明的依赖是否兼容。
RUN python -m pip install --no-cache-dir -r requirements.txt -c requirements-linux.lock.txt \
    && python -m pip check

# 复制应用、FAQ 和独立入库脚本。
# 实际配置、模型缓存和数据库数据由运行时配置或挂载提供。
COPY app/ ./app/
COPY docs/ ./docs/
COPY index_faq.py ./

# 声明 API 使用的容器端口；宿主机端口映射将在 Compose 中配置。
EXPOSE 8000

# 容器启动时运行 API。FAQ 入库仍是独立操作。
# 监听 0.0.0.0，让请求可以从容器外经端口映射进入。
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

