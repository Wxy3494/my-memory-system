from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAQ_PATH = PROJECT_ROOT / "docs" / "faq.md"
RULE_HEADER = re.compile(r"## (RULE-[A-Z]+-\d{2}) (.+)")


def load_faq(path: Path = FAQ_PATH) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()

    versions = [
        line.removeprefix("版本：").strip()
        for line in lines
        if line.startswith("版本：")
    ]
    if len(versions) != 1:
        raise ValueError("FAQ 文档必须有且只有一个版本号")

    headings = []
    for line_no, line in enumerate(lines, start=1):
        match = RULE_HEADER.fullmatch(line)
        if match:
            headings.append((line_no, match.group(1), match.group(2)))

    if not headings:
        raise ValueError("没有找到 RULE 标题")

    chunks = []
    seen_ids = set()
    for index, (start_line, rule_id, title) in enumerate(headings):
        next_line = (
            headings[index + 1][0]
            if index + 1 < len(headings)
            else len(lines) + 1
        )
        body = [(n, lines[n - 1]) for n in range(start_line + 1, next_line)]
        questions = [text[2:].strip() for _, text in body if text.startswith("问：")]
        answers = [text[2:].strip() for _, text in body if text.startswith("答：")]

        if rule_id in seen_ids or len(questions) != 1 or len(answers) != 1:
            raise ValueError(f"{rule_id} 重复，或问答数量不是各一条")
        seen_ids.add(rule_id)

        end_line = max(n for n, text in body if text.strip())
        chunks.append({
            "chunk_no": index + 1,
            "chunk_id": rule_id,
            "source": path.relative_to(PROJECT_ROOT).as_posix(),
            "version": versions[0],
            "start_line": start_line,
            "end_line": end_line,
            "title": title,
            "question": questions[0],
            "answer": answers[0],
            "text": "\n".join(lines[start_line - 1:end_line]),
        })

    return chunks


if __name__ == "__main__":
    chunks = load_faq()
    print(f"共 {len(chunks)} 个文档块")
    for chunk in chunks:
        print(
            f"{chunk['chunk_no']:02d} {chunk['chunk_id']} "
            f"{chunk['source']}:{chunk['start_line']}-{chunk['end_line']} "
            f"版本={chunk['version']}"
        )
        print(chunk["text"])
    