import sys


def main() -> int:
    # En el .exe de Windows (sin consola) stdout/stderr no existen
    import os
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    # Modo línea de comandos: `netmon --cli ...` (útil para servidores sin escritorio)
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        from netmon.cli import main as cli_main
        return cli_main(sys.argv[2:])
    from netmon.ui.app import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
