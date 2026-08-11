"""读取 README.md 并打印第一行。"""

from pathlib import Path

def main():
    readme = Path(__file__).parent / "README.md"
    with open(readme, "r", encoding="utf-8") as f:
        first_line = f.readline().rstrip("\n")
    print(first_line)

if __name__ == "__main__":
    main()
