from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="启动参考文献异常检测 HTTP 微服务",
    )
    parser.add_argument(
        "--host",
        help="监听地址（默认读 REFERENCE_API_HOST，否则 0.0.0.0）",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="监听端口（默认读 REFERENCE_API_PORT，否则 18080）",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="开发模式热重载（生产环境勿用）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    from reference_anomaly_detection.api.settings import get_settings

    args = build_parser().parse_args(argv)
    settings = get_settings()
    host = args.host or settings.host
    port = args.port or settings.port

    uvicorn.run(
        "reference_anomaly_detection.api.app:app",
        host=host,
        port=port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
