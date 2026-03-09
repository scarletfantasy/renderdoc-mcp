from renderdoc_mcp.install import install_extension


def main() -> None:
    target = install_extension()
    print(target)
