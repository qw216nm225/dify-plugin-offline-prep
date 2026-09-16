"""离线重打包：把插件的 Python 依赖轮子打进 .difypkg，供离线服务器安装。

用法: python3 inject.py <输入.difypkg> <输出目录>
步骤:
  1. 解包插件
  2. 原生 pip 下载全部依赖轮子到 wheels/（runner 是 aarch64，无需跨平台参数；
     条件依赖按 Linux 原生环境评估，win32 条目自动跳过）
  3. 在 pyproject.toml 注入 [tool.uv] 离线配置
  4. 重新打包为 <原名>-offline.difypkg
"""
import pathlib
import shutil
import subprocess
import sys
import zipfile


def main() -> None:
    pkg = pathlib.Path(sys.argv[1])
    outdir = pathlib.Path(sys.argv[2])
    stem = pkg.stem
    work = pathlib.Path("work") / stem
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    with zipfile.ZipFile(pkg) as z:
        z.extractall(work)

    req = work / "requirements.txt"
    if not req.exists():
        raise SystemExit(f"requirements.txt 不存在: {pkg}")

    subprocess.run(
        [sys.executable, "-m", "pip", "download",
         "--only-binary=:all:", "--prefer-binary",
         "-r", "requirements.txt", "-d", "wheels"],
        cwd=work, check=True,
    )

    pp = work / "pyproject.toml"
    if pp.exists():
        txt = pp.read_text(encoding="utf-8")
        # 剔除 [dependency-groups] 段：uv sync 默认包含 dev 组，
        # 而 dev 依赖（pytest/ruff/black 等）不在离线轮子里，会导致解析失败。
        lines, skip = [], False
        for line in txt.splitlines():
            if line.startswith("[dependency-groups"):
                skip = True
                continue
            if skip:
                if line.startswith("["):
                    skip = False
                else:
                    continue
            lines.append(line)
        txt = "\n".join(lines) + "\n"
        if "[tool.uv]" not in txt:
            txt += (
                "\n[tool.uv]\n"
                "no-index = true\n"
                'find-links = ["./wheels/"]\n'
                'environments = ["sys_platform == \'linux\'"]\n'
            )
        pp.write_text(txt, encoding="utf-8")

    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"{stem}-offline.difypkg"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(work.rglob("*")):
            if f.is_file() and f.name != "uv.lock":
                # 剔除 uv.lock：存在 lockfile 时 uv sync 按锁定的 PyPI 源安装，
                # 会无视 no-index/find-links 离线配置；去掉后走本地轮子解析。
                z.write(f, f.relative_to(work))

    print(f"done: {out} ({out.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
